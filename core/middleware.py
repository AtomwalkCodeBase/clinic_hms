"""
core/middleware.py
------------------
JWTTenantMiddleware — runs on every request before the view.

What it does:
  1. Reads the Authorization: Bearer <token> header.
  2. Decodes and validates the JWT (using the same secret as SimpleJWT).
  3. Pulls db_name, tenant_id, role, license_tier, is_platform from claims.
  4. Calls set_tenant_db(db_name) to point the ORM router at the right DB.
  5. Attaches decoded claims directly to request so views and permissions
     can read them without touching the token again.

Public endpoints (login, refresh, health) skip JWT validation — they are
listed in EXEMPT_PREFIXES.

Security notes:
  - Token signature is verified with JWT_SECRET_KEY from settings.
  - Expired tokens return 401 immediately.
  - If db_name in the token does not exist as a configured DATABASES alias,
    the request is rejected with 401 to prevent data leakage.
"""

import logging
from django.conf import settings
from django.http  import JsonResponse
import jwt

from .db_router import set_tenant_db

logger = logging.getLogger(__name__)

# These URL prefixes bypass JWT validation
EXEMPT_PREFIXES = (
    "/api/v1/auth/login/",
    "/api/v1/auth/token/refresh/",
    "/api/v1/auth/setup-password/",  # invite token in body, not Bearer
    "/api/v1/portal/register/",      # patient self-signup
    "/health/",
    "/admin/",
)


class JWTTenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # ── Reset thread-local on every request ───────────────────────────
        set_tenant_db(None)

        # ── Skip exempt paths ─────────────────────────────────────────────
        if any(request.path.startswith(prefix) for prefix in EXEMPT_PREFIXES):
            return self.get_response(request)

        # ── Extract token ─────────────────────────────────────────────────
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return self._unauthorised("Authentication credentials were not provided.")

        token = auth_header.split(" ", 1)[1]

        # ── Decode and validate ───────────────────────────────────────────
        try:
            payload = jwt.decode(
                token,
                settings.JWT_SIGNING_KEY,
                algorithms=["HS256"],
            )
        except jwt.ExpiredSignatureError:
            return self._unauthorised("Token has expired.")
        except jwt.InvalidTokenError as exc:
            logger.warning("Invalid JWT received: %s", exc)
            return self._unauthorised("Invalid token.")

        # ── Validate tenant DB alias exists in settings ───────────────────
        db_name = payload.get("db_name")
        is_platform = payload.get("is_platform", False)
        is_patient  = payload.get("role") == "patient"

        if not is_platform and not is_patient:
            if not db_name:
                return self._unauthorised("Token missing tenant context.")
            # Auto-register tenant DB config if not yet in settings.DATABASES.
            # Tenant DBs are not persisted across restarts — they're registered
            # lazily on first use (login, or here on subsequent requests).
            if db_name not in settings.DATABASES:
                from apps.tenants.utils import _make_db_config
                from apps.tenants.models import Tenant
                if not Tenant.objects.filter(db_name=db_name, is_active=True).exists():
                    logger.error(
                        "JWT references unknown db_name=%s — no matching active tenant.",
                        db_name,
                    )
                    return self._unauthorised("Invalid tenant context.")
                settings.DATABASES[db_name] = _make_db_config(db_name)
                logger.info("Lazily registered tenant DB config: %s", db_name)
            set_tenant_db(db_name)

        # ── Attach claims to request ──────────────────────────────────────
        request.tenant_db      = db_name
        request.tenant_id      = payload.get("tenant_id")
        request.user_role      = payload.get("role")
        request.license_tier   = payload.get("license_tier", "starter")
        request.is_platform    = is_platform
        request.jwt_payload    = payload

        return self.get_response(request)

    @staticmethod
    def _unauthorised(message: str) -> JsonResponse:
        return JsonResponse(
            {"success": False, "message": message, "errors": {}},
            status=401,
        )
