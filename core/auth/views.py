"""core/auth/views.py"""

import jwt
import logging
import secrets
from datetime import timedelta
from django.conf import settings
from django.contrib.auth import authenticate
from django.db.models import Q
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.throttling import ScopedRateThrottle

from core.api.response import success, error
from apps.hospital_master.models import Hospital, Subscription
from apps.hospital_master.services import TIER_FEATURE_DEFAULTS
from apps.hospital_setup.models import StaffUser
from apps.patients.models import StaffMobileIndex

logger = logging.getLogger(__name__)

from core.auth.serializers import (
    StaffLoginSerializer,
    PlatformLoginSerializer,
    SetupPasswordSerializer,
    ChangePasswordSerializer,
)
from apps.patients.models import Patient
from apps.patients.services import accounts, accounts_with_mobile, check_password


def _make_tokens(payload: dict) -> dict:
    """Create access + refresh JWT pair from a claims payload."""
    now         = timezone.now()
    access_exp  = now + settings.JWT_ACCESS_TOKEN_LIFETIME
    refresh_exp = now + settings.JWT_REFRESH_TOKEN_LIFETIME

    access_payload  = {**payload, "exp": access_exp,  "token_type": "access",  "jti": secrets.token_hex(16)}
    refresh_payload = {**payload, "exp": refresh_exp, "token_type": "refresh", "jti": secrets.token_hex(16)}

    return {
        "access":  jwt.encode(access_payload,  settings.JWT_SIGNING_KEY, algorithm="HS256"),
        "refresh": jwt.encode(refresh_payload, settings.JWT_SIGNING_KEY, algorithm="HS256"),
    }


# ── Staff Login ───────────────────────────────────────────────────────────────

class StaffLoginView(APIView):
    """POST /api/v1/auth/login/staff/"""
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        serializer = StaffLoginSerializer(data=request.data)
        if not serializer.is_valid():
            return error("Validation error.", errors=serializer.errors)

        d = serializer.validated_data
        login_by_employee_id = bool(d.get("hospital_code")) and bool(d.get("employee_id"))

        if login_by_employee_id:
            # ── Step 1 (employee-ID path): resolve hospital directly by hospital_code ──
            try:
                hospital = Hospital.objects.get(hospital_code__iexact=d["hospital_code"], is_active=True)
            except Hospital.DoesNotExist:
                return error("Invalid credentials.")
            db_name, hospital_id = hospital.db_name, hospital.id
        else:
            # ── Step 1 (mobile/email path): look up which hospital DB this
            identifier = d["mobile"]
            try:
                if "@" in identifier:
                    index = StaffMobileIndex.objects.using("default").get(email__iexact=identifier)
                else:
                    index = StaffMobileIndex.objects.using("default").get(mobile=identifier)
            except StaffMobileIndex.DoesNotExist:
                return error("Invalid credentials.")
            db_name, hospital_id = index.hospital.db_name, index.hospital_id

            # ── Step 2: Verify hospital is active ───────────────────────────────
            try:
                hospital = Hospital.objects.get(pk=hospital_id, is_active=True)
            except Hospital.DoesNotExist:
                return error("This hospital account is inactive. Contact Atomwalk support.")

        # ── Step 3: Ensure hospital DB is registered ────────────────────────────
        from apps.hospital_master.services import ensure_hospital_db
        ensure_hospital_db(db_name)

        # ── Step 4: Fetch StaffUser from hospital DB ────────────────────────────
        try:
            if login_by_employee_id:
                staff = StaffUser.objects.using(db_name).select_related("custom_role").get(
                    employee_id=d["employee_id"], is_active=True
                )
            else:
                staff = StaffUser.objects.using(db_name).select_related("custom_role").get(
                    Q(phone=d["mobile"]) | Q(email__iexact=d["mobile"]), is_active=True
                )
        except StaffUser.DoesNotExist:
            return error("Invalid credentials.")

        # ── Step 5: Check password ─────────────────────────────────────────────
        if staff.password == "!":
            return error(
                "Account not activated. Please set your password via the invite link.",
                status=403,
            )

        if not staff.check_password(d["password"]):
            return error("Invalid credentials.")

        # ── Step 6: Get subscription ───────────────────────────────────────────
        try:
            subscription = Subscription.objects.get(hospital=hospital)
        except Subscription.DoesNotExist:
            return error("Subscription not found.")

        from apps.hospital_setup.rbac import resolve_acts_as
        payload = {
            "user_id":      staff.id,
            "email":        staff.email,
            "full_name":    staff.get_full_name(),
            "role":         staff.role,
            # [] for the 6 system roles — see resolve_acts_as() and
            "acts_as":      sorted(resolve_acts_as(staff)),
            # Display-only — lets the sidebar/topbar show "Doctor Clinic"
            "custom_role_name": staff.custom_role.name if staff.role == "custom" and staff.custom_role else None,
            "db_name":      db_name,
            "hospital_id":    hospital_id,
            "hospital_name": hospital.name,
            "license_tier": subscription.license_tier,
            "is_platform":  False,
            "branch_id":    staff.branch_id,
        }

        # Update last_login
        staff.last_login = timezone.now()
        staff.save(using=db_name, update_fields=["last_login"])

        return success(data={
            **_make_tokens(payload),
            "must_change_password": staff.must_change_password,
        }, message="Login successful.")


