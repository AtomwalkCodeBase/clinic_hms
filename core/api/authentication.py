"""core/api/authentication.py"""

import jwt
from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


class MockUser:
    """Lightweight user-like object built from a decoded JWT payload."""
    is_anonymous     = False
    is_active        = True
    is_authenticated = True

    def __init__(self, payload: dict):
        self.pk          = payload.get("user_id")
        self.email       = payload.get("email", "")
        # Login tokens carry the display name; several views record it as "who did this"
        self.full_name   = payload.get("full_name", "")
        self.role        = payload.get("role", "")
        # Which system-role identities this user should be treated as for
        self.acts_as     = payload.get("acts_as", [])
        self.is_platform = payload.get("is_platform", False)
        self.hospital_id   = payload.get("hospital_id")
        self.db_name     = payload.get("db_name", "default")
        self.branch_id   = payload.get("branch_id")
        self.subscription = None
        # Baked in at login time (see PatientLoginView / PatientOTPLoginView).
        self.awpid       = payload.get("awpid")

    def __str__(self):
        return self.email


class JWTHospitalAuthentication(BaseAuthentication):
    """DRF authentication class for Atomwalk's custom JWT format."""

    def authenticate(self, request):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return None  # Unauthenticated — AllowAny views still work

        token = auth_header.split(" ", 1)[1]

        try:
            payload = jwt.decode(
                token,
                settings.JWT_SIGNING_KEY,
                algorithms=["HS256"],
            )
        except jwt.ExpiredSignatureError:
            raise AuthenticationFailed("Token has expired.")
        except jwt.InvalidTokenError:
            raise AuthenticationFailed("Invalid token.")

        # Reject refresh tokens used as access tokens
        token_type = payload.get("token_type")
        if token_type and token_type not in ("access",):
            raise AuthenticationFailed("Invalid token type — use an access token.")

        # Revocation check — makes logout actually invalidate a still-unexpired
        jti = payload.get("jti")
        if jti:
            from core.auth.otp import is_revoked
            if is_revoked(jti):
                raise AuthenticationFailed("Token has been revoked. Please log in again.")

        user = MockUser(payload)

        # ── Subscription lifecycle enforcement ──────────────────────────────
        if user.hospital_id:
            from apps.hospital_master.models import Subscription
            sub = Subscription.objects.using("default").filter(hospital_id=user.hospital_id).first()
            user.subscription = sub
            if sub:
                if sub.status in ("frozen", "suspended"):
                    raise PermissionDenied(
                        f"This hospital's account is {sub.get_status_display().lower()}. "
                        "Contact Atomwalk support to restore access."
                    )
                if sub.status == "read_only" and request.method not in SAFE_METHODS:
                    raise PermissionDenied(
                        "This hospital's subscription is read-only due to a billing issue — "
                        "you can view existing records but not add or change anything. "
                        "Contact your hospital admin to restore full access."
                    )

            # ── Live is_active check ──────────────────────────────────────
            from apps.hospital_setup.models import StaffUser
            still_active = StaffUser.objects.using(user.db_name).filter(
                pk=user.pk
            ).values_list("is_active", flat=True).first()
            if not still_active:
                raise PermissionDenied(
                    "Your account has been deactivated. Contact your hospital admin."
                )

        # ── Stale-token / reused-ID guard (patients) ────────────────────────
        if user.role == "patient":
            from apps.patients.services import accounts
            current_awpid = accounts().filter(
                pk=user.pk, is_active=True
            ).values_list("awpid", flat=True).first()
            if not current_awpid or current_awpid != user.awpid:
                raise AuthenticationFailed(
                    "Your session is no longer valid. Please log in again."
                )

        return (user, token)

    def authenticate_header(self, request):
        return "Bearer"
