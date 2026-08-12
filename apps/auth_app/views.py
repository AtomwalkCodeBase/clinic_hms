"""
apps/auth_app/views.py
-----------------------
Authentication endpoints for all user types.

Endpoints:
  POST /api/v1/auth/login/staff/      — hospital staff login (profile-based routing, no subdomain)
  POST /api/v1/auth/login/platform/   — Atomwalk platform admin login (no subdomain)
  POST /api/v1/auth/login/patient/    — patient portal login (email or AWPID)
  POST /api/v1/auth/token/refresh/    — refresh access token
  GET  /api/v1/auth/me/               — current user info
  GET  /api/v1/auth/me/permissions/   — feature flags for the frontend
  POST /api/v1/auth/setup-password/   — staff invite → set own password
"""

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

from core.response import success, error
from apps.tenants.models import Tenant, Subscription
from apps.tenants.constants import TIER_FEATURE_DEFAULTS
from apps.org.models import StaffUser
from apps.registry.models import PatientIdentity, StaffMobileIndex

logger = logging.getLogger(__name__)

from .serializers import (
    StaffLoginSerializer,
    PlatformLoginSerializer,
    PatientLoginSerializer,
    SetupPasswordSerializer,
    ChangePasswordSerializer,
)


def _make_tokens(payload: dict) -> dict:
    """
    Create access + refresh JWT pair from a claims payload.
    Every token gets a unique jti so it can be individually revoked via
    BlacklistedToken (see LogoutView below and core/authentication.py).
    """
    now         = timezone.now()
    access_exp  = now + timedelta(minutes=60)
    refresh_exp = now + timedelta(days=7)

    access_payload  = {**payload, "exp": access_exp,  "token_type": "access",  "jti": secrets.token_hex(16)}
    refresh_payload = {**payload, "exp": refresh_exp, "token_type": "refresh", "jti": secrets.token_hex(16)}

    return {
        "access":  jwt.encode(access_payload,  settings.JWT_SIGNING_KEY, algorithm="HS256"),
        "refresh": jwt.encode(refresh_payload, settings.JWT_SIGNING_KEY, algorithm="HS256"),
    }


def _make_invite_token(staff_id: int, tenant_db: str) -> str:
    """
    Generate a signed invite token for the setup-password flow.
    Valid for 48 hours. Not an access token — only accepted by SetupPasswordView.
    """
    payload = {
        "staff_id":  staff_id,
        "tenant_db": tenant_db,
        "token_type": "invite",
        "exp": timezone.now() + timedelta(hours=48),
        "jti": secrets.token_hex(8),  # prevent reuse
    }
    return jwt.encode(payload, settings.JWT_SIGNING_KEY, algorithm="HS256")


# ── Staff Login ───────────────────────────────────────────────────────────────

