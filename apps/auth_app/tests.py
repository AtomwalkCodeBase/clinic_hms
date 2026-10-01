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


class TokenLifetimeTests(TestCase):
    """The JWT_*_LIFETIME settings (env-configurable) are what _make_tokens actually uses."""

    def lifetimes(self):
        tokens = _make_tokens({"user_id": 1})
        decode = lambda t: jwt.decode(t, settings.JWT_SIGNING_KEY, algorithms=["HS256"])
        a, r = decode(tokens["access"]), decode(tokens["refresh"])
        return a["exp"] - a["iat"] if "iat" in a else None, a["exp"], r["exp"]

    def test_tokens_last_as_long_as_the_configured_lifetimes(self):
        import time
        _, a_exp, r_exp = self.lifetimes()
        now = time.time()
        self.assertAlmostEqual(a_exp - now, settings.JWT_ACCESS_TOKEN_LIFETIME.total_seconds(), delta=30)
        self.assertAlmostEqual(r_exp - now, settings.JWT_REFRESH_TOKEN_LIFETIME.total_seconds(), delta=30)

    def test_overriding_the_settings_changes_the_token_lifetimes(self):
        import time
        from datetime import timedelta
        from django.test import override_settings
        with override_settings(JWT_ACCESS_TOKEN_LIFETIME=timedelta(minutes=5), JWT_REFRESH_TOKEN_LIFETIME=timedelta(days=1)):
            _, a_exp, r_exp = self.lifetimes()
        now = time.time()
        self.assertAlmostEqual(a_exp - now, 5 * 60, delta=30)
        self.assertAlmostEqual(r_exp - now, 24 * 3600, delta=30)
