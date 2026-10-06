from django.test import TestCase
from django.urls import NoReverseMatch, reverse
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.platform_admin.classification_rule_views import DocumentCorrectView, DocumentReportView, ReclassifyView
from apps.records.models import MedicalDocument
from apps.records.tests.helpers import make_doc
from core.authentication import MockUser


def call(view, method, data=None, params=None, **kwargs):
    request = getattr(APIRequestFactory(), method)("/x", params or data or {}, format="json")
    force_authenticate(request, user=MockUser({"user_id": 1, "role": "platform_admin"}))
    return view.as_view()(request, **kwargs)


class RemovedSettingsTests(TestCase):
    """The document types, keywords and Celery settings are fixed in code, so no screen or endpoint edits them."""

    def test_there_is_no_endpoint_for_rules_or_sweep_settings(self):
        with self.assertRaises(NoReverseMatch):
            reverse("platform-classification-rules")
        with self.assertRaises(NoReverseMatch):
            reverse("platform-classification-rule-detail", kwargs={"pk": 1})
        with self.assertRaises(NoReverseMatch):
            reverse("platform-records-sweep-config")

    def test_the_report_correction_and_reclassify_endpoints_remain(self):
        self.assertTrue(reverse("platform-records-report"))
        self.assertTrue(reverse("platform-records-report-detail", kwargs={"pk": 1}))
        self.assertTrue(reverse("platform-records-reclassify"))


class DocumentReportViewTests(TestCase):
    databases = {"default"}

    def test_lists_documents_filtered_by_method_and_status(self):
        make_doc(status="completed", document_type="lab_report", by="rules", name="a.pdf")
        make_doc(status="completed", document_type="lab_report", by="human", name="b.pdf")
        make_doc(status="failed", name="c.pdf")
        resp = call(DocumentReportView, "get")
        self.assertEqual(resp.data["data"]["pagination"]["total_count"], 3)

        def rows(**params):
            return call(DocumentReportView, "get", params=params).data["data"]["results"]

        self.assertEqual([r["method"] for r in rows(method="rule")], ["rule"])
        self.assertEqual([r["method"] for r in rows(method="staff")], ["staff"])
        self.assertEqual([r["processing_status"] for r in rows(status="failed")], ["failed"])

    def test_it_offers_the_fixed_types_a_person_can_choose(self):
        types = call(DocumentReportView, "get").data["data"]["doc_types"]
        self.assertIn("lab_report", types)
        self.assertNotIn("not_classified", types)

    def test_a_row_shows_the_patient_the_type_and_the_status(self):
        make_doc(status="review_required", by="rules", name="u.pdf")
        row = call(DocumentReportView, "get").data["data"]["results"][0]
        self.assertEqual((row["awpid"], row["doc_type"], row["processing_status"]),
                         ("AWP-T1", "not_classified", "review_required"))


class DocumentCorrectViewTests(TestCase):
    databases = {"default"}

    def test_correcting_a_document_sets_type_and_marks_it_human(self):
        doc = make_doc(status="completed", document_type="lab_report", by="rules")
        resp = call(DocumentCorrectView, "patch", {"doc_type": "prescription"}, pk=doc.id)
        self.assertEqual(resp.status_code, 200)
        doc = MedicalDocument.objects.get(pk=doc.pk)
        self.assertEqual((doc.document_type, doc.status), ("prescription", "completed"))
        self.assertEqual(resp.data["data"]["method"], "staff")

    def test_rejects_an_unknown_doc_type(self):
        doc = make_doc(status="completed")
        self.assertEqual(call(DocumentCorrectView, "patch", {"doc_type": "not_a_real_type"}, pk=doc.id).status_code, 400)
        self.assertEqual(call(DocumentCorrectView, "patch", {"doc_type": "not_classified"}, pk=doc.id).status_code, 400)

    def test_a_document_that_needs_review_can_be_filed(self):
        doc = make_doc(status="review_required", by="rules")
        self.assertEqual(call(DocumentCorrectView, "patch", {"doc_type": "imaging_report"}, pk=doc.id).status_code, 200)
        self.assertEqual(MedicalDocument.objects.get(pk=doc.pk).status, "completed")

    def test_correcting_a_failed_document_completes_it(self):
        doc = make_doc(status="failed", error_message="unreadable")
        call(DocumentCorrectView, "patch", {"doc_type": "lab_report"}, pk=doc.id)
        doc = MedicalDocument.objects.get(pk=doc.pk)
        self.assertEqual((doc.status, doc.error_message), ("completed", ""))

    def test_a_file_still_being_read_cannot_be_corrected(self):
        doc = make_doc(status="classifying")
        self.assertEqual(call(DocumentCorrectView, "patch", {"doc_type": "lab_report"}, pk=doc.id).status_code, 400)

    def test_an_unknown_document_is_not_found(self):
        self.assertEqual(call(DocumentCorrectView, "patch", {"doc_type": "lab_report"}, pk=999999).status_code, 404)

    def test_only_a_platform_admin_can(self):
        doc = make_doc(status="completed")
        request = APIRequestFactory().patch("/x", {"doc_type": "lab_report"}, format="json")
        force_authenticate(request, user=MockUser({"user_id": 1, "role": "patient"}))
        self.assertEqual(DocumentCorrectView.as_view()(request, pk=doc.id).status_code, 403)


class ReclassifyViewTests(TestCase):
    databases = {"default"}

    def test_reclassify_runs_the_rules_again(self):
        make_doc(status="review_required", by="rules",
                 text="City laboratory report. Hemoglobin, glucose, cholesterol, reference range.")
        resp = call(ReclassifyView, "post")
        self.assertEqual(resp.data["data"], {"checked": 1, "changed": 1, "classified": 1, "unclassified": 0})
