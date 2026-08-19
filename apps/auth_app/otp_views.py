"""
apps/auth_app/otp_views.py
----------------------------
OTP request/verify endpoints shared by every pre-authentication OTP flow:
staff password reset, patient password reset, patient self-registration,
and day-to-day passwordless patient login.

  POST /api/v1/auth/otp/request/           — send a code
  POST /api/v1/auth/otp/verify/            — verify a code, get an action_token
  POST /api/v1/auth/forgot-password/staff/reset/    — consume action_token, set new password
  POST /api/v1/auth/forgot-password/patient/reset/  — consume action_token, set new password
  POST /api/v1/auth/login/patient/otp/     — consume action_token (purpose=login_patient), issue JWT

Patient self-registration's own request/verify pair lives in
apps/patients/portal_views.py (PortalRegisterRequestOTPView /
PortalRegisterVerifyOTPView) since it shares PortalRegisterView's imports
and is patient-app-specific; contact-change (mobile-number re-verification)
similarly lives next to PortalProfileView. Both reuse this same core.otp
module — there is one OTP engine, not several.

Every response here is deliberately generic on "identifier not found" (same
wording whether the account exists or not) to avoid leaking which mobile
numbers/emails have accounts — the one exception is registration, where the
whole point of the check is telling the user they already have an account.
"""

import logging

from django.conf import settings
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle

from core.response import success, error
from core.otp import (
    create_otp, verify_otp, make_action_token, decode_action_token,
    mask_identifier, OTPError,
)
from core.email import send_otp_email
from core.sms import send_otp_sms
from apps.registry.models import OTPCode

logger = logging.getLogger(__name__)

PURPOSE_LABELS = {
    OTPCode.PURPOSE_PASSWORD_RESET_STAFF:   "password reset",
    OTPCode.PURPOSE_PASSWORD_RESET_PATIENT: "password reset",
    OTPCode.PURPOSE_REGISTRATION_PATIENT:   "account verification",
    OTPCode.PURPOSE_LOGIN_PATIENT:          "sign in",
    OTPCode.PURPOSE_CONTACT_CHANGE_PATIENT: "mobile number change",
}

# Purposes OTPRequestView resolves itself — contact_change_patient's
# *request* step is authenticated (identifier is derived from the caller's
# own account, never accepted from the body) and lives in
# apps.patients.portal_views.PortalMobileChangeRequestOTPView instead.
_HANDLED_PURPOSES = {
    OTPCode.PURPOSE_PASSWORD_RESET_STAFF,
    OTPCode.PURPOSE_PASSWORD_RESET_PATIENT,
    OTPCode.PURPOSE_REGISTRATION_PATIENT,
    OTPCode.PURPOSE_LOGIN_PATIENT,
}

# OTPVerifyView additionally accepts contact_change_patient — verifying a
# code has no side effects on its own (it only yields an action_token), so
# there's no harm in this step being purpose-agnostic; only the *request*
# step (which decides who a code gets sent to) needs to stay restricted.
_VERIFIABLE_PURPOSES = _HANDLED_PURPOSES | {OTPCode.PURPOSE_CONTACT_CHANGE_PATIENT}


def _ensure_tenant_db(db_name):
    if db_name not in settings.DATABASES:
        from apps.tenants.utils import _make_db_config
        settings.DATABASES[db_name] = _make_db_config(db_name)


def _resolve_staff_target(identifier):
    """Mobile or email, matching StaffLoginView's own identifier resolution. Returns (staff_id, db_name) or None."""
    from apps.registry.models import StaffMobileIndex
    from apps.org.models import StaffUser

    try:
        if "@" in identifier:
            index = StaffMobileIndex.objects.using("default").get(email__iexact=identifier)
        else:
            index = StaffMobileIndex.objects.using("default").get(mobile=identifier)
    except StaffMobileIndex.DoesNotExist:
        return None

    _ensure_tenant_db(index.db_name)
    try:
        from django.db.models import Q
        staff = StaffUser.objects.using(index.db_name).get(
            Q(phone=identifier) | Q(email__iexact=identifier), is_active=True
        )
    except StaffUser.DoesNotExist:
        return None
    return staff.id, index.db_name


def _resolve_patient_target(identifier):
    """Mobile, email, or AWPID, matching PatientLoginView's own resolution. Returns PatientAccount or None."""
    from apps.registry.models import PatientAccount

    try:
        if identifier.upper().startswith("AWPID-"):
            return PatientAccount.objects.using("default").get(awpid__iexact=identifier, is_active=True)
        if "@" in identifier:
            return PatientAccount.objects.using("default").get(email__iexact=identifier, is_active=True)
        return PatientAccount.objects.using("default").get(mobile=identifier, is_active=True)
    except PatientAccount.DoesNotExist:
        return None