class StaffLoginView(APIView):
    """
    POST /api/v1/auth/login/staff/

    Two supported request shapes (see StaffLoginSerializer):
      1. {mobile, password} — profile-based routing, no subdomain needed.
         The "mobile" field also accepts an email address (detected by the
         presence of "@") — either way it's resolved via StaffMobileIndex
         (registry DB) → tenant db_name → StaffUser → verify password → JWT.
         This matches the design spec:
         Request → Authenticated User → Profile → Hospital → DB Name → Tenant DB
      2. {subdomain, employee_id, password} — for hospitals using employee
         IDs. Employee IDs aren't globally unique (two hospitals can both
         have "EMP-001"), so this path resolves the tenant DIRECTLY from
         the given subdomain instead of a registry-wide index lookup.
    """
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        serializer = StaffLoginSerializer(data=request.data)
        if not serializer.is_valid():
            return error("Validation error.", errors=serializer.errors)

        d = serializer.validated_data
        login_by_employee_id = bool(d.get("subdomain")) and bool(d.get("employee_id"))

        if login_by_employee_id:
            # ── Step 1 (employee-ID path): resolve tenant directly by subdomain ──
            try:
                tenant = Tenant.objects.get(subdomain__iexact=d["subdomain"], is_active=True)
            except Tenant.DoesNotExist:
                return error("Invalid credentials.")
            db_name, tenant_id = tenant.db_name, tenant.id
        else:
            # ── Step 1 (mobile/email path): look up which tenant DB this
            # identifier belongs to. The "mobile" field also accepts an
            # email address — detected by the presence of "@" — since staff
            # may not know which identifier a given colleague registered with.
            identifier = d["mobile"]
            try:
                if "@" in identifier:
                    index = StaffMobileIndex.objects.using("default").get(email__iexact=identifier)
                else:
                    index = StaffMobileIndex.objects.using("default").get(mobile=identifier)
            except StaffMobileIndex.DoesNotExist:
                return error("Invalid credentials.")
            db_name, tenant_id = index.db_name, index.tenant_id

            # ── Step 2: Verify tenant is active ───────────────────────────────
            try:
                tenant = Tenant.objects.get(pk=tenant_id, is_active=True)
            except Tenant.DoesNotExist:
                return error("This hospital account is inactive. Contact Atomwalk support.")

        # ── Step 3: Ensure tenant DB is registered ────────────────────────────
        if db_name not in settings.DATABASES:
            from apps.tenants.utils import _make_db_config
            settings.DATABASES[db_name] = _make_db_config(db_name)

        # ── Step 4: Fetch StaffUser from tenant DB ────────────────────────────
        try:
            if login_by_employee_id:
                staff = StaffUser.objects.using(db_name).get(employee_id=d["employee_id"], is_active=True)
            else:
                staff = StaffUser.objects.using(db_name).get(
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
            subscription = Subscription.objects.get(tenant=tenant)
        except Subscription.DoesNotExist:
            return error("Subscription not found.")

        payload = {
            "user_id":      staff.id,
            "email":        staff.email,
            "full_name":    staff.get_full_name(),
            "role":         staff.role,
            "db_name":      db_name,
            "tenant_id":    tenant_id,
            "hospital_name": tenant.name,
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
    """
    POST /api/v1/auth/login/platform/
    Authenticates against Django's built-in auth.User (the superuser created
    via DJANGO_SUPERUSER_* env vars + --noinput at startup).
    No subdomain required — platform admin has no tenant context.
    """
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
            "tenant_id":   None,
            "license_tier": "enterprise",
        }

        return success(data=_make_tokens(payload), message="Platform login successful.")


# ── Patient Login ─────────────────────────────────────────────────────────────

class PatientLoginView(APIView):
    """
    POST /api/v1/auth/login/patient/
    Body: {"mobile": ..., "password": ...}  (also accepts AWPID or email in the mobile field)
    """
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        from apps.registry.models import PatientAccount

        login_id = (request.data.get("mobile") or request.data.get("awpid") or "").strip()
        password = request.data.get("password") or ""
        if not login_id or not password:
            return error("Mobile number and password are required.")

        try:
            if login_id.upper().startswith("AWPID-"):
                acct = PatientAccount.objects.using("default").get(awpid=login_id, is_active=True)
            elif "@" in login_id:
                acct = PatientAccount.objects.using("default").get(email__iexact=login_id, is_active=True)
            else:
                acct = PatientAccount.objects.using("default").get(mobile=login_id, is_active=True)
        except PatientAccount.DoesNotExist:
            return error("Invalid credentials.")

        if not acct.check_password(password):
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
            "tenant_id":   None,
            "is_platform": False,
        }
        return success(data=_make_tokens(payload), message="Login successful.")


# ── Setup Password (invite flow) ──────────────────────────────────────────────

class SetupPasswordView(APIView):
    """
    POST /api/v1/auth/setup-password/
    Called by newly invited staff to activate their account.
    The invite_token was returned when hospital admin invited them.
    """
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
        tenant_db = payload["tenant_db"]

        # Validate DB exists
        if tenant_db not in settings.DATABASES:
            return error("Invalid invite token — tenant not found.")

        try:
            staff = StaffUser.objects.using(tenant_db).get(pk=staff_id, is_active=True)
        except StaffUser.DoesNotExist:
            return error("Staff account not found or deactivated.")

        staff.set_password(d["new_password"])
        staff.save(using=tenant_db, update_fields=["password"])

        return success(message="Password set successfully. You can now log in.")


# ── Change Password ───────────────────────────────────────────────────────────

