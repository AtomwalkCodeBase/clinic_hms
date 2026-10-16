"""
core/tests/tests.py
--------------
DB-independent unit tests — safe to run anywhere, including CI, without a
live Postgres instance. DB-backed integration tests live in each app's
tests.py and require a real database (see apps/opd/tests.py docstring).
"""

from django.test import TestCase


class HealthCheckTests(TestCase):
    def test_health_endpoint_returns_200_or_503_json(self):
        """
        The /health/ endpoint must always return JSON with a boolean db
        status, never a 500 — that's the whole point of a health check.
        """
        response = self.client.get("/health/")
        self.assertIn(response.status_code, (200, 503))
        data = response.json()
        self.assertIn("status", data)
        self.assertIn("database", data)
        self.assertEqual(data["service"], "atomwalk-hms")


class AuditLogHelperTests(TestCase):
    def test_log_action_never_raises_on_bad_db(self):
        """
        Auditing must never break the request it's auditing. Pointing at a
        nonexistent DB alias should be swallowed, not propagate.
        """
        from core.utils.audit import log_action
        try:
            log_action(None, "this-db-alias-does-not-exist", action="test.noop")
        except Exception as exc:  # noqa: BLE001 — this is exactly what we're asserting against
            self.fail(f"log_action raised instead of swallowing the error: {exc}")