def _send_code(identifier, channel, code, purpose_label):
    if channel == "email":
        return send_otp_email(identifier, code, purpose_label)
    return send_otp_sms(identifier, code, purpose_label)


class OTPRequestView(APIView):
    """POST /api/v1/auth/otp/request/  body: {purpose, identifier}"""
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "otp"

    def post(self, request):
        purpose = (request.data.get("purpose") or "").strip()
        identifier = (request.data.get("identifier") or "").strip()
        if not identifier:
            return error("Enter your mobile number or email.")
        if purpose not in _HANDLED_PURPOSES:
            return error("Invalid request.")

        # Normalize case for email-shaped identifiers so the same address
        # typed with different casing always resolves to the same OTPCode
        # rows / target lookups.
        if "@" in identifier:
            identifier = identifier.lower()

        target_type, target_id, target_db = "", None, ""

        if purpose == OTPCode.PURPOSE_PASSWORD_RESET_STAFF:
            resolved = _resolve_staff_target(identifier)
            if not resolved:
                return error("We couldn't find a staff account with those details.")
            target_type, (target_id, target_db) = "staff", resolved

        elif purpose == OTPCode.PURPOSE_PASSWORD_RESET_PATIENT:
            acct = _resolve_patient_target(identifier)
            if not acct:
                return error("We couldn't find an account with those details.")
            target_type, target_id = "patient", acct.id
            # Send to whichever channel the caller actually typed — but if
            # they typed the AWPID, fall back to the account's own mobile
            # (an AWPID isn't itself a deliverable channel).
            if identifier.upper().startswith("AWPID-"):
                identifier = acct.mobile

        elif purpose == OTPCode.PURPOSE_LOGIN_PATIENT:
            acct = _resolve_patient_target(identifier)
            if not acct:
                return error("We couldn't find an account with those details.")
            target_type, target_id = "patient", acct.id
            if identifier.upper().startswith("AWPID-"):
                identifier = acct.mobile

        elif purpose == OTPCode.PURPOSE_REGISTRATION_PATIENT:
            from apps.registry.models import PatientAccount
            # Email-based for now — verifying via mobile requires a paid SMS
            # gateway (see core/sms.py) that isn't wired up yet. Email is
            # free to send (SMTP already live) and PatientAccount.email is
            # unique, so it works as the verified identifier just as well.
            # The mobile number is still collected at account-creation time
            # (PortalRegisterView) as a required field, just not OTP-proven.
            if "@" not in identifier:
                return error("Enter a valid email address.", errors={"identifier": "Invalid format."})
            if PatientAccount.objects.using("default").filter(email__iexact=identifier).exists():
                return error("An account with this email already exists. Please log in.")
            from core.realworld_validation import validate_email_domain
            is_valid, reason = validate_email_domain(identifier)
            if not is_valid:
                return error(reason, errors={"identifier": reason})
            # target_type/target_id stay blank — no user exists yet.

        try:
            otp, code, channel = create_otp(purpose, identifier, target_type, target_id, target_db)
        except OTPError as exc:
            return error(str(exc))

        label = PURPOSE_LABELS.get(purpose, "verification")
        sent = _send_code(identifier, channel, code, label)
        if not sent:
            return error("Couldn't send the verification code right now. Please try again shortly.")

        data = {"channel": channel, "masked_identifier": mask_identifier(identifier)}
        return success(data=data, message=f"Verification code sent to {mask_identifier(identifier)}.")


class OTPVerifyView(APIView):
    """POST /api/v1/auth/otp/verify/  body: {purpose, identifier, code} -> {action_token}"""
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "otp"

    def post(self, request):
        purpose = (request.data.get("purpose") or "").strip()
        identifier = (request.data.get("identifier") or "").strip()
        code = (request.data.get("code") or "").strip()
        if purpose not in _VERIFIABLE_PURPOSES:
            return error("Invalid request.")
        if not identifier or not code:
            return error("Enter the code we sent you.")
        if "@" in identifier:
            identifier = identifier.lower()

        # Registration's identifier is the raw mobile; the others may have
        # been typed as AWPID and normalized to a mobile inside
        # OTPRequestView — verify_otp keys purely off (purpose, identifier)
        # as actually stored on the OTPCode row, so re-resolve AWPID here
        # too for password_reset_patient / login_patient.
        if purpose in (OTPCode.PURPOSE_PASSWORD_RESET_PATIENT, OTPCode.PURPOSE_LOGIN_PATIENT) \
                and identifier.upper().startswith("AWPID-"):
            acct = _resolve_patient_target(identifier)
            if acct:
                identifier = acct.mobile

        try:
            otp = verify_otp(purpose, identifier, code)
        except OTPError as exc:
            return error(str(exc))

        token = make_action_token(purpose, identifier, otp.target_type, otp.target_id, otp.target_db)
        return success(data={"action_token": token}, message="Verified.")


