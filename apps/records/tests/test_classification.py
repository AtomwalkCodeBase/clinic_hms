from unittest import mock

import fitz
from django.test import TestCase

from apps.records import services
from apps.records.models import DocumentClassification, MedicalDocument, SweepConfig

LAB_TEXT = "City laboratory. Hemoglobin 13 g/dL, glucose 90, cholesterol 180. Reference range attached."


class RuleTests(TestCase):
    databases = {"default"}

    def test_rules_come_from_the_database(self):
        rules = services.load_rules()
        self.assertIn("lab_report", rules)                                    # seeded by the migrations
        self.assertIn("hemoglobin", rules["lab_report"])

    def test_a_good_match_is_filed_under_that_type_with_its_confidence(self):
        code, confidence, details = services.classify(LAB_TEXT)               # 5 lab keywords found, nothing else
        self.assertEqual(code, "lab_report")
        self.assertEqual(confidence, 63.6)
        self.assertEqual((details["evidence"], details["best_guess"]), (5.0, "lab_report"))

    def test_a_rule_change_applies_to_the_next_document(self):
        DocumentClassification.objects.create(code="dental", name="dental", keywords="tooth|molar|dentist")
        self.assertEqual(services.classify("The dentist checked the molar and the tooth")[0], "dental")

    def test_a_switched_off_rule_is_ignored(self):
        DocumentClassification.objects.filter(code="lab_report").update(is_active=False)
        self.assertNotIn("lab_report", services.load_rules())

    def test_types_without_keywords_are_never_assigned_by_the_rules(self):
        DocumentClassification.objects.create(code="note_only", name="note_only", keywords="")
        DocumentClassification.objects.create(code="only_minus", name="only_minus", keywords="-lab report")
        self.assertNotIn("note_only", services.load_rules())
        self.assertNotIn("only_minus", services.load_rules())

    def test_too_little_evidence_is_unable_to_classify_and_keeps_the_best_guess(self):
        DocumentClassification.objects.create(code="dental", name="dental", keywords="tooth|molar|dentist|crown")
        code, confidence, details = services.classify("only a tooth is mentioned")      # one keyword
        self.assertIsNone(code)
        self.assertEqual((details["best_guess"], details["evidence"]), ("dental", 1.0))

    def test_no_text_is_unable_to_classify(self):
        self.assertEqual(services.classify("   ")[:2], (None, 0.0))

    def test_no_match_at_all_is_unable_to_classify(self):
        code, confidence, details = services.classify("some unclear text")
        self.assertEqual((code, confidence, details["best_guess"]), (None, 0.0, ""))

    def test_only_configured_types_are_compared(self):
        DocumentClassification.objects.all().delete()
        self.assertEqual(services.classify(LAB_TEXT)[:2], (None, 0.0))

    def test_the_confidence_bar_is_a_setting(self):
        SweepConfig.objects.update_or_create(pk=1, defaults={"min_confidence": 90})
        self.assertIsNone(services.classify(LAB_TEXT)[0])                       # 63.6 is below 90
        SweepConfig.objects.filter(pk=1).update(min_confidence=60)
        self.assertEqual(services.classify(LAB_TEXT)[0], "lab_report")

    def test_the_evidence_scale_is_a_setting(self):
        SweepConfig.objects.update_or_create(pk=1, defaults={"evidence_scale": 3})
        self.assertGreater(services.classify(LAB_TEXT)[1], 63.6)                # 5 hits are plenty on a small scale

    def test_a_minus_word_rules_a_type_out(self):
        DocumentClassification.objects.filter(code="lab_report").update(keywords="laboratory|hemoglobin|glucose|cholesterol|reference range|-city laboratory^5")
        self.assertIsNone(services.classify(LAB_TEXT)[0])


class ReclassifyTests(TestCase):
    databases = {"default"}

    def test_documents_are_judged_again_with_todays_rules_but_a_persons_verdict_stays(self):
        from apps.records.tests.helpers import make_doc
        old = make_doc(status="completed", doc_type=None, by="system", data={"extracted_text": LAB_TEXT, "method": "rule"})
        theirs = make_doc(status="completed", doc_type="scan", by="human", data={"extracted_text": LAB_TEXT})
        issued = make_doc(status="completed", doc_type="prescription", by="human", source_tenant_id=3)
        counts = services.reclassify_existing()
        self.assertEqual(counts, {"checked": 1, "changed": 1, "classified": 1, "unclassified": 0})
        self.assertEqual(MedicalDocument.objects.get(pk=old.pk).doc_type, "lab_report")
        self.assertEqual(MedicalDocument.objects.get(pk=theirs.pk).doc_type, "scan")
        self.assertEqual(MedicalDocument.objects.get(pk=issued.pk).doc_type, "prescription")

    def test_a_document_that_stops_fitting_becomes_unable_to_classify(self):
        from apps.records.tests.helpers import make_doc
        doc = make_doc(status="completed", doc_type="lab_report", by="system", data={"extracted_text": "nothing relevant"})
        services.reclassify_existing()
        doc = MedicalDocument.objects.get(pk=doc.pk)
        self.assertIsNone(doc.classification_id)
        self.assertIn("Unable to classify", doc.classification_details["note"])


class ValidTypesTests(TestCase):
    databases = {"default"}

    def test_a_new_type_is_valid_without_a_code_change(self):
        self.assertNotIn("dental", [c.code for c in DocumentClassification.configured()])
        DocumentClassification.objects.create(code="dental", name="Dental", keywords="tooth")
        self.assertIn("dental", [c.code for c in DocumentClassification.configured()])

    def test_there_are_no_built_in_types(self):
        DocumentClassification.objects.all().delete()
        self.assertEqual(DocumentClassification.configured(), [])

    def test_consult_note_is_staff_only(self):
        self.assertTrue(DocumentClassification.for_code("consult_note").is_staff_only)
        self.assertNotIn("consult_note", [c.code for c in DocumentClassification.configured()])


class ExtractTextTests(TestCase):
    def test_pdf_with_a_text_layer_needs_no_ocr(self):
        doc = fitz.open()
        doc.new_page().insert_text((50, 80), LAB_TEXT, fontsize=10)
        with mock.patch("apps.records.services.ocr") as ocr:
            text = services.extract_text(doc.tobytes(), "application/pdf")
        self.assertIn("Hemoglobin", text)
        ocr.run.assert_not_called()

    def test_image_goes_through_rapidocr(self):
        with mock.patch("apps.records.services.ocr") as ocr:
            ocr.run.return_value.text = " Rx tablet "
            self.assertEqual(services.extract_text(b"\xff\xd8\xff...", "image/jpeg"), "Rx tablet")
            ocr.run.assert_called_once()
