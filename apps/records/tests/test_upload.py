from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.records import services
from apps.records.models import DocumentBatch, MedicalDocument
from apps.records.tests.helpers import PDF, identity, make_doc
from apps.records.views import BatchDetailView, UploadView
from core.authentication import MockUser


def pdf(name="report.pdf", size=None):
    body = PDF if size is None else b"%PDF" + b"x" * (size - 4)
    return SimpleUploadedFile(name, body, content_type="application/pdf")


@mock.patch("apps.records.views.resolve_target_awpid_and_dob", return_value=("AWP-T1", None, None))
@mock.patch("apps.records.views.start_processing")
@mock.patch("apps.records.services.storage")            # the delete of an uploaded file
@mock.patch("core.storage.put_bytes", side_effect=lambda key, data, mime_type: key)      # the FileField's S3 write
class UploadViewTests(TestCase):
    databases = {"default"}

    def setUp(self):
        identity("AWP-T1")

    def post(self, files):
        request = APIRequestFactory().post("/api/v1/records/upload/", {"files": files}, format="multipart")
        force_authenticate(request, user=MockUser({"user_id": 1, "role": "patient", "awpid": "AWP-T1"}))
        return UploadView.as_view()(request)

    def test_every_upload_gets_a_batch_even_for_one_file(self, put, storage, start, _resolve):
        resp = self.post([pdf("a.pdf")])

        self.assertEqual(resp.status_code, 202)
        batch = DocumentBatch.objects.get()
        self.assertEqual((batch.patient.awpid, batch.total_files, resp.data["data"]["batch_id"]), ("AWP-T1", 1, batch.id))
        doc = MedicalDocument.objects.get()
        self.assertEqual((doc.processing_status, doc.patient.awpid, doc.file_name, doc.batch_id, doc.size, doc.document_type),
                         ("queued", "AWP-T1", "a.pdf", batch.id, len(PDF), "not_classified"))
        self.assertRegex(doc.file.name, rf"^documents/AWP-T1/{batch.id}/[0-9a-f]{{32}}\.pdf$")
        start.assert_called_once_with([doc.id], "instant")

    def test_the_file_goes_to_s3_through_the_file_field(self, put, storage, start, _resolve):
        self.post([pdf("a.pdf")])
        doc = MedicalDocument.objects.get()
        key, data = put.call_args.args
        self.assertEqual((key, data), (doc.file.name, PDF))
        self.assertEqual(put.call_args.kwargs["mime_type"], "application/pdf")

    def test_several_files_share_one_batch_and_one_folder_and_are_all_queued(self, put, storage, start, _resolve):
        resp = self.post([pdf("a.pdf"), pdf("b.pdf"), pdf("c.pdf")])

        self.assertEqual(resp.status_code, 202)
        batch = DocumentBatch.objects.get()
        self.assertEqual(batch.total_files, 3)
        docs = MedicalDocument.objects.filter(batch=batch)
        self.assertEqual(docs.count(), 3)
        self.assertTrue(all(d.file.name.startswith(f"documents/AWP-T1/{batch.id}/") for d in docs))
        self.assertEqual(len(resp.data["data"]["documents"]), 3)
        start.assert_called_once_with([d.id for d in docs.order_by("id")], "bulk")

    def test_a_long_file_name_is_cut_to_fit(self, put, storage, start, _resolve):
        self.post([SimpleUploadedFile("x" * 150 + ".pdf", PDF, content_type="application/pdf")])
        self.assertEqual(len(MedicalDocument.objects.get().file_name), 100)

    def test_the_content_is_not_checked_at_the_door(self, put, storage, start, _resolve):
        """A bad file is accepted and fails later in the extraction job, so it never blocks the others."""
        resp = self.post([pdf("ok.pdf"), SimpleUploadedFile("notes.pdf", b"hello", content_type="application/pdf")])
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(MedicalDocument.objects.count(), 2)

    def test_an_unknown_extension_is_stored_as_bin_and_never_trusted_as_a_content_type(self, put, storage, start, _resolve):
        self.post([SimpleUploadedFile("evil.html", b"<html>", content_type="text/html")])
        key, _data = put.call_args.args
        self.assertTrue(key.endswith(".bin"))
        self.assertEqual(put.call_args.kwargs["mime_type"], "application/octet-stream")

    def test_one_oversize_file_rejects_everything_before_s3(self, put, storage, start, _resolve):
        with mock.patch("apps.records.serializers.MAX_FILE_BYTES", 150):
            resp = self.post([pdf("ok.pdf"), pdf("big.pdf", size=200)])

        self.assertEqual(resp.status_code, 400)
        put.assert_not_called()
        start.assert_not_called()
        self.assertEqual(MedicalDocument.objects.count(), 0)

    def test_an_empty_file_rejects_everything_before_s3(self, put, storage, start, _resolve):
        resp = self.post([pdf("ok.pdf"), SimpleUploadedFile("empty.pdf", b"", content_type="application/pdf")])
        self.assertEqual(resp.status_code, 400)
        self.assertIn("empty", str(resp.data))
        put.assert_not_called()
        self.assertEqual(MedicalDocument.objects.count(), 0)

    def test_total_over_250mb_is_rejected(self, put, storage, start, _resolve):
        with mock.patch("apps.records.serializers.MAX_TOTAL_BYTES", 150):
            resp = self.post([pdf("a.pdf"), pdf("b.pdf")])        # 2 × 109 bytes > 150
        self.assertEqual(resp.status_code, 400)
        put.assert_not_called()

    def test_more_than_50_files_is_rejected(self, put, storage, start, _resolve):
        with mock.patch("apps.records.serializers.MAX_FILES", 2):
            resp = self.post([pdf("a.pdf"), pdf("b.pdf"), pdf("c.pdf")])
        self.assertEqual(resp.status_code, 400)
        put.assert_not_called()
        self.assertEqual(MedicalDocument.objects.count(), 0)

    def test_an_s3_failure_part_way_saves_nothing_and_deletes_what_was_sent(self, put, storage, start, _resolve):
        sent = []

        def flaky(key, data, mime_type):
            sent.append(key)
            if len(sent) == 2:
                raise RuntimeError("S3 down")
            return key

        put.side_effect = flaky
        resp = self.post([pdf("a.pdf"), pdf("b.pdf")])

        self.assertEqual(resp.status_code, 503)
        self.assertEqual((MedicalDocument.objects.count(), DocumentBatch.objects.count()), (0, 0))
        deleted = [call.args[0] for call in storage.delete.call_args_list]
        self.assertEqual(len(deleted), 1)                    # the one that was sent is cleaned up
        self.assertTrue(deleted[0].startswith("documents/AWP-T1/"))
        start.assert_not_called()

    def test_files_are_sent_to_s3_at_the_same_time(self, put, storage, start, _resolve):
        import threading
        import time
        active, peak, lock = 0, 0, threading.Lock()

        def slow_put(key, data, mime_type):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return key

        put.side_effect = slow_put
        resp = self.post([pdf(f"{i}.pdf") for i in range(6)])
        self.assertEqual(resp.status_code, 202)
        self.assertGreater(peak, 1)
        self.assertEqual(MedicalDocument.objects.count(), 6)


