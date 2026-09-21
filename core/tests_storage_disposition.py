from django.test import SimpleTestCase

from core.storage import _attachment_disposition


class AttachmentDispositionTests(SimpleTestCase):
    """S3 rejects a response-content-disposition that isn't ISO-8859-1 — this
    broke every View/Download on prescriptions titled "Rx … — <date>"."""

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
