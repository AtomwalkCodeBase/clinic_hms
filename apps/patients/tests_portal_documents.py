"""
Patient-portal document semantics (registry DB only): the list, retyping, retry, zip and the activity.

There is no patient-side delete: a document stays in the patient's records.
"""

from unittest import mock

from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.patients.portal_views import PortalDocumentDetailView, PortalDocumentListCreateView
from apps.records.classification import CHOOSABLE_TYPES
from apps.records.models import PatientDocumentClassification
from apps.records.tests.helpers import identity, make_doc, reload
from apps.registry.models import PatientAccount
from core.authentication import MockUser


@override_settings(RECORDS_REVIEW_FROM="")          # the review step is off here: every upload counts as confirmed
class PortalDocumentTests(TestCase):
    databases = {"default"}

    def setUp(self):
        self.acct = PatientAccount.objects.using("default").create(
            awpid="AW-DOC-1", full_name="P", mobile="9222222222", password="x",
        )
        identity(self.acct.awpid)

    def make_doc(self, **kw):
        return make_doc(self.acct.awpid, status="completed", document_type="lab_report", by="rules", **kw)

    def user(self):
        return MockUser({"user_id": self.acct.id, "role": "patient", "awpid": self.acct.awpid})

    def call(self, view, method, data=None, **kwargs):
        factory = getattr(APIRequestFactory(), method)
        request = factory("/x/", data, format="json") if data is not None else factory("/x/")
        force_authenticate(request, user=self.user())
        return view.as_view()(request, **kwargs)

    def patch(self, doc, **body):
        return self.call(PortalDocumentDetailView, "patch", body, doc_id=doc.id)

    # ── there is no delete ──
    def test_a_document_cannot_be_deleted_by_the_patient(self):
        doc = self.make_doc()
        self.assertEqual(self.call(PortalDocumentDetailView, "delete", doc_id=doc.id).status_code, 405)
        with self.assertRaises(NoReverseMatch):
            reverse("portal-documents-bulk-delete")

    # ── the list ──
    def test_the_list_shows_status_type_and_size(self):
        doc = self.make_doc(name="rx.pdf", size=1234)
        results = self.call(PortalDocumentListCreateView, "get").data["results"]
        self.assertEqual([(r["id"], r["file_name"], r["title"], r["processing_status"], r["doc_type"], r["size"])
                          for r in results], [(doc.id, "rx.pdf", "rx.pdf", "completed", "lab_report", 1234)])

    def test_someone_elses_documents_are_not_listed(self):
        make_doc("AW-OTHER", status="completed", document_type="lab_report")
        self.assertEqual(self.call(PortalDocumentListCreateView, "get").data["results"], [])

    def test_the_row_carries_the_number_a_hospital_printed_on_the_document(self):
        make_doc(self.acct.awpid, status="completed", document_type="prescription", by="issued", uploaded_by="staff",
                 source_tenant_id="7", document_ref="RX-1")
        row = self.call(PortalDocumentListCreateView, "get").data["results"][0]
        self.assertEqual((row["public_document_id"], row["source_tenant_id"], row["method"]), ("RX-1", "7", "staff"))
        self.assertNotIn("hospital_label", row)
        self.assertNotIn("doctor_label", row)

    def test_an_unclassified_row_shows_no_guess_at_all(self):
        doc = make_doc(self.acct.awpid, status="review_required", by="rules", name="u.pdf")
        PatientDocumentClassification.objects.filter(document=doc).update(ai_document_type="lab_report")
        row = self.call(PortalDocumentListCreateView, "get").data["results"][0]
        self.assertEqual((row["doc_type"], row["suggested_type"], row["confirmed"], row["processing_status"]),
                         ("not_classified", None, False, "review_required"))
        self.assertNotIn("best_guess", row)

    def test_a_failed_row_carries_its_reason(self):
        make_doc(self.acct.awpid, status="failed", error_message="The file is empty.")
        self.assertEqual(self.call(PortalDocumentListCreateView, "get").data["results"][0]["error"], "The file is empty.")

    def test_the_list_can_be_filtered_by_status(self):
        make_doc(self.acct.awpid, status="queued", name="q.pdf")
        make_doc(self.acct.awpid, status="review_required", name="r.pdf")
        make_doc(self.acct.awpid, status="completed", name="c.pdf")
        request = APIRequestFactory().get("/x/", {"status": "queued,review_required"})
        force_authenticate(request, user=self.user())
        results = PortalDocumentListCreateView.as_view()(request).data["results"]
        self.assertEqual(sorted(r["processing_status"] for r in results), ["queued", "review_required"])

    # ── choosing a type ──
    def test_the_patient_can_file_a_document_the_rules_could_not_place(self):
        doc = make_doc(self.acct.awpid, status="review_required", by="rules")
        resp = self.patch(doc, doc_type="prescription")
        self.assertEqual(resp.status_code, 200)
        doc = reload(doc)
        self.assertEqual((doc.document_type, doc.processing_status), ("prescription", "completed"))
        self.assertEqual(resp.data["data"]["method"], "staff")

    def test_the_patient_can_only_choose_one_of_the_fixed_types(self):
        doc = make_doc(self.acct.awpid, status="review_required", by="rules")
        for bad in ("made_up", "not_classified", "LAB_REPORT"):
            self.assertEqual(self.patch(doc, doc_type=bad).status_code, 400, bad)
        self.assertEqual(reload(doc).document_type, "not_classified")

    def test_the_type_of_a_hospital_issued_report_cannot_be_changed(self):
        doc = self.make_doc(uploaded_by="staff", source_tenant_id="7", source_ref="encounter:abc")
        self.assertEqual(self.patch(doc, doc_type="imaging_report").status_code, 400)

    def test_the_detail_offers_the_fixed_types(self):
        doc = self.make_doc()
        data = self.call(PortalDocumentDetailView, "get", doc_id=doc.id).data["data"]
        self.assertEqual(sorted(data["doc_types"]), sorted(CHOOSABLE_TYPES))

    # ── retry ──
    def test_a_failed_file_can_be_tried_again(self):
        doc = make_doc(self.acct.awpid, status="failed", error_message="boom")
        with mock.patch("apps.records.tasks.extract_document_task.apply_async") as delay:
            resp = self.patch(doc, action="retry")
        self.assertEqual(resp.status_code, 200)
        delay.assert_called_once_with(args=[doc.id, "instant"], queue="instant")
        self.assertEqual((reload(doc).status, reload(doc).error_message), ("queued", ""))

    def test_only_a_failed_file_can_be_retried(self):
        for status in ("completed", "review_required", "queued"):
            doc = make_doc(self.acct.awpid, status=status)
            self.assertEqual(self.patch(doc, action="retry").status_code, 400, status)

    def test_keeping_a_duplicate_is_gone_because_duplicates_are_no_longer_rejected(self):
        doc = make_doc(self.acct.awpid, status="completed")
        self.assertEqual(self.patch(doc, action="keep").status_code, 400)

    # ── the activity ──
    def events(self, doc):
        return [e["text"] for e in self.call(PortalDocumentDetailView, "get", doc_id=doc.id).data["data"]["events"]]

    def test_the_detail_tells_what_happened_to_the_report(self):
        doc = make_doc(self.acct.awpid, status="completed", document_type="lab_report", by="rules", name="x.pdf")
        self.assertEqual(self.events(doc), ["You uploaded this file", "Filed as Lab report by the rules"])
        self.patch(doc, doc_type="prescription")
        self.assertEqual(self.events(doc), ["You uploaded this file", "You set the type to Prescription"])

    def test_the_activity_of_a_document_that_needs_review_and_of_a_failure(self):
        review = make_doc(self.acct.awpid, status="review_required", by="rules")
        PatientDocumentClassification.objects.filter(document=review).update(ai_document_type="lab_report")
        failed = make_doc(self.acct.awpid, status="failed", error_message="The file is empty.")
        self.assertEqual(self.events(review)[-1], "The rules couldn’t tell what it is - choose its type")
        self.assertEqual(self.events(failed)[-1], "We couldn’t read it — The file is empty.")