# ── Platform Admin Login ──────────────────────────────────────────────────────

class PlatformLoginView(APIView):
    """POST /api/v1/auth/login/platform/"""
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        serializer = PlatformLoginSerializer(data=request.data)
        if not serializer.is_valid():
            return error("Validation error.", errors=serializer.errors)

        d = serializer.validated_data
        login_id = d["username"]  # may be username or email
        password = d["password"]

        # Try by username first
        user = authenticate(request, username=login_id, password=password)

        # Fallback: look up by email then authenticate by real username
        if not user:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            try:
                user_obj = User.objects.get(email=login_id, is_superuser=True)
                user = authenticate(request, username=user_obj.username, password=password)
            except User.DoesNotExist:
                pass

        if not user or not user.is_superuser:
            return error("Invalid credentials.")

        payload = {
            "user_id":     user.id,
            "email":       user.email,
            "username":    user.username,
            "role":        "platform_admin",
            "is_platform": True,
            "db_name":     None,
            "hospital_id":   None,
            "license_tier": "enterprise",
        }

        return success(data=_make_tokens(payload), message="Platform login successful.")


# ── Patient Login ─────────────────────────────────────────────────────────────

class PatientLoginView(APIView):
    """POST /api/v1/auth/login/patient/"""
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):

        login_id = (request.data.get("mobile") or request.data.get("awpid") or "").strip()
        password = request.data.get("password") or ""
        if not login_id or not password:
            return error("Mobile number and password are required.")

        try:
            if login_id.upper().startswith("AWPID-"):
                acct = accounts().get(awpid=login_id, is_active=True)
            elif "@" in login_id:
                acct = accounts().get(email__iexact=login_id, is_active=True)
            else:
                acct = accounts_with_mobile(login_id).get(is_active=True)
        except Patient.DoesNotExist:
            return error("Invalid credentials.")

        if not check_password(acct, password):
            return error("Invalid credentials.")

        acct.last_login = timezone.now()
        acct.save(using="default", update_fields=["last_login"])

        payload = {
            "user_id":     acct.id,
            "email":       acct.email,
            "full_name":   acct.full_name,
            "awpid":       acct.awpid,
            "role":        "patient",
            "db_name":     None,
            "hospital_id":   None,
            "is_platform": False,
        }
        return success(data=_make_tokens(payload), message="Login successful.")


# ── Setup Password (invite flow) ──────────────────────────────────────────────

