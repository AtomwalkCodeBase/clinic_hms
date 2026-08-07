"""
apps/auth_app/tests.py
------------------------
DB-independent tests for token issuance/shape. Full login-flow tests (staff/
platform/patient) need a live registry DB + a provisioned tenant DB, so
they're intentionally not attempted here — see the module docstring in
core/tests.py for the DB-independent vs DB-backed test split.
"""

import jwt
from django.conf import settings
from django.test import TestCase

from .views import _make_tokens, StaffLoginView, PlatformLoginView, PatientLoginView, LogoutView


class TokenIssuanceTests(TestCase):
    def test_access_and_refresh_tokens_have_distinct_jti(self):
        """
        Each token must get its own jti so logout can revoke exactly one
        token (e.g. just the access token) without invalidating the other.
        """
        tokens = _make_tokens({"user_id": 1, "role": "doctor"})
        access_payload = jwt.decode(tokens["access"], settings.JWT_SIGNING_KEY, algorithms=["HS256"])
        refresh_payload = jwt.decode(tokens["refresh"], settings.JWT_SIGNING_KEY, algorithms=["HS256"])

        self.assertIn("jti", access_payload)
        self.assertIn("jti", refresh_payload)
        self.assertNotEqual(access_payload["jti"], refresh_payload["jti"])
        self.assertEqual(access_payload["token_type"], "access")
        self.assertEqual(refresh_payload["token_type"], "refresh")

    def test_two_calls_never_reuse_a_jti(self):
        first = _make_tokens({"user_id": 1})
        second = _make_tokens({"user_id": 1})
        first_jti = jwt.decode(first["access"], settings.JWT_SIGNING_KEY, algorithms=["HS256"])["jti"]
        second_jti = jwt.decode(second["access"], settings.JWT_SIGNING_KEY, algorithms=["HS256"])["jti"]
        self.assertNotEqual(first_jti, second_jti)


class LoginThrottleScopeTests(TestCase):
    """
    Verifies the login endpoints are actually wired to the "login" throttle
    scope (settings.py alone doesn't guarantee a view uses it — this closes
    that gap so a future refactor can't silently drop the rate limit).
    """

    def test_staff_login_has_login_scope(self):
        self.assertEqual(StaffLoginView.throttle_scope, "login")

    def test_platform_login_has_login_scope(self):
        self.assertEqual(PlatformLoginView.throttle_scope, "login")

    def test_patient_login_has_login_scope(self):
        self.assertEqual(PatientLoginView.throttle_scope, "login")

    def test_logout_requires_authentication(self):
        from rest_framework.permissions import IsAuthenticated
        self.assertIn(IsAuthenticated, LogoutView.permission_classes)