@mock.patch("apps.records.views.resolve_target_awpid_and_dob", return_value=("AWP-T1", None, None))
class BatchDetailViewTests(TestCase):
    """The batch first, then its documents."""
    databases = {"default"}

    def get(self, batch_id):
        request = APIRequestFactory().get(f"/api/v1/records/batches/{batch_id}/")
        force_authenticate(request, user=MockUser({"user_id": 1, "role": "patient", "awpid": "AWP-T1"}))
        return BatchDetailView.as_view()(request, batch_id=batch_id)

    def test_returns_the_batch_counts_and_each_document(self, _resolve):
        identity("AWP-T1")
        batch = DocumentBatch.objects.create(patient=identity("AWP-T1"), total_files=3)
        make_doc(batch=batch, status="completed", document_type="lab_report", by="rules", name="a.pdf")
        make_doc(batch=batch, status="queued", name="b.pdf")
        make_doc(batch=batch, status="review_required", by="rules", name="c.pdf")

        data = self.get(batch.id).data["data"]
        self.assertEqual((data["id"], data["total_files"], data["status"]), (batch.id, 3, "processing"))
        self.assertEqual({k: v for k, v in data["counts"].items() if v},
                         {"completed": 1, "queued": 1, "review_required": 1})
        self.assertEqual([(d["file_name"], d["status"], d["processing_status"], d["doc_type"]) for d in data["documents"]],
                         [("a.pdf", "completed", "completed", "lab_report"),
                          ("b.pdf", "queued", "queued", "not_classified"),
                          ("c.pdf", "review_required", "review_required", "not_classified")])

    def test_a_batch_is_complete_when_every_document_is_in_a_final_state(self, _resolve):
        identity("AWP-T1")
        batch = DocumentBatch.objects.create(patient=identity("AWP-T1"), total_files=3)
        make_doc(batch=batch, status="completed", document_type="imaging_report", by="rules")
        make_doc(batch=batch, status="review_required", by="rules")
        make_doc(batch=batch, status="failed")
        batch.refresh()
        self.assertEqual((batch.processed_files, batch.failed_files, batch.status), (2, 1, "completed_with_errors"))
        self.assertEqual(services.batch_summary(batch)["status"], "completed")

    def test_someone_elses_batch_is_not_found(self, _resolve):
        batch = DocumentBatch.objects.create(patient=identity("AWP-OTHER"), total_files=1)
        self.assertEqual(self.get(batch.id).status_code, 404)