class ChangePasswordView(APIView):
    """
    POST /api/v1/auth/change-password/
    For staff who logged in with a temp password (must_change_password=True).
    Also works as a regular password change.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return error("Validation error.", errors=serializer.errors)

        d = serializer.validated_data

        if request.is_platform:
            return error("Platform admins change passwords via Django admin.")

        db_name = request.tenant_db
        try:
            staff = StaffUser.objects.using(db_name).get(
                pk=request.user.id, is_active=True
            )
        except StaffUser.DoesNotExist:
            return error("Staff account not found.")

        # Forced first-login change (must_change_password=True) skips this —
        # they already proved they know the current password by using it to
        # log in moments ago. A voluntary change from Settings must prove it
        # again, so a hijacked/left-open session can't lock the real owner out.
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

class StaffForgotPasswordView(APIView):
    """
    POST /api/v1/auth/forgot-password/staff/
    Body: {mobile, date_of_birth (YYYY-MM-DD), new_password, confirm_password}

    There's no email/SMS gateway wired into this stack, so this can't do an
    OTP or reset-link flow — it verifies identity the only other way real
    data on file allows: mobile number (the login identifier) plus date of
    birth (something the account holder set on their own profile, not
    guessable from the login screen). If a staff member's DOB was never
    set, this can't verify them and they're told to contact their admin —
    who can always reset a password directly (see TenantStaffResetPasswordView
    / StaffResetPasswordView), no guessing required.
    """
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        mobile = (request.data.get("mobile") or "").strip()
        dob    = (request.data.get("date_of_birth") or "").strip()
        new_password     = request.data.get("new_password") or ""
        confirm_password = request.data.get("confirm_password") or ""

        if not mobile or not dob:
            return error("Mobile number and date of birth are required.")
        if new_password != confirm_password:
            return error("Passwords do not match.", errors={"confirm_password": "Passwords do not match."})
        if len(new_password) < 8:
            return error("New password must be at least 8 characters.", errors={"new_password": "Too short."})

        try:
            index = StaffMobileIndex.objects.using("default").get(mobile=mobile)
        except StaffMobileIndex.DoesNotExist:
            return error("We couldn't verify those details.")

        db_name = index.db_name
        if db_name not in settings.DATABASES:
            from apps.tenants.utils import _make_db_config
            settings.DATABASES[db_name] = _make_db_config(db_name)

        try:
            staff = StaffUser.objects.using(db_name).get(phone=mobile, is_active=True)
        except StaffUser.DoesNotExist:
            return error("We couldn't verify those details.")

        if not staff.date_of_birth:
            return error(
                "We can't verify your identity without a date of birth on file. "
                "Ask your hospital admin to reset your password instead."
            )
        if str(staff.date_of_birth) != dob:
            return error("We couldn't verify those details.")

        staff.set_password(new_password)
        staff.must_change_password = False
        staff.save(using=db_name, update_fields=["password", "must_change_password"])

        return success(message="Password reset successfully. You can now log in.")


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
            "tenant_id":  p.get("tenant_id"),
            "db_name":    p.get("db_name"),
            "hospital_name": p.get("hospital_name", ""),
            "is_platform": p.get("is_platform", False),
        }

        # The JWT itself never carries the profile photo (a multi-KB base64
        # data URI) — it's fetched fresh here from whichever table actually
        # owns it, per account type, so the sidebar/topbar avatar can stay
        # up to date without needing a fresh login every time it changes.
        data["photo"] = ""
        try:
            if p.get("role") == "patient":
                from apps.registry.models import PatientAccount
                acct = PatientAccount.objects.using("default").get(pk=p.get("user_id"))
                data["photo"] = acct.photo or ""
            elif not p.get("is_platform") and p.get("db_name"):
                staff = StaffUser.objects.using(p["db_name"]).get(pk=p.get("user_id"))
                data["photo"] = staff.photo or ""
        except Exception:
            # Best-effort: platform admins (no row to look up) and missing/
            # inactive accounts are expected and shouldn't break /me/, but a
            # genuine DB error here would look identical from the outside —
            # log it so it's not completely invisible if something's actually
            # broken (e.g. a schema change on photo).
            logger.debug("MeView: could not resolve photo for user_id=%s role=%s", p.get("user_id"), p.get("role"), exc_info=True)

        return success(data=data)


class PermissionsView(APIView):
    """GET /api/v1/auth/me/permissions/ — subscription feature flags."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.is_platform:
            # Platform admin gets everything — pulled from the enterprise tier's
            # own feature dict (single source of truth in constants.py) rather
            # than a hand-copied literal that could silently drift out of sync
            # with it, same class of bug the TIER_FEATURE_DEFAULTS refactor was
            # meant to prevent everywhere else.
            return success(data={
                **TIER_FEATURE_DEFAULTS["enterprise"],
                "license_tier": "enterprise", "subscription_status": "active",
                "max_doctors": 0, "max_branches": 0, "max_staff": 0,
                "usage": {"doctors": None, "branches": None, "staff": None},
            })

        try:
            tenant = Tenant.objects.get(pk=request.tenant_id)
            sub    = Subscription.objects.get(tenant=tenant)
        except (Tenant.DoesNotExist, Subscription.DoesNotExist):
            return error("Subscription not found.")

        # Live usage against the tier's limits — lets the frontend disable
        # "+ Add Branch" / "+ Invite Staff" and show "X of Y used" before the
        # admin fills out a whole form only to hit a 403 at the end. Kept
        # best-effort here (unlike the write-time check in apps.tenants.limits,
        # which fails closed) since this is read-only display data, not a
        # gate — worst case the buttons just don't show a live count.
        from apps.tenants.limits import get_usage_counts
        try:
            usage = get_usage_counts(request.tenant_db)
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

        from apps.registry.models import BlacklistedToken
        if payload.get("jti") and BlacklistedToken.objects.using("default").filter(jti=payload["jti"]).exists():
            return error("Refresh token has been revoked. Please log in again.", status=401)

        payload.pop("exp", None)
        payload.pop("token_type", None)
        return success(data=_make_tokens(payload))


class LogoutView(APIView):
    """
    POST /api/v1/auth/logout/
    Body (optional): {"refresh": "<refresh token>"}

    Blacklists the current access token's jti immediately, and the refresh
    token's jti if supplied, so a stolen/left-open session can be killed
    server-side instead of just waiting out the token's natural expiry.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from apps.registry.models import BlacklistedToken

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
