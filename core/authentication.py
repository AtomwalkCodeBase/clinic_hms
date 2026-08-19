"""
core/authentication.py
-----------------------
Custom DRF authentication backend for Atomwalk HMS.

Replaces rest_framework_simplejwt.authentication.JWTAuthentication.

Reads our custom PyJWT tokens and populates request.user with a lightweight
MockUser that satisfies DRF's IsAuthenticated check and the role-based
permission classes in core/permissions.py.
"""

import jwt
from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


class MockUser:
    """
    Lightweight user-like object built from a decoded JWT payload.
    Allows DRF's IsAuthenticated and role-permission classes to work
    without any database round-trips.

    `subscription` is populated (one extra DB query, registry DB only) for
    hospital-staff requests — see JWTTenantAuthentication.authenticate().
    It's looked up fresh on every request rather than cached in the JWT so a
    tier change or suspension takes effect immediately, not on next login.
    """
    is_anonymous     = False
    is_active        = True
    is_authenticated = True

    def __init__(self, payload: dict):
        self.id          = payload.get("user_id")
        self.pk          = self.id  # DRF's throttle classes read .pk, not .id
        self.email       = payload.get("email", "")
        self.role        = payload.get("role", "")
        # Which system-role identities this user should be treated as for
        # every Is*/doctor-listing check — [] for the 6 system roles (they
        # don't need it, .role already says everything) and non-empty only
        # for role="custom" staff, e.g. ["doctor", "nurse", "front_desk"].
        # Set once at login time (see apps.org.rbac.resolve_acts_as +
        # StaffLoginView) and baked into the JWT rather than looked up per
        # request — same tradeoff as .role itself: a custom role's acts_as
        # changing takes effect on next login, not instantly, which matches
        # how a role change for anyone else already works today.
        self.acts_as     = payload.get("acts_as", [])
        self.is_platform = payload.get("is_platform", False)
        self.tenant_id   = payload.get("tenant_id")
        self.db_name     = payload.get("db_name", "default")
        self.branch_id   = payload.get("branch_id")
        self.subscription = None

    def __str__(self):
        return self.email


class JWTTenantAuthentication(BaseAuthentication):
    """
    DRF authentication class for Atomwalk's custom JWT format.

    If no Bearer token is present, returns None (unauthenticated) so that
    AllowAny views can still proceed.

    If a token is present but invalid/expired, raises AuthenticationFailed (401).
    """

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
        # token instead of relying purely on natural expiry.
        jti = payload.get("jti")
        if jti:
            from apps.registry.models import BlacklistedToken
            if BlacklistedToken.objects.using("default").filter(jti=jti).exists():
                raise AuthenticationFailed("Token has been revoked. Please log in again.")

        user = MockUser(payload)

        # ── Subscription lifecycle enforcement ──────────────────────────────
        # Only hospital staff carry a tenant_id (platform admins and patients
        # don't — see auth_app/views.py's three login payloads), so this only
        # ever runs for staff requests. Checked fresh every request, not
        # cached in the JWT, so a platform-admin suspension or a tier change
        # takes effect on the staff member's very next request.
        if user.tenant_id:
            from apps.tenants.models import Subscription
            sub = Subscription.objects.using("default").filter(tenant_id=user.tenant_id).first()
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
            # StaffLoginView already blocks a deactivated staff member from
            # getting a *new* token, but a token issued before deactivation
            # stays valid for up to 60 minutes (access) or 7 days (refresh)
            # otherwise — a "Deactivate" click on the platform-admin or
            # hospital-admin side wouldn't actually cut off a session already
            # in progress. Checked fresh every request (one extra indexed
            # lookup on the tenant DB, same cost as the subscription check
            # above) so deactivation takes effect on the very next call.
            from apps.org.models import StaffUser
            still_active = StaffUser.objects.using(user.db_name).filter(
                pk=user.id
            ).values_list("is_active", flat=True).first()
            if not still_active:
                raise PermissionDenied(
                    "Your account has been deactivated. Contact your hospital admin."
                )

        return (user, token)

    def authenticate_header(self, request):
        return "Bearer"