@mock.patch("apps.records.views.start_processing")
@mock.patch("apps.records.services.storage")
@mock.patch("core.storage.put_bytes", side_effect=lambda key, data, mime_type: key)
class UploadForWhomTests(TestCase):
    """"Who is this for?" on the phone sends patient_awpid with the upload. The family link is checked for real here (the
    tests above stub it out): a linked family member's upload is filed under them, anyone else's is refused."""
    databases = {"default"}

    def setUp(self):
        from apps.registry.models import PatientAccount, PatientRelationship
        self.acct = PatientAccount.objects.using("default").create(awpid="AWP-ME", full_name="Me", mobile="9333333331", password="x")
        identity("AWP-ME")
        identity("AWP-KID")
        identity("AWP-STRANGER")
        PatientRelationship.objects.using("default").create(guardian_awpid="AWP-ME", dependent_awpid="AWP-KID", relationship="child")

    def post(self, awpid=None):
        data = {"files": [pdf("a.pdf")], **({"patient_awpid": awpid} if awpid else {})}
        request = APIRequestFactory().post("/api/v1/records/upload/", data, format="multipart")
        force_authenticate(request, user=MockUser({"user_id": self.acct.id, "role": "patient", "awpid": "AWP-ME"}))
        return UploadView.as_view()(request)

    def test_with_no_one_chosen_the_upload_is_the_patients_own(self, put, storage, start):
        self.assertEqual(self.post().status_code, 202)
        self.assertEqual(MedicalDocument.objects.get().patient.awpid, "AWP-ME")

    def test_a_linked_family_member_gets_the_upload(self, put, storage, start):
        self.assertEqual(self.post("AWP-KID").status_code, 202)
        doc = MedicalDocument.objects.get()
        self.assertEqual(doc.patient.awpid, "AWP-KID")
        self.assertIn("AWP-KID", doc.file.name)

    def test_someone_not_linked_to_the_account_is_refused_and_nothing_is_saved(self, put, storage, start):
        resp = self.post("AWP-STRANGER")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(MedicalDocument.objects.count(), 0)
        put.assert_not_called()
        start.assert_not_called()
