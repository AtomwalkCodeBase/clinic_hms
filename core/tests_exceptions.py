"""
core/tests_exceptions.py
------------------------
DRF-raised errors must reach clients in the {success, message, errors} envelope
(core.exceptions.custom_exception_handler, registered in REST_FRAMEWORK).
"""

import time

import jwt
from django.conf import settings
from django.test import SimpleTestCase
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated, PermissionDenied, Throttled

from core.exceptions import custom_exception_handler


class HandlerRegistrationTests(SimpleTestCase):
    def test_handler_is_registered(self):
        self.assertEqual(settings.REST_FRAMEWORK["EXCEPTION_HANDLER"], "core.exceptions.custom_exception_handler")

    def test_permission_denied_uses_the_envelope(self):
        """The subscription/deactivation messages raised in core.authentication rely on this."""
        resp = custom_exception_handler(PermissionDenied("This hospital's account is frozen."), {})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data, {"success": False, "message": "This hospital's account is frozen.", "errors": {}})

    def test_authentication_failed_and_not_authenticated(self):
        for exc, code in ((AuthenticationFailed("Token has been revoked."), 401), (NotAuthenticated(), 401)):
            resp = custom_exception_handler(exc, {})
            self.assertEqual(resp.status_code, code)
            self.assertFalse(resp.data["success"])
            self.assertTrue(resp.data["message"])
            self.assertEqual(resp.data["errors"], {})

    def test_throttled_keeps_its_message(self):
        resp = custom_exception_handler(Throttled(wait=7), {})
        self.assertEqual(resp.status_code, 429)
        self.assertIn("throttled", resp.data["message"].lower())

    def test_serializer_errors_are_moved_under_errors(self):
        class S(serializers.Serializer):
            name = serializers.CharField()

        s = S(data={})
        with self.assertRaises(serializers.ValidationError) as ctx:
            s.is_valid(raise_exception=True)
        resp = custom_exception_handler(ctx.exception, {})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.data["success"])
        self.assertIn("name", resp.data["errors"])

    def test_unhandled_exceptions_are_left_to_django(self):
        with self.assertLogs("core.exceptions", level="ERROR"):
            self.assertIsNone(custom_exception_handler(RuntimeError("boom"), {}))


class EndToEndEnvelopeTests(SimpleTestCase):
    def test_wrong_role_gets_the_envelope_not_bare_detail(self):
        """Through the real middleware + auth + permission stack (no DB is touched for a platform token)."""
        token = jwt.encode(
            {"user_id": 1, "role": "platform_admin", "is_platform": True, "token_type": "access",
             "exp": int(time.time()) + 300},
            settings.JWT_SIGNING_KEY, algorithm="HS256",
        )
        resp = self.client.get("/api/v1/org/branches/", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(resp.status_code, 403)
        body = resp.json()
        self.assertEqual(set(body), {"success", "message", "errors"})
        self.assertFalse(body["success"])
        self.assertEqual(body["message"], "Access restricted to hospital staff.")
