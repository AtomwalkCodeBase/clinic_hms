"""core/auth/tests_otp.py — one-time codes and signed-out tokens kept in Redis."""
import time

from django.test import SimpleTestCase

from core.auth import otp
from core.auth.otp import OTPError, Purpose


class RedisCase(SimpleTestCase):
    def setUp(self):
        r = otp._redis()
        for pattern in ("otp:*", "otp-wait:*"):
            for key in r.scan_iter(pattern):
                r.delete(key)


class OneTimeCodeTests(RedisCase):
    def test_the_right_code_is_accepted_once_and_says_who_it_was_for(self):
        code, channel = otp.create_otp(Purpose.LOGIN_PATIENT, "a@example.com", "patient", 7, "cp_hospital_x")
        self.assertEqual(channel, "email")
        who = otp.verify_otp(Purpose.LOGIN_PATIENT, "a@example.com", code)
        self.assertEqual((who.target_type, who.target_id, who.target_db), ("patient", 7, "cp_hospital_x"))
        with self.assertRaisesMessage(OTPError, "No active code"):
            otp.verify_otp(Purpose.LOGIN_PATIENT, "a@example.com", code)

    def test_a_blank_target_id_comes_back_as_none(self):
        code, channel = otp.create_otp(Purpose.REGISTRATION_PATIENT, "9000000001")
        self.assertEqual(channel, "sms")
        self.assertIsNone(otp.verify_otp(Purpose.REGISTRATION_PATIENT, "9000000001", code).target_id)

    def test_a_new_code_cannot_be_asked_for_straight_away(self):
        otp.create_otp(Purpose.LOGIN_PATIENT, "b@example.com")
        with self.assertRaisesMessage(OTPError, "Please wait"):
            otp.create_otp(Purpose.LOGIN_PATIENT, "b@example.com")
        otp.create_otp(Purpose.PASSWORD_RESET_PATIENT, "b@example.com")           # a different purpose is its own counter

    def test_five_wrong_codes_lock_the_code_even_for_the_right_one(self):
        code, _ = otp.create_otp(Purpose.LOGIN_PATIENT, "c@example.com")
        wrong = "000000" if code != "000000" else "111111"
        for left in (4, 3, 2, 1):
            with self.assertRaisesMessage(OTPError, f"{left} attempt"):
                otp.verify_otp(Purpose.LOGIN_PATIENT, "c@example.com", wrong)
        with self.assertRaisesMessage(OTPError, "Too many"):
            otp.verify_otp(Purpose.LOGIN_PATIENT, "c@example.com", wrong)
        with self.assertRaisesMessage(OTPError, "Too many"):
            otp.verify_otp(Purpose.LOGIN_PATIENT, "c@example.com", code)

    def test_a_code_for_one_purpose_does_not_open_another(self):
        code, _ = otp.create_otp(Purpose.LOGIN_PATIENT, "d@example.com")
        with self.assertRaisesMessage(OTPError, "No active code"):
            otp.verify_otp(Purpose.PASSWORD_RESET_PATIENT, "d@example.com", code)


class ActionTokenTests(SimpleTestCase):
    def test_a_token_only_works_for_the_purpose_it_was_made_for(self):
        token = otp.make_action_token(Purpose.LOGIN_PATIENT, "e@example.com", "patient", 3, "")
        self.assertEqual(otp.decode_action_token(token, Purpose.LOGIN_PATIENT)["target_id"], 3)
        with self.assertRaisesMessage(OTPError, "Invalid verification token"):
            otp.decode_action_token(token, Purpose.PASSWORD_RESET_STAFF)
        with self.assertRaisesMessage(OTPError, "Invalid verification token"):
            otp.decode_action_token("not-a-token", Purpose.LOGIN_PATIENT)


class RevokedTokenTests(SimpleTestCase):
    def test_a_revoked_token_is_refused_until_it_would_have_expired(self):
        self.assertFalse(otp.is_revoked("jti-never-seen"))
        otp.revoke_token("jti-revoked-1", time.time() + 60)
        self.assertTrue(otp.is_revoked("jti-revoked-1"))
        self.assertTrue(0 < otp._redis().ttl("revoked:jti-revoked-1") <= 60)

    def test_a_token_that_has_already_expired_is_not_stored(self):
        otp.revoke_token("jti-expired-1", time.time() - 5)
        self.assertFalse(otp.is_revoked("jti-expired-1"))
