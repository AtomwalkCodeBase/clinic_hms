"""
core/logging_context.py
-----------------------
Request-scoped context for log records, so one API call can be followed across the
middleware, views, signals and services that log while handling it.

  RequestIdMiddleware   assigns/accepts an X-Request-ID and echoes it in the response
  set_request_identity  called by JWTTenantMiddleware once the token is decoded
  RequestContextFilter  copies the values onto every LogRecord (request_id, tenant_id, user_id)

Uses contextvars, so it is safe under threads and async and is reset for every request.
"""

import logging
import re
import uuid
from contextvars import ContextVar

_request_id = ContextVar("request_id", default="-")
_tenant_id = ContextVar("tenant_id", default="-")
_user_id = ContextVar("user_id", default="-")

# Accept a caller-supplied id only if it looks like an id — it is written to logs and a header.
_SAFE_ID = re.compile(r"^[A-Za-z0-9._\-]{8,64}$")


def get_request_id() -> str:
    return _request_id.get()


def set_request_identity(*, tenant_id=None, user_id=None) -> None:
    if tenant_id is not None:
        _tenant_id.set(str(tenant_id))
    if user_id is not None:
        _user_id.set(str(user_id))


def reset_request_identity() -> None:
    """Back to "no request" — for code (and tests) that runs outside RequestIdMiddleware."""
    _tenant_id.set("-")
    _user_id.set("-")


class RequestContextFilter(logging.Filter):
    def filter(self, record):
        record.request_id = _request_id.get()
        record.tenant_id = _tenant_id.get()
        record.user_id = _user_id.get()
        return True


class RequestIdMiddleware:
    header = "X-Request-ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        supplied = request.headers.get(self.header, "")
        rid = supplied if _SAFE_ID.match(supplied) else uuid.uuid4().hex
        tokens = (_request_id.set(rid), _tenant_id.set("-"), _user_id.set("-"))
        try:
            response = self.get_response(request)
        finally:
            for var, token in zip((_request_id, _tenant_id, _user_id), tokens):
                var.reset(token)
        response[self.header] = rid
        return response
