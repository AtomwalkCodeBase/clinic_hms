"""core/tests_logging_context.py — request id / tenant / user on log records."""

import logging
import time

import jwt
from django.conf import settings
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from core.logging_context import RequestContextFilter, RequestIdMiddleware, get_request_id, reset_request_identity, set_request_identity


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []
        self.addFilter(RequestContextFilter())

    def emit(self, record):
        self.records.append(record)


class RequestIdMiddlewareTests(SimpleTestCase):
    def run_request(self, **headers):
        seen = {}

        def view(request):
            seen["id"] = get_request_id()
            return HttpResponse("ok")

        response = RequestIdMiddleware(view)(RequestFactory().get("/x/", **headers))
        return response, seen["id"]

    def test_generates_an_id_and_returns_it_in_the_response(self):
        response, inside = self.run_request()
        self.assertRegex(response["X-Request-ID"], r"^[0-9a-f]{32}$")
        self.assertEqual(response["X-Request-ID"], inside)

    def test_accepts_a_well_formed_caller_supplied_id(self):
        response, inside = self.run_request(HTTP_X_REQUEST_ID="trace-abc-12345")
        self.assertEqual((response["X-Request-ID"], inside), ("trace-abc-12345", "trace-abc-12345"))

    def test_rejects_a_malformed_id_rather_than_logging_it(self):
        response, _ = self.run_request(HTTP_X_REQUEST_ID="bad id\nwith newline")
        self.assertRegex(response["X-Request-ID"], r"^[0-9a-f]{32}$")

    def test_the_context_is_cleared_after_the_request(self):
        self.run_request(HTTP_X_REQUEST_ID="trace-abc-12345")
        self.assertEqual(get_request_id(), "-")


class FilterTests(SimpleTestCase):
    def setUp(self):
        reset_request_identity()

    def test_records_carry_request_tenant_and_user(self):
        handler, log = Capture(), logging.getLogger("core.tests_logging_context.sample")
        log.addHandler(handler)
        self.addCleanup(log.removeHandler, handler)
        log.setLevel(logging.INFO)

        def view(request):
            set_request_identity(tenant_id=7, user_id=42)
            log.info("inside")
            return HttpResponse("ok")

        RequestIdMiddleware(view)(RequestFactory().get("/x/", HTTP_X_REQUEST_ID="trace-abc-12345"))
        log.info("outside")
        inside, outside = handler.records
        self.assertEqual((inside.request_id, inside.tenant_id, inside.user_id), ("trace-abc-12345", "7", "42"))
        self.assertEqual((outside.request_id, outside.tenant_id, outside.user_id), ("-", "-", "-"))


class JwtMiddlewareIdentityTests(SimpleTestCase):
    def test_a_platform_token_sets_the_user_on_the_log_context(self):
        from core.middleware import JWTTenantMiddleware

        handler, log = Capture(), logging.getLogger("core.tests_logging_context.jwt")
        log.addHandler(handler)
        self.addCleanup(log.removeHandler, handler)
        log.setLevel(logging.INFO)

        def view(request):
            log.info("handled")
            return HttpResponse("ok")

        token = jwt.encode({"user_id": 5, "is_platform": True, "role": "platform_admin", "token_type": "access",
                            "exp": int(time.time()) + 60}, settings.JWT_SIGNING_KEY, algorithm="HS256")
        chain = RequestIdMiddleware(JWTTenantMiddleware(view))
        chain(RequestFactory().get("/api/v1/platform/stats/", HTTP_AUTHORIZATION=f"Bearer {token}"))
        self.assertEqual(handler.records[0].user_id, "5")
