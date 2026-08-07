"""
core/tests.py
--------------
DB-independent unit tests — safe to run anywhere, including CI, without a
live Postgres instance. DB-backed integration tests live in each app's
tests.py and require a real database (see apps/opd/tests.py docstring).
"""

from django.test import TestCase, override_settings
from django.urls import reverse


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


@override_settings(FIELD_ENCRYPTION_KEY="Zm9vYmFyYmF6cXV4Zm9vYmFyYmF6cXV4Zm9vYmFyYmF6cXU9")
class EncryptedFieldTests(TestCase):
    """
    core.encrypted_fields round-trip test. Uses a throwaway key via
    override_settings — never the real FIELD_ENCRYPTION_KEY.
    """

    def test_round_trip_is_reversible(self):
        from cryptography.fernet import Fernet
        # Use a real generated key for this test regardless of the placeholder above.
        key = Fernet.generate_key().decode()
        with self.settings(FIELD_ENCRYPTION_KEY=key):
            from core.encrypted_fields import EncryptedTextField
            field = EncryptedTextField()
            plaintext = "Patient reports mild fever and cough for 3 days."
            ciphertext = field.get_prep_value(plaintext)
            self.assertNotEqual(ciphertext, plaintext)  # actually encrypted, not passthrough
            recovered = field.from_db_value(ciphertext, None, None)
            self.assertEqual(recovered, plaintext)

    def test_empty_value_is_not_encrypted(self):
        from core.encrypted_fields import EncryptedTextField
        field = EncryptedTextField()
        self.assertEqual(field.get_prep_value(""), "")
        self.assertIsNone(field.get_prep_value(None))


class AuditLogHelperTests(TestCase):
    def test_log_action_never_raises_on_bad_db(self):
        """
        Auditing must never break the request it's auditing. Pointing at a
        nonexistent DB alias should be swallowed, not propagate.
        """
        from core.audit import log_action
        try:
            log_action(None, "this-db-alias-does-not-exist", action="test.noop")
        except Exception as exc:  # noqa: BLE001 — this is exactly what we're asserting against
            self.fail(f"log_action raised instead of swallowing the error: {exc}")
