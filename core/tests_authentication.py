"""core/tests_authentication.py — MockUser built from a JWT payload."""

from django.test import SimpleTestCase

from core.authentication import MockUser


class MockUserTests(SimpleTestCase):
    def test_carries_the_display_name_from_the_token(self):
        """Views record getattr(request.user, "full_name", None) or email as 'who did this'."""
        self.assertEqual(MockUser({"user_id": 1, "full_name": "Dr Asha Rao", "email": "a@x.test"}).full_name, "Dr Asha Rao")

    def test_defaults_to_empty_so_callers_fall_back_to_email(self):
        u = MockUser({"user_id": 1, "email": "a@x.test"})
        self.assertEqual(getattr(u, "full_name", None) or u.email, "a@x.test")
