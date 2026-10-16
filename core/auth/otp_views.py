"""core/auth/otp_views.py"""

import logging


from apps.hospital_master.services import ensure_hospital_db
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle

from core.api.response import success, error
from core.messaging.otp import (
    create_otp, verify_otp, make_action_token, decode_action_token,
    mask_identifier, OTPError,
)
from core.messaging.email import send_otp_email
from core.messaging.sms import send_otp_sms
from apps.patients.models import OTPCode
from apps.patients.models import Patient
from apps.patients.services import accounts, accounts_with_mobile, set_password

logger = logging.getLogger(__name__)

PURPOSE_LABELS = {
    OTPCode.PURPOSE_PASSWORD_RESET_STAFF:   "password reset",
    OTPCode.PURPOSE_PASSWORD_RESET_PATIENT: "password reset",
    OTPCode.PURPOSE_REGISTRATION_PATIENT:   "account verification",
    OTPCode.PURPOSE_LOGIN_PATIENT:          "sign in",
    OTPCode.PURPOSE_CONTACT_CHANGE_PATIENT: "mobile number change",
}

# Purposes OTPRequestView resolves itself — contact_change_patient's
_HANDLED_PURPOSES = {
    OTPCode.PURPOSE_PASSWORD_RESET_STAFF,
    OTPCode.PURPOSE_PASSWORD_RESET_PATIENT,
    OTPCode.PURPOSE_REGISTRATION_PATIENT,
    OTPCode.PURPOSE_LOGIN_PATIENT,
}

# OTPVerifyView additionally accepts contact_change_patient — verifying a
_VERIFIABLE_PURPOSES = _HANDLED_PURPOSES | {OTPCode.PURPOSE_CONTACT_CHANGE_PATIENT}


def _resolve_staff_target(identifier):
    """Mobile or email, matching StaffLoginView's own identifier resolution. Returns (staff_id, db_name) or None."""
    from apps.patients.models import StaffMobileIndex
    from apps.hospital_setup.models import StaffUser

    try:
        if "@" in identifier:
            index = StaffMobileIndex.objects.using("default").get(email__iexact=identifier)
        else:
            index = StaffMobileIndex.objects.using("default").get(mobile=identifier)
    except StaffMobileIndex.DoesNotExist:
        return None

    ensure_hospital_db(index.hospital.db_name)
    try:
        from django.db.models import Q
        staff = StaffUser.objects.using(index.hospital.db_name).get(
            Q(phone=identifier) | Q(email__iexact=identifier), is_active=True
        )
    except StaffUser.DoesNotExist:
        return None
    return staff.id, index.hospital.db_name


def _resolve_patient_target(identifier):
    """Mobile, email, or AWPID, matching PatientLoginView's own resolution. Returns PatientAccount or None."""

    try:
        if identifier.upper().startswith("AWPID-"):
            return accounts().get(awpid__iexact=identifier, is_active=True)
        if "@" in identifier:
            return accounts().get(email__iexact=identifier, is_active=True)
        return accounts_with_mobile(identifier).get(is_active=True)
    except Patient.DoesNotExist:
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
            # Send to whichever channel the caller actually typed — but if they typed the AWPID (not itself a
            if identifier.upper().startswith("AWPID-"):
                if not acct.email:
                    return error("There is no email on this account. Enter your mobile number instead.")
                identifier = acct.email.lower()

        elif purpose == OTPCode.PURPOSE_LOGIN_PATIENT:
            acct = _resolve_patient_target(identifier)
            if not acct:
                return error("We couldn't find an account with those details.")
            target_type, target_id = "patient", acct.id
            if identifier.upper().startswith("AWPID-"):
                if not acct.email:
                    return error("There is no email on this account. Enter your mobile number instead.")
                identifier = acct.email.lower()

        elif purpose == OTPCode.PURPOSE_REGISTRATION_PATIENT:
            # Email-based for now — verifying via mobile requires a paid SMS
            if "@" not in identifier:
                return error("Enter a valid email address.", errors={"identifier": "Invalid format."})
            if accounts().filter(email__iexact=identifier).exists():
                return error("An account with this email already exists. Please log in.")
            from core.utils.realworld_validation import validate_email_domain
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
        if purpose in (OTPCode.PURPOSE_PASSWORD_RESET_PATIENT, OTPCode.PURPOSE_LOGIN_PATIENT) \
                and identifier.upper().startswith("AWPID-"):
            acct = _resolve_patient_target(identifier)
            if acct and acct.email:
                identifier = acct.email.lower()

        try:
            otp = verify_otp(purpose, identifier, code)
        except OTPError as exc:
            return error(str(exc))

        token = make_action_token(purpose, identifier, otp.target_type, otp.target_id, (otp.hospital.db_name if otp.hospital_id else ""))
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
        ensure_hospital_db(db_name)
        from apps.hospital_setup.models import StaffUser
        try:
            staff = StaffUser.objects.using(db_name).get(pk=staff_id, is_active=True)
        except StaffUser.DoesNotExist:
            return error("Staff account not found.")

        staff.set_password(new_password)
        staff.must_change_password = False
        staff.save(using=db_name, update_fields=["password", "must_change_password"])

        from core.utils.audit import log_action
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

        try:
            acct = accounts().get(pk=payload.get("target_id"), is_active=True)
        except Patient.DoesNotExist:
            return error("Account not found.")

        set_password(acct, new_password)
        acct.save(using="default", update_fields=["password"])

        # Atomwalk-level (cross-hospital) security event — logged, not written
        logger.info("Patient password reset via OTP: account_id=%s awpid=%s", acct.id, acct.awpid)

        return success(message="Password reset successfully. You can now log in.")


class PatientOTPLoginView(APIView):
    """POST /api/v1/auth/login/patient/otp/  body: {action_token}"""
    permission_classes = [AllowAny]

    def post(self, request):
        token = request.data.get("action_token") or ""
        try:
            payload = decode_action_token(token, OTPCode.PURPOSE_LOGIN_PATIENT)
        except OTPError as exc:
            return error(str(exc))

        from django.utils import timezone
        try:
            acct = accounts().get(pk=payload.get("target_id"), is_active=True)
        except Patient.DoesNotExist:
            return error("Account not found.")

        acct.last_login = timezone.now()
        acct.save(using="default", update_fields=["last_login"])

        from core.auth.views import _make_tokens
        jwt_payload = {
            "user_id":     acct.id,
            "email":       acct.email,
            "full_name":   acct.full_name,
            "awpid":       acct.awpid,
            "role":        "patient",
            "db_name":     None,
            "hospital_id":   None,
            "is_platform": False,
        }
        logger.info("Patient OTP login: account_id=%s awpid=%s", acct.id, acct.awpid)
        return success(data=_make_tokens(jwt_payload), message="Signed in successfully.")
