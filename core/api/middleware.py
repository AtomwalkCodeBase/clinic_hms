"""core/api/middleware.py"""

import logging
import re
import uuid
from contextvars import ContextVar

from django.conf import settings
from django.http  import JsonResponse
import jwt

from core.db_router import set_hospital_db

logger = logging.getLogger(__name__)

# These URL prefixes bypass JWT validation
EXEMPT_PREFIXES = (
    "/api/v1/auth/login/",
    "/api/v1/auth/token/refresh/",
    "/api/v1/auth/setup-password/",  # invite token in body, not Bearer
    "/api/v1/auth/otp/",
    "/api/v1/auth/forgot-password/", # staff+patient OTP reset (action_token in body, not Bearer)
    "/api/v1/portal/register/",
    "/api/v1/emergency/",
                                      # doctor's phone with no Atomwalk login at all; auth is the signed token
    "/api/v1/consult-pad/",
                                      # same story as /emergency/ above: scanned on a phone with no session;
    "/api/v1/records-share/",
                                      # create/status/records/download endpoints gated by the 32-char
    "/api/v1/view-report/",
                                      # (apps/hospital_patients/document_view_views.py) — no Atomwalk login at all;
    "/health/",
    "/django-admin/",
)

# drf-spectacular's schema and Swagger views are AllowAny once past this middleware, so
DEBUG_ONLY_EXEMPT_PREFIXES = (
    "/api/docs/",
    "/api/schema/",
)


class JWTHospitalMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # ── Reset thread-local on every request ───────────────────────────
        set_hospital_db(None)

        # ── Skip exempt paths ─────────────────────────────────────────────
        exempt = EXEMPT_PREFIXES + DEBUG_ONLY_EXEMPT_PREFIXES if settings.DEBUG else EXEMPT_PREFIXES
        if any(request.path.startswith(prefix) for prefix in exempt):
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

        # ── Validate hospital DB alias exists in settings ───────────────────
        db_name = payload.get("db_name")
        is_platform = payload.get("is_platform", False)
        is_patient  = payload.get("role") == "patient"

        if not is_platform and not is_patient:
            if not db_name:
                return self._unauthorised("Token missing hospital context.")
            # Auto-register hospital DB config if not yet in settings.DATABASES.
            if db_name not in settings.DATABASES:
                from apps.hospital_master.services import ensure_hospital_db
                from apps.hospital_master.models import Hospital
                if not Hospital.objects.filter(db_name=db_name, is_active=True).exists():
                    logger.error(
                        "JWT references unknown db_name=%s — no matching active hospital.",
                        db_name,
                    )
                    return self._unauthorised("Invalid hospital context.")
                ensure_hospital_db(db_name)
                logger.info("Lazily registered hospital DB config: %s", db_name)
            set_hospital_db(db_name)

        # ── Attach claims to request ──────────────────────────────────────
        set_request_identity(hospital_id=payload.get("hospital_id"), user_id=payload.get("user_id"))
        request.hospital_db      = db_name
        request.hospital_id      = payload.get("hospital_id")
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


# ── Request id / hospital / user on every log line ───────────────────────────

_request_id = ContextVar("request_id", default="-")
_hospital_id = ContextVar("hospital_id", default="-")
_user_id = ContextVar("user_id", default="-")

# Accept a caller-supplied id only if it looks like an id — it is written to logs and a header.
_SAFE_ID = re.compile(r"^[A-Za-z0-9._\-]{8,64}$")


def get_request_id() -> str:
    return _request_id.get()


def set_request_identity(*, hospital_id=None, user_id=None) -> None:
    if hospital_id is not None:
        _hospital_id.set(str(hospital_id))
    if user_id is not None:
        _user_id.set(str(user_id))


def reset_request_identity() -> None:
    """Back to "no request" — for code (and tests) that runs outside RequestIdMiddleware."""
    _hospital_id.set("-")
    _user_id.set("-")


class RequestContextFilter(logging.Filter):
    def filter(self, record):
        record.request_id = _request_id.get()
        record.hospital_id = _hospital_id.get()
        record.user_id = _user_id.get()
        return True


class RequestIdMiddleware:
    header = "X-Request-ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        supplied = request.headers.get(self.header, "")
        rid = supplied if _SAFE_ID.match(supplied) else uuid.uuid4().hex
        tokens = (_request_id.set(rid), _hospital_id.set("-"), _user_id.set("-"))
        try:
            response = self.get_response(request)
        finally:
            for var, token in zip((_request_id, _hospital_id, _user_id), tokens):
                var.reset(token)
        response[self.header] = rid
        return response
