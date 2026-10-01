"""
Patient-portal document delete semantics (registry DB only).

A patient deleting a document removes it from their own view (deleted_at) — whether they uploaded it or a hospital
made it for them. The issuing hospital keeps its own copy, so nothing is lost on its side.
"""

from unittest import mock

from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.patients.portal_views import (
    PortalDocumentBulkDeleteView, PortalDocumentDetailView, PortalDocumentListCreateView,
)
from apps.records.models import DocumentClassification, MedicalDocument
from apps.records.tests.helpers import identity, make_doc, reload
from apps.registry.models import PatientAccount
from core.authentication import MockUser


class PortalDocumentDeleteTests(TestCase):
    databases = {"default"}

    def setUp(self):
        self.acct = PatientAccount.objects.using("default").create(
            awpid="AW-DOC-1", full_name="P", mobile="9222222222", password="x",
        )
        identity(self.acct.awpid)

    def make_doc(self, **kw):
        return make_doc(self.acct.awpid, status="completed", doc_type="lab_report", by="system", **kw)

    def call(self, view, method, **kwargs):
        request = getattr(APIRequestFactory(), method)("/x/")
        force_authenticate(request, user=MockUser({"user_id": self.acct.id, "role": "patient", "awpid": self.acct.awpid}))
        return view.as_view()(request, **kwargs)

    def delete(self, doc):
        return self.call(PortalDocumentDetailView, "delete", doc_id=doc.id)

    def test_a_self_uploaded_document_is_deleted(self):
        doc = self.make_doc(uploaded_by="patient")
        self.assertEqual(self.delete(doc).status_code, 200)
        self.assertIsNotNone(reload(doc).deleted_at)

    def test_a_hospital_authored_document_is_only_hidden_the_hospital_keeps_its_copy(self):
        doc = self.make_doc(uploaded_by="staff", source_tenant_id=7, source_ref="encounter:abc")
        self.assertEqual(self.delete(doc).status_code, 200)
        self.assertIsNotNone(reload(doc).hidden_at)
        self.assertIsNone(reload(doc).deleted_at)
        self.assertEqual(self.call(PortalDocumentListCreateView, "get").data["results"], [])

    def test_someone_elses_document_cannot_be_deleted(self):
        doc = make_doc("AW-OTHER", status="completed", doc_type="lab_report", uploaded_by="patient")
        self.assertGreaterEqual(self.delete(doc).status_code, 400)
        self.assertIsNone(reload(doc).deleted_at)

    def test_the_list_shows_status_type_and_size_and_hides_deleted_and_staff_only(self):
        shown = self.make_doc(name="rx.pdf", size=1234)
        deleted = self.make_doc(name="gone.pdf")
        make_doc(self.acct.awpid, status="completed", doc_type="consult_note", by="human", name="note.pdf")
        self.delete(deleted)

        results = self.call(PortalDocumentListCreateView, "get").data["results"]
        self.assertEqual([(r["id"], r["file_name"], r["processing_status"], r["doc_type"], r["size"]) for r in results],
                         [(shown.id, "rx.pdf", "completed", "lab_report", 1234)])

    def patch(self, doc, doc_type):
        request = APIRequestFactory().patch("/x/", {"doc_type": doc_type}, format="json")
        force_authenticate(request, user=MockUser({"user_id": self.acct.id, "role": "patient", "awpid": self.acct.awpid}))
        return PortalDocumentDetailView.as_view()(request, doc_id=doc.id)

    def test_the_patient_can_correct_the_type_of_their_own_upload(self):
        doc = make_doc(self.acct.awpid, status="completed", by="system")      # unable to classify
        resp = self.patch(doc, "prescription")
        self.assertEqual(resp.status_code, 200)
        doc = reload(doc)
        self.assertEqual((doc.doc_type, doc.method, doc.processing_status), ("prescription", "staff", "completed"))

    def test_the_patient_can_only_choose_a_configured_type(self):
        doc = make_doc(self.acct.awpid, status="completed", by="system")
        self.assertEqual(self.patch(doc, "made_up").status_code, 400)
        self.assertEqual(self.patch(doc, "consult_note").status_code, 400)       # staff-only is never offered
        self.assertEqual(reload(doc).doc_type, "")

    def test_the_type_of_a_hospital_issued_report_cannot_be_changed(self):
        doc = self.make_doc(uploaded_by="staff", source_tenant_id=7, source_ref="encounter:abc")
        self.assertEqual(self.patch(doc, "scan").status_code, 400)

    def test_a_rejected_duplicate_cannot_be_retyped(self):
        doc = make_doc(self.acct.awpid, status="rejected")
        self.assertEqual(self.patch(doc, "prescription").status_code, 400)

    def test_a_rejected_duplicate_can_be_kept_and_goes_back_through_the_pipeline(self):
        doc = make_doc(self.acct.awpid, status="rejected", data={"duplicate_of": 5})
        with mock.patch("apps.records.tasks.extract_document_task.delay") as extract:
            request = APIRequestFactory().patch("/x/", {"action": "keep"}, format="json")
            force_authenticate(request, user=MockUser({"user_id": self.acct.id, "role": "patient", "awpid": self.acct.awpid}))
            resp = PortalDocumentDetailView.as_view()(request, doc_id=doc.id)
        self.assertEqual(resp.status_code, 200)
        extract.assert_called_once_with(doc.id)
        row = MedicalDocument.objects.get(pk=doc.pk)
        self.assertTrue(row.classification_details["keep_duplicate"])
        self.assertEqual((row.status, row.error), ("extracting", ""))        # queued, then claimed by the dispatch

    def test_only_a_duplicate_can_be_kept_and_only_a_failed_file_retried(self):
        for status, action in (("completed", "keep"), ("completed", "retry"), ("failed", "keep"), ("rejected", "retry")):
            doc = make_doc(self.acct.awpid, status=status)
            request = APIRequestFactory().patch("/x/", {"action": action}, format="json")
            force_authenticate(request, user=MockUser({"user_id": self.acct.id, "role": "patient", "awpid": self.acct.awpid}))
            self.assertEqual(PortalDocumentDetailView.as_view()(request, doc_id=doc.id).status_code, 400, (status, action))

    def test_a_failed_file_can_be_tried_again(self):
        doc = make_doc(self.acct.awpid, status="failed")
        MedicalDocument.objects.filter(pk=doc.pk).update(error="boom", attempts=3)
        with mock.patch("apps.records.tasks.extract_document_task.delay"):
            request = APIRequestFactory().patch("/x/", {"action": "retry"}, format="json")
            force_authenticate(request, user=MockUser({"user_id": self.acct.id, "role": "patient", "awpid": self.acct.awpid}))
            self.assertEqual(PortalDocumentDetailView.as_view()(request, doc_id=doc.id).status_code, 200)
        row = MedicalDocument.objects.get(pk=doc.pk)
        self.assertEqual((row.error, row.attempts, row.status), ("", 1, "extracting"))

    def test_a_rejected_row_points_to_the_original(self):
        doc = make_doc(self.acct.awpid, status="rejected", data={"duplicate_of": 7})
        row = next(r for r in self.call(PortalDocumentListCreateView, "get").data["results"] if r["id"] == doc.id)
        self.assertEqual(row["duplicate_of"], 7)

    def test_the_detail_offers_the_configured_types(self):
        doc = self.make_doc()
        data = self.call(PortalDocumentDetailView, "get", doc_id=doc.id).data["data"]
        self.assertEqual(sorted(data["doc_types"]), sorted(c.code for c in DocumentClassification.configured()))

    def test_an_unclassified_row_says_what_it_came_closest_to(self):
        make_doc(self.acct.awpid, status="completed", by="system", data={"best_guess": "lab_report"}, name="u.pdf")
        row = self.call(PortalDocumentListCreateView, "get").data["results"][0]
        self.assertEqual((row["doc_type"], row["best_guess"]), ("", "lab_report"))

    def bulk_delete(self, ids):
        request = APIRequestFactory().post("/x/", {"ids": ids}, format="json")
        force_authenticate(request, user=MockUser({"user_id": self.acct.id, "role": "patient", "awpid": self.acct.awpid}))
        return PortalDocumentBulkDeleteView.as_view()(request)

    def test_several_reports_can_be_deleted_at_once(self):
        a, b, c = self.make_doc(name="a.pdf"), self.make_doc(name="b.pdf"), self.make_doc(name="c.pdf")
        resp = self.bulk_delete([a.id, b.id])
        self.assertEqual((resp.status_code, resp.data["data"]["deleted"], resp.data["data"]["skipped"]), (200, 2, []))
        self.assertIsNotNone(reload(a).deleted_at)
        self.assertIsNotNone(reload(b).deleted_at)
        self.assertIsNone(reload(c).deleted_at)

    def test_bulk_delete_skips_what_is_not_the_patients_and_never_blocks_the_rest(self):
        mine = self.make_doc()
        theirs = make_doc("AW-OTHER", status="completed", doc_type="scan", by="system")
        note = make_doc(self.acct.awpid, status="completed", doc_type="consult_note", by="human")
        resp = self.bulk_delete([mine.id, theirs.id, note.id, 999999])
        self.assertEqual(resp.data["data"]["deleted"], 1)
        self.assertCountEqual(resp.data["data"]["skipped"], [theirs.id, note.id, 999999])
        self.assertIsNone(reload(theirs).deleted_at)
        self.assertIsNone(reload(note).deleted_at)

    def test_bulk_delete_needs_ids_and_has_a_ceiling(self):
        self.assertEqual(self.bulk_delete([]).status_code, 400)
        self.assertEqual(self.bulk_delete(list(range(1, 102))).status_code, 400)

    def test_a_hospital_issued_report_is_removed_from_the_view_in_bulk_too(self):
        issued = self.make_doc(uploaded_by="staff", source_tenant_id=7, source_ref="encounter:abc")
        self.assertEqual(self.bulk_delete([issued.id]).data["data"]["deleted"], 1)
        self.assertIsNotNone(reload(issued).hidden_at)

    def test_the_detail_tells_what_happened_to_the_report(self):
        doc = make_doc(self.acct.awpid, status="completed", doc_type="lab_report", by="system", name="x.pdf")
        MedicalDocument.objects.filter(pk=doc.pk).update(score=81.4)
        texts = [e["text"] for e in self.call(PortalDocumentDetailView, "get", doc_id=doc.id).data["data"]["events"]]
        self.assertEqual(texts, ["You uploaded this file", "Filed as Lab report by the rules (81% confident)"])
        self.patch(doc, "prescription")
        texts = [e["text"] for e in self.call(PortalDocumentDetailView, "get", doc_id=doc.id).data["data"]["events"]]
        self.assertEqual(texts, ["You uploaded this file", "You set the type to Prescription"])

    def test_the_activity_of_a_duplicate_and_of_a_failure(self):
        dup = make_doc(self.acct.awpid, status="rejected")
        MedicalDocument.objects.filter(pk=dup.pk).update(error="Same as a.pdf, uploaded 01 Oct 2026.")
        failed = make_doc(self.acct.awpid, status="failed")
        MedicalDocument.objects.filter(pk=failed.pk).update(error="The file is empty.")
        last = lambda d: self.call(PortalDocumentDetailView, "get", doc_id=d.id).data["data"]["events"][-1]["text"]   # noqa: E731
        self.assertEqual(last(dup), "Not added: Same as a.pdf, uploaded 01 Oct 2026.")
        self.assertEqual(last(failed), "We couldn’t read it — The file is empty.")

    def test_the_list_can_be_filtered_by_status(self):
        make_doc(self.acct.awpid, status="queued", name="q.pdf")
        make_doc(self.acct.awpid, status="rejected", name="dup.pdf")
        request = APIRequestFactory().get("/x/", {"status": "queued,rejected"})
        force_authenticate(request, user=MockUser({"user_id": self.acct.id, "role": "patient", "awpid": self.acct.awpid}))
        results = PortalDocumentListCreateView.as_view()(request).data["results"]
        self.assertEqual(sorted(r["processing_status"] for r in results), ["queued", "rejected"])
