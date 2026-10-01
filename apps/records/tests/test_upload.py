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
@mock.patch("apps.records.views.dispatch_documents")
@mock.patch("apps.records.services.storage")
class UploadViewTests(TestCase):
    databases = {"default"}

    def setUp(self):
        identity("AWP-T1")

    def post(self, files):
        request = APIRequestFactory().post("/api/v1/records/upload/", {"files": files}, format="multipart")
        force_authenticate(request, user=MockUser({"user_id": 1, "role": "patient", "awpid": "AWP-T1"}))
        return UploadView.as_view()(request)

    def test_every_upload_gets_a_batch_even_for_one_file(self, storage, dispatch, _resolve):
        resp = self.post([pdf("a.pdf")])

        self.assertEqual(resp.status_code, 202)
        batch = DocumentBatch.objects.get()
        self.assertEqual((batch.awpid_id, batch.total_files, resp.data["data"]["batch_id"]), ("AWP-T1", 1, batch.id))
        doc = MedicalDocument.objects.get()
        self.assertEqual((doc.processing_status, doc.awpid_id, doc.original_file_name, doc.batch_id, doc.size),
                         ("queued", "AWP-T1", "a.pdf", batch.id, len(PDF)))
        self.assertRegex(doc.file_path, rf"^patients/AWP-T1/documents/{batch.id}/[0-9a-f]{{32}}\.pdf$")
        self.assertEqual(MedicalDocument.objects.get().status, "queued")
        dispatch.assert_called_once_with(1, ids=[doc.id])

    def test_several_files_share_one_batch_and_one_folder(self, storage, dispatch, _resolve):
        storage.put_bytes.side_effect = lambda path, data, mime_type: path
        resp = self.post([pdf("a.pdf"), pdf("b.pdf"), pdf("c.pdf")])

        self.assertEqual(resp.status_code, 202)
        batch = DocumentBatch.objects.get()
        self.assertEqual(batch.total_files, 3)
        docs = MedicalDocument.objects.filter(batch=batch)
        self.assertEqual(docs.count(), 3)
        self.assertTrue(all(d.file_path.startswith(f"patients/AWP-T1/documents/{batch.id}/") for d in docs))
        self.assertEqual(len(resp.data["data"]["documents"]), 3)
        dispatch.assert_called_once()

    def test_a_big_batch_is_left_queued_for_the_dispatcher(self, storage, dispatch, _resolve):
        storage.put_bytes.side_effect = lambda path, data, mime_type: path
        with mock.patch("apps.records.views.SweepConfig.current", return_value=mock.Mock(instant_max_files=2)):
            self.post([pdf("a.pdf"), pdf("b.pdf"), pdf("c.pdf")])
        dispatch.assert_not_called()
        self.assertEqual(MedicalDocument.objects.filter(status="queued").count(), 3)

    def test_the_content_is_not_checked_at_the_door(self, storage, dispatch, _resolve):
        """A bad file is accepted and fails later in the extraction job, so it never blocks the others."""
        storage.put_bytes.side_effect = lambda path, data, mime_type: path
        resp = self.post([pdf("ok.pdf"), SimpleUploadedFile("notes.pdf", b"hello", content_type="application/pdf")])
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(MedicalDocument.objects.count(), 2)

    def test_an_unknown_extension_is_stored_as_bin_and_never_trusted_as_a_content_type(self, storage, dispatch, _resolve):
        storage.put_bytes.side_effect = lambda path, data, mime_type: path
        self.post([SimpleUploadedFile("evil.html", b"<html>", content_type="text/html")])
        path, _data = storage.put_bytes.call_args.args
        self.assertTrue(path.endswith(".bin"))
        self.assertEqual(storage.put_bytes.call_args.kwargs["mime_type"], "application/octet-stream")

    def test_one_oversize_file_rejects_everything_before_s3(self, storage, dispatch, _resolve):
        with mock.patch("apps.records.serializers.MAX_FILE_BYTES", 150):
            resp = self.post([pdf("ok.pdf"), pdf("big.pdf", size=200)])

        self.assertEqual(resp.status_code, 400)
        storage.put_bytes.assert_not_called()
        dispatch.assert_not_called()
        self.assertEqual(MedicalDocument.objects.count(), 0)

    def test_an_empty_file_rejects_everything_before_s3(self, storage, dispatch, _resolve):
        resp = self.post([pdf("ok.pdf"), SimpleUploadedFile("empty.pdf", b"", content_type="application/pdf")])
        self.assertEqual(resp.status_code, 400)
        self.assertIn("empty", str(resp.data))
        storage.put_bytes.assert_not_called()
        self.assertEqual(MedicalDocument.objects.count(), 0)

    def test_total_over_250mb_is_rejected(self, storage, dispatch, _resolve):
        with mock.patch("apps.records.serializers.MAX_TOTAL_BYTES", 150):
            resp = self.post([pdf("a.pdf"), pdf("b.pdf")])        # 2 × 109 bytes > 150
        self.assertEqual(resp.status_code, 400)
        storage.put_bytes.assert_not_called()

    def test_more_than_50_files_is_rejected(self, storage, dispatch, _resolve):
        with mock.patch("apps.records.serializers.MAX_FILES", 2):
            resp = self.post([pdf("a.pdf"), pdf("b.pdf"), pdf("c.pdf")])
        self.assertEqual(resp.status_code, 400)
        storage.put_bytes.assert_not_called()
        self.assertEqual(MedicalDocument.objects.count(), 0)

    def test_an_s3_failure_part_way_saves_nothing_and_deletes_what_was_sent(self, storage, dispatch, _resolve):
        storage.put_bytes.side_effect = [None, RuntimeError("S3 down")]
        resp = self.post([pdf("a.pdf"), pdf("b.pdf")])

        self.assertEqual(resp.status_code, 503)
        self.assertEqual((MedicalDocument.objects.count(), DocumentBatch.objects.count()), (0, 0))
        deleted = [c.args[0] for c in storage.delete.call_args_list]
        self.assertEqual(len(deleted), 2)                    # both paths are cleaned up, sent or not
        self.assertTrue(all(p.startswith("patients/AWP-T1/documents/") for p in deleted))
        dispatch.assert_not_called()

    def test_files_are_sent_to_s3_at_the_same_time(self, storage, dispatch, _resolve):
        import threading
        import time
        active, peak, lock = 0, 0, threading.Lock()

        def slow_put(path, data, mime_type):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.05)
            with lock:
                active -= 1

        storage.put_bytes.side_effect = slow_put
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
        batch = DocumentBatch.objects.create(awpid_id="AWP-T1", total_files=3)
        make_doc(batch=batch, status="completed", doc_type="lab_report", by="system", name="a.pdf")
        make_doc(batch=batch, status="queued", name="b.pdf")
        make_doc(batch=batch, status="rejected", name="c.pdf")

        data = self.get(batch.id).data["data"]
        self.assertEqual((data["id"], data["total_files"], data["status"]), (batch.id, 3, "processing"))
        self.assertEqual({k: v for k, v in data["counts"].items() if v},
                         {"completed": 1, "queued": 1, "rejected": 1})
        self.assertEqual([(d["file_name"], d["status"], d["doc_type"]) for d in data["documents"]],
                         [("a.pdf", "completed", "lab_report"), ("b.pdf", "queued", ""), ("c.pdf", "rejected", "")])

    def test_a_batch_is_complete_when_every_document_is_in_a_final_state(self, _resolve):
        identity("AWP-T1")
        batch = DocumentBatch.objects.create(awpid_id="AWP-T1", total_files=2)
        make_doc(batch=batch, status="completed", doc_type="scan", by="system")
        make_doc(batch=batch, status="failed")
        batch.refresh()
        self.assertEqual(services.batch_summary(batch)["status"], "completed")

    def test_someone_elses_batch_is_not_found(self, _resolve):
        identity("AWP-OTHER")
        batch = DocumentBatch.objects.create(awpid_id="AWP-OTHER", total_files=1)
        self.assertEqual(self.get(batch.id).status_code, 404)
