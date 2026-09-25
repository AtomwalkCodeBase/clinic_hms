"""
core/tests_extract_text.py
--------------------------
DB-independent tests for the extraction-only entry point used by the mobile
upload-and-extract flow (doc_classifier.extract_text) and the small helpers
around it. Deliberately separate from tests_doc_classifier.py: extract_text
must NOT classify, so nothing here asserts on kind/panel/date.

    python -c "import django; django.setup(); import unittest; unittest.main(module='core.tests_extract_text', argv=['x'])"

(`manage.py test` can't build this project's dynamic multi-tenant DB config,
and none of these tests need a database.)
"""

import io

from django.test import SimpleTestCase
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

from core import doc_classifier


def _pdf(pages: int, text: str = "Extraction test page, long enough to skip the OCR fallback entirely") -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for i in range(pages):
        c.drawString(72, 750, f"{text} #{i}")
        c.showPage()
    c.save()
    return buf.getvalue()


class ExtractTextTests(SimpleTestCase):
    def test_pdf_text_layer_is_returned_without_ocr(self):
        text, conf = doc_classifier.extract_text(_pdf(1), "application/pdf")
        self.assertIn("Extraction test page", text)
        self.assertIsNone(conf)   # text layer was enough; OCR never ran

    def test_multi_page_pdf_returns_every_page(self):
        text, _ = doc_classifier.extract_text(_pdf(3), "application/pdf")
        for i in range(3):
            self.assertIn(f"#{i}", text)

    def test_encrypted_pdf_raises_extraction_error(self):
        w = PdfWriter()
        for pg in PdfReader(io.BytesIO(_pdf(1))).pages:
            w.add_page(pg)
        w.encrypt("secret")
        buf = io.BytesIO()
        w.write(buf)
        with self.assertRaises(doc_classifier.ExtractionError) as cm:
            doc_classifier.extract_text(buf.getvalue(), "application/pdf")
        self.assertEqual(cm.exception.code, "encrypted")
        self.assertIn("password", cm.exception.message.lower())

    def test_does_not_classify(self):
        # A lab-report-looking text must come back as plain text — no kind,
        # panel or date decisions belong to this entry point.
        result = doc_classifier.extract_text(
            _pdf(1, "Haemoglobin 13.5 g/dL Reference Range 12-16 Sample Collected On 11/09/2026"),
            "application/pdf",
        )
        self.assertIsInstance(result, tuple)
        self.assertIsInstance(result[0], str)


class ExtractDocumentJsonTests(SimpleTestCase):
    KEYS = {"version", "text", "char_count", "page_count", "confidence", "method",
            "mime_type", "extracted_at", "duration_ms"}

    def test_result_has_the_documented_shape(self):
        r = doc_classifier.extract_document(_pdf(2), "application/pdf")
        self.assertEqual(set(r), self.KEYS)
        self.assertEqual(r["version"], 1)
        self.assertEqual(r["page_count"], 2)
        self.assertEqual(r["char_count"], len(r["text"]))
        self.assertEqual(r["mime_type"], "application/pdf")

    def test_text_layer_pdf_reports_method_pdf_text(self):
        r = doc_classifier.extract_document(_pdf(1), "application/pdf")
        self.assertEqual(r["method"], "pdf_text")
        self.assertIsNone(r["confidence"])

    def test_extract_text_is_the_tuple_view_of_the_same_result(self):
        raw = _pdf(1)
        text, conf = doc_classifier.extract_text(raw, "application/pdf")
        r = doc_classifier.extract_document(raw, "application/pdf")
        self.assertEqual((text, conf), (r["text"], r["confidence"]))

    def test_result_is_json_serialisable(self):
        import json
        json.dumps(doc_classifier.extract_document(_pdf(1), "application/pdf"))


class PdfPageCountTests(SimpleTestCase):
    def test_counts_pages(self):
        self.assertEqual(doc_classifier._pdf_page_count(_pdf(1)), 1)
        self.assertEqual(doc_classifier._pdf_page_count(_pdf(20)), 20)
        self.assertEqual(doc_classifier._pdf_page_count(_pdf(21)), 21)

    def test_garbage_is_zero_not_an_exception(self):
        self.assertEqual(doc_classifier._pdf_page_count(b"not a pdf"), 0)