class SetupPasswordView(APIView):
    """POST /api/v1/auth/setup-password/"""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SetupPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return error("Validation error.", errors=serializer.errors)

        d = serializer.validated_data

        # Decode the invite token
        try:
            payload = jwt.decode(
                d["invite_token"],
                settings.JWT_SIGNING_KEY,
                algorithms=["HS256"],
            )
        except jwt.ExpiredSignatureError:
            return error("Invite link has expired. Ask your admin to re-invite you.")
        except jwt.InvalidTokenError:
            return error("Invalid invite token.")

        if payload.get("token_type") != "invite":
            return error("Invalid token type.")

        staff_id  = payload["staff_id"]
        hospital_db = payload["hospital_db"]

        # Validate DB exists
        if hospital_db not in settings.DATABASES:
            return error("Invalid invite token — hospital not found.")

        try:
            staff = StaffUser.objects.using(hospital_db).get(pk=staff_id, is_active=True)
        except StaffUser.DoesNotExist:
            return error("Staff account not found or deactivated.")

        staff.set_password(d["new_password"])
        staff.save(using=hospital_db, update_fields=["password"])

        return success(message="Password set successfully. You can now log in.")


# ── Change Password ───────────────────────────────────────────────────────────

class ChangePasswordView(APIView):
    """POST /api/v1/auth/change-password/"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return error("Validation error.", errors=serializer.errors)

        d = serializer.validated_data

        if request.is_platform:
            return error("Platform admins change passwords via Django admin.")

        db_name = request.hospital_db
        try:
            staff = StaffUser.objects.using(db_name).get(
                pk=request.user.id, is_active=True
            )
        except StaffUser.DoesNotExist:
            return error("Staff account not found.")

        # Forced first-login change (must_change_password=True) skips this —
        if not staff.must_change_password:
            current = d.get("current_password") or ""
            if not current:
                return error("Current password is required.", errors={"current_password": "Required."})
            if not staff.check_password(current):
                return error("Current password is incorrect.", errors={"current_password": "Incorrect."})

        staff.set_password(d["new_password"])
        staff.must_change_password = False
        staff.save(using=db_name, update_fields=["password", "must_change_password"])

        return success(message="Password changed successfully.")


# ── Forgot Password (staff) ───────────────────────────────────────────────────


# ── Me / Permissions ──────────────────────────────────────────────────────────

class MeView(APIView):
    """GET /api/v1/auth/me/ — returns the current user's context."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        p = request.jwt_payload
        data = {
            "user_id":    p.get("user_id"),
            "email":      p.get("email"),
            "full_name":  p.get("full_name", ""),
            "role":       p.get("role"),
            "hospital_id":  p.get("hospital_id"),
            "db_name":    p.get("db_name"),
            "hospital_name": p.get("hospital_name", ""),
            "is_platform": p.get("is_platform", False),
        }

        # The JWT itself never carries the profile photo (a multi-KB base64
        data["photo"] = ""
        try:
            from core import storage as blob_storage
            if p.get("role") == "patient":
                acct = accounts().get(pk=p.get("user_id"))
                data["photo"] = blob_storage.signed_url(acct.photo)
            elif not p.get("is_platform") and p.get("db_name"):
                staff = StaffUser.objects.using(p["db_name"]).get(pk=p.get("user_id"))
                data["photo"] = blob_storage.signed_url(staff.photo)
        except Exception:
            # Best-effort: platform admins (no row to look up) and missing/
            logger.debug("MeView: could not resolve photo for user_id=%s role=%s", p.get("user_id"), p.get("role"), exc_info=True)

        # Hospital's own logo (Hospital.logo, uploaded via /org/settings/) —
        data["logo"] = ""
        if not p.get("is_platform") and p.get("role") != "patient" and p.get("hospital_id"):
            try:
                from core import storage as blob_storage
                hospital = Hospital.objects.using("default").get(pk=p["hospital_id"])
                from apps.hospital_master.services import parameters_of
                data["logo"] = blob_storage.signed_url(parameters_of(hospital).logo)
            except Exception:
                logger.debug("MeView: could not resolve hospital logo for hospital_id=%s", p.get("hospital_id"), exc_info=True)

        return success(data=data)


