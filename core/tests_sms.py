"""core/tests_sms.py — phone numbers must not appear in full in SMS delivery logs."""

from unittest import mock

from django.test import SimpleTestCase, override_settings

from core import sms


class MaskTests(SimpleTestCase):
    def test_keeps_only_the_last_four_digits(self):
        self.assertEqual(sms._mask("9876543210"), "******3210")
        self.assertEqual(sms._mask("+919876543210"), "*********3210")
        self.assertEqual(sms._mask("123"), "123")
        self.assertEqual(sms._mask(None), "")


class FailureLogsTests(SimpleTestCase):
    @override_settings(SMS_BACKEND="msg91", SMS_FALLBACK_BACKEND="", MSG91_AUTH_KEY="k", MSG91_TEMPLATE_ID="t")
    def test_msg91_failure_logs_do_not_contain_the_full_number(self):
        resp = mock.Mock(status_code=500, text="boom", content=b"", ok=False)
        with mock.patch("requests.post", return_value=resp), self.assertLogs("core.sms", level="ERROR") as logs:
            self.assertFalse(sms.send_otp_sms("9876543210", "123456", "login"))
        text = "\n".join(logs.output)
        self.assertNotIn("9876543210", text)
        self.assertIn("3210", text)
        self.assertNotIn("123456", text)
