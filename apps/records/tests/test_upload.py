from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.records import services
from apps.records.models import SharedDocument, SweepConfig, UploadBatch
from apps.records.serializers import MAX_FILE_BYTES
from apps.records.views import UploadView
from core.authentication import MockUser

PDF = b"%PDF-1.4\n" + b"x" * 100


def pdf(name="report.pdf", size=None):
    body = PDF if size is None else b"%PDF" + b"x" * (size - 4)
    return SimpleUploadedFile(name, body, content_type="application/pdf")


@mock.patch("apps.patients.portal_views._resolve_target_awpid_and_dob", return_value=("AWP-T1", None, None))
@mock.patch("apps.records.views.extract_document_task")
@mock.patch("apps.records.services.storage")
class UploadViewTests(TestCase):
    databases = {"default"}

    def post(self, files):
        request = APIRequestFactory().post("/api/v1/records/upload/", {"files": files}, format="multipart")
        force_authenticate(request, user=MockUser({"user_id": 1, "role": "patient", "awpid": "AWP-T1"}))
        return UploadView.as_view()(request)

    def test_one_batch_one_document_and_one_task_per_file(self, storage, task, _resolve):
        storage.put_bytes.side_effect = lambda key, data, mime_type: key
        resp = self.post([pdf("a.pdf"), pdf("b.pdf"), pdf("c.pdf")])

        self.assertEqual(resp.status_code, 202)
        self.assertEqual(UploadBatch.objects.count(), 1)
        docs = SharedDocument.objects.filter(batch__isnull=False)
        self.assertEqual(docs.count(), 3)
        self.assertTrue(all(d.processing_status == "queued" and d.awpid == "AWP-T1" for d in docs))
        self.assertEqual(task.delay.call_count, 3)
        self.assertEqual(len(resp.data["data"]["documents"]), 3)

    def test_one_oversize_file_rejects_everything_before_s3(self, storage, task, _resolve):
        resp = self.post([pdf("ok.pdf"), pdf("big.pdf", size=MAX_FILE_BYTES + 1)])

        self.assertEqual(resp.status_code, 400)
        storage.put_bytes.assert_not_called()
        task.delay.assert_not_called()
        self.assertEqual(SharedDocument.objects.count(), 0)

    def test_total_over_200mb_is_rejected(self, storage, task, _resolve):
        with mock.patch("apps.records.serializers.MAX_TOTAL_BYTES", 150):
            resp = self.post([pdf("a.pdf"), pdf("b.pdf")])        # 2 × 109 bytes > 150
        self.assertEqual(resp.status_code, 400)
        storage.put_bytes.assert_not_called()

    def test_not_a_pdf_or_image_is_rejected(self, storage, task, _resolve):
        resp = self.post([pdf("ok.pdf"), SimpleUploadedFile("notes.pdf", b"hello", content_type="application/pdf")])
        self.assertEqual(resp.status_code, 400)
        storage.put_bytes.assert_not_called()

    def test_s3_failure_part_way_removes_the_files_already_sent(self, storage, task, _resolve):
        storage.put_bytes.side_effect = ["patient-documents/AWP-T1/1.pdf", RuntimeError("S3 down")]
        resp = self.post([pdf("a.pdf"), pdf("b.pdf")])

        self.assertEqual(resp.status_code, 503)
        storage.delete.assert_called_once_with("patient-documents/AWP-T1/1.pdf")
        self.assertEqual(UploadBatch.objects.count(), 0)
        task.delay.assert_not_called()

    def test_a_batch_at_the_instant_limit_dispatches_immediately(self, storage, task, _resolve):
        SweepConfig.objects.update_or_create(pk=1, defaults={"instant_max_files": 5})
        storage.put_bytes.side_effect = lambda key, data, mime_type: key
        resp = self.post([pdf(f"{i}.pdf") for i in range(5)])

        self.assertEqual(resp.status_code, 202)
        self.assertEqual(task.delay.call_count, 5)

    def test_a_batch_over_the_instant_limit_is_left_queued_for_the_sweep(self, storage, task, _resolve):
        SweepConfig.objects.update_or_create(pk=1, defaults={"instant_max_files": 5})
        storage.put_bytes.side_effect = lambda key, data, mime_type: key
        resp = self.post([pdf(f"{i}.pdf") for i in range(6)])

        self.assertEqual(resp.status_code, 202)
        docs = SharedDocument.objects.filter(batch__isnull=False)
        self.assertEqual(docs.count(), 6)
        self.assertTrue(all(d.processing_status == "queued" for d in docs))
        task.delay.assert_not_called()


class SafeDeleteTests(TestCase):
    """services._safe_delete() must never delete an object outside this app's own S3 prefix."""

    @mock.patch("apps.records.services.storage")
    def test_refuses_to_delete_a_key_outside_its_own_prefix(self, storage):
        services._safe_delete("lab-reports/some-hospital/report.pdf")
        storage.delete.assert_not_called()

    @mock.patch("apps.records.services.storage")
    def test_deletes_a_key_under_its_own_prefix(self, storage):
        services._safe_delete("patient-documents/AWP-T1/x.pdf")
        storage.delete.assert_called_once_with("patient-documents/AWP-T1/x.pdf")

    @mock.patch("apps.records.services.storage")
    def test_empty_key_is_a_silent_no_op(self, storage):
        services._safe_delete("")
        storage.delete.assert_not_called()