class PermissionsView(APIView):
    """GET /api/v1/auth/me/permissions/ — subscription feature flags."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.is_platform:
            # Platform admin gets everything — pulled from the enterprise tier's
            return success(data={
                **TIER_FEATURE_DEFAULTS["enterprise"],
                "license_tier": "enterprise", "subscription_status": "active",
                "max_doctors": 0, "max_branches": 0, "max_staff": 0,
                "usage": {"doctors": None, "branches": None, "staff": None},
            })

        try:
            hospital = Hospital.objects.get(pk=request.hospital_id)
            sub    = Subscription.objects.get(hospital=hospital)
        except (Hospital.DoesNotExist, Subscription.DoesNotExist):
            return error("Subscription not found.")

        # Live usage against the tier's limits — lets the frontend disable
        from apps.hospital_master.services import get_usage_counts
        try:
            usage = get_usage_counts(request.hospital_db)
        except Exception:
            usage = {"doctors": None, "branches": None, "staff": None}

        return success(data={
            "feat_lab":          sub.feat_lab,
            "feat_pharmacy":     sub.feat_pharmacy,
            "feat_whatsapp":     sub.feat_whatsapp,
            "feat_multi_branch": sub.feat_multi_branch,
            "feat_ai_voice":     sub.feat_ai_voice,
            "feat_patient_app":  sub.feat_patient_app,
            "feat_analytics":    sub.feat_analytics,
            "feat_video":        sub.feat_video,
            "feat_face_recog":   sub.feat_face_recog,
            "feat_custom_roles": sub.feat_custom_roles,
            "license_tier":      sub.license_tier,
            "subscription_status": sub.status,
            "max_doctors":       sub.max_doctors,
            "max_branches":      sub.max_branches,
            "max_staff":         sub.max_staff,
            "usage":             usage,
        })


# ── Token Refresh ─────────────────────────────────────────────────────────────

class TokenRefreshView(APIView):
    """POST /api/v1/auth/token/refresh/"""
    permission_classes = [AllowAny]

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return error("Refresh token required.")
        try:
            payload = jwt.decode(
                refresh_token, settings.JWT_SIGNING_KEY, algorithms=["HS256"]
            )
            if payload.get("token_type") != "refresh":
                raise jwt.InvalidTokenError("Not a refresh token.")
        except jwt.ExpiredSignatureError:
            return error("Refresh token expired. Please log in again.", status=401)
        except jwt.InvalidTokenError:
            return error("Invalid refresh token.", status=401)

        from apps.patients.models import BlacklistedToken
        if payload.get("jti") and BlacklistedToken.objects.using("default").filter(jti=payload["jti"]).exists():
            return error("Refresh token has been revoked. Please log in again.", status=401)

        payload.pop("exp", None)
        payload.pop("token_type", None)
        return success(data=_make_tokens(payload))


class LogoutView(APIView):
    """POST /api/v1/auth/logout/"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from apps.patients.models import BlacklistedToken

        auth_header = request.headers.get("Authorization", "")
        token = auth_header.split(" ", 1)[1] if auth_header.startswith("Bearer ") else None

        jtis_to_blacklist = []
        if token:
            try:
                payload = jwt.decode(token, settings.JWT_SIGNING_KEY, algorithms=["HS256"], options={"verify_exp": False})
                if payload.get("jti"):
                    jtis_to_blacklist.append((payload["jti"], payload.get("exp")))
            except jwt.InvalidTokenError:
                pass

        refresh_token = request.data.get("refresh")
        if refresh_token:
            try:
                payload = jwt.decode(refresh_token, settings.JWT_SIGNING_KEY, algorithms=["HS256"], options={"verify_exp": False})
                if payload.get("jti"):
                    jtis_to_blacklist.append((payload["jti"], payload.get("exp")))
            except jwt.InvalidTokenError:
                pass

        for jti, exp in jtis_to_blacklist:
            expires_at = timezone.datetime.fromtimestamp(exp, tz=timezone.utc) if exp else timezone.now() + timedelta(days=7)
            BlacklistedToken.objects.using("default").get_or_create(jti=jti, defaults={"expires_at": expires_at})

        return success(data={"logged_out": True})