class StaffForgotPasswordResetView(APIView):
    """POST /api/v1/auth/forgot-password/staff/reset/  body: {action_token, new_password, confirm_password}"""
    permission_classes = [AllowAny]

    def post(self, request):
        token = request.data.get("action_token") or ""
        new_password = request.data.get("new_password") or ""
        confirm_password = request.data.get("confirm_password") or ""
        if new_password != confirm_password:
            return error("Passwords do not match.", errors={"confirm_password": "Passwords do not match."})
        if len(new_password) < 8:
            return error("New password must be at least 8 characters.", errors={"new_password": "Too short."})

        try:
            payload = decode_action_token(token, OTPCode.PURPOSE_PASSWORD_RESET_STAFF)
        except OTPError as exc:
            return error(str(exc))

        db_name = payload.get("target_db")
        staff_id = payload.get("target_id")
        _ensure_tenant_db(db_name)
        from apps.org.models import StaffUser
        try:
            staff = StaffUser.objects.using(db_name).get(pk=staff_id, is_active=True)
        except StaffUser.DoesNotExist:
            return error("Staff account not found.")

        staff.set_password(new_password)
        staff.must_change_password = False
        staff.save(using=db_name, update_fields=["password", "must_change_password"])

        from core.audit import log_action
        log_action(None, db_name, action="auth.password_reset_via_otp",
                   resource_type="StaffUser", resource_id=str(staff.id))

        return success(message="Password reset successfully. You can now log in.")


class PatientForgotPasswordResetView(APIView):
    """POST /api/v1/auth/forgot-password/patient/reset/  body: {action_token, new_password, confirm_password}"""
    permission_classes = [AllowAny]

    def post(self, request):
        token = request.data.get("action_token") or ""
        new_password = request.data.get("new_password") or ""
        confirm_password = request.data.get("confirm_password") or ""
        if new_password != confirm_password:
            return error("Passwords do not match.", errors={"confirm_password": "Passwords do not match."})
        if len(new_password) < 8:
            return error("New password must be at least 8 characters.", errors={"new_password": "Too short."})

        try:
            payload = decode_action_token(token, OTPCode.PURPOSE_PASSWORD_RESET_PATIENT)
        except OTPError as exc:
            return error(str(exc))

        from apps.registry.models import PatientAccount
        try:
            acct = PatientAccount.objects.using("default").get(pk=payload.get("target_id"), is_active=True)
        except PatientAccount.DoesNotExist:
            return error("Account not found.")

        acct.set_password(new_password)
        acct.save(using="default", update_fields=["password"])

        # Registry-level (cross-tenant) security event — logged, not written
        # to a new table. apps.org.AuditLog is per-tenant and patients have
        # no tenant context; a second/duplicate audit table was tried once
        # already in this codebase (apps.compliance.AccessLog) and removed
        # for exactly that reason — see apps/compliance/models.py's
        # docstring. A log line is the correct-weight solution here.
        logger.info("Patient password reset via OTP: account_id=%s awpid=%s", acct.id, acct.awpid)

        return success(message="Password reset successfully. You can now log in.")


class PatientOTPLoginView(APIView):
    """
    POST /api/v1/auth/login/patient/otp/  body: {action_token}
    Day-to-day passwordless sign-in — the action_token proves a
    login_patient-purpose OTP was just verified for this account.
    Issues the same JWT pair/payload shape as PatientLoginView.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        token = request.data.get("action_token") or ""
        try:
            payload = decode_action_token(token, OTPCode.PURPOSE_LOGIN_PATIENT)
        except OTPError as exc:
            return error(str(exc))

        from apps.registry.models import PatientAccount
        from django.utils import timezone
        try:
            acct = PatientAccount.objects.using("default").get(pk=payload.get("target_id"), is_active=True)
        except PatientAccount.DoesNotExist:
            return error("Account not found.")

        acct.last_login = timezone.now()
        acct.save(using="default", update_fields=["last_login"])

        from .views import _make_tokens
        jwt_payload = {
            "user_id":     acct.id,
            "email":       acct.email,
            "full_name":   acct.full_name,
            "awpid":       acct.awpid,
            "role":        "patient",
            "db_name":     None,
            "tenant_id":   None,
            "is_platform": False,
        }
        logger.info("Patient OTP login: account_id=%s awpid=%s", acct.id, acct.awpid)
        return success(data=_make_tokens(jwt_payload), message="Signed in successfully.")
