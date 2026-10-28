"""Tests of the flat core modules: the health endpoint, SMS logging, storage download names."""
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from core import messaging as sms
from core.storage import _attachment_disposition


class HealthCheckTests(TestCase):
    def test_health_endpoint_returns_200_or_503_json(self):
        """The /health/ endpoint must always return JSON with a boolean db"""
        response = self.client.get("/health/")
        self.assertIn(response.status_code, (200, 503))
        data = response.json()
        self.assertIn("status", data)
        self.assertIn("database", data)
        self.assertEqual(data["service"], "atomwalk-hms")


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
        with mock.patch("requests.post", return_value=resp), self.assertLogs("core.messaging", level="ERROR") as logs:
            self.assertFalse(sms.send_otp_sms("9876543210", "123456", "login"))
        text = "\n".join(logs.output)
        self.assertNotIn("9876543210", text)
        self.assertIn("3210", text)
        self.assertNotIn("123456", text)


class AttachmentDispositionTests(SimpleTestCase):
    """S3 rejects a response-content-disposition that isn't ISO-8859-1 — this"""

    def _assert_s3_safe(self, value):
        value.encode("iso-8859-1")          # must not raise
        value.encode("ascii")               # ours is pure ASCII

    def test_the_real_failing_title(self):
        v = _attachment_disposition("Handwritten Prescription RX-000002 — 2026-09-07.pdf")
        self._assert_s3_safe(v)
        self.assertIn('filename="Handwritten Prescription RX-000002 - 2026-09-07.pdf"', v)
        self.assertIn("filename*=UTF-8''", v)

    def test_accents_and_indic_scripts(self):
        for name in ("Café report.pdf", "రిపోర్ట్.pdf", "健康.pdf"):
            self._assert_s3_safe(_attachment_disposition(name))

    def test_quotes_and_newlines_cannot_break_the_header(self):
        v = _attachment_disposition('a"b\r\nSet-Cookie: x.pdf')
        self._assert_s3_safe(v)
        self.assertNotIn("\n", v)
        self.assertEqual(v.count('"'), 2)   # only the two wrapping the fallback name

    def test_blank_falls_back(self):
        self.assertIn('filename="download"', _attachment_disposition(""))
        self.assertIn('filename="download"', _attachment_disposition(None))
