"""An upload the patient has not confirmed yet is not shared: not in the doctor's list, not viewable or downloadable by
id, and not in the history another hospital pulls. Once the patient confirms it, it is."""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.patients.records_share_views import _vault_documents
from apps.patients.services import PatientService
from apps.records.tests.helpers import identity, make_doc
from apps.registry.models import RecordsShareRequest

AWPID = "AW-SHARE-W1"


@override_settings(RECORDS_REVIEW_FROM="2000-01-01T00:00:00+00:00")
class WaitingUploadsAreNotSharedTests(TestCase):
    databases = {"default"}

    def setUp(self):
        identity(AWPID)
        self.waiting = make_doc(AWPID, status="completed", document_type="lab_report", by="rules", name="waiting.pdf")
        self.confirmed = make_doc(AWPID, status="completed", document_type="lab_report", by="human", name="confirmed.pdf")
        self.issued = make_doc(AWPID, status="completed", document_type="prescription", by="issued", name="issued.pdf",
                               uploaded_by="staff")
        self.grant = RecordsShareRequest.objects.using("default").create(
            token="tok-wait-1", code="654321", awpid=AWPID, status=RecordsShareRequest.STATUS_APPROVED,
            expires_at=timezone.now() + timedelta(hours=1),
        )

    def test_the_vault_leaves_out_a_waiting_upload(self):
        ids = {d["id"] for d in _vault_documents(AWPID)}
        self.assertEqual(ids, {self.confirmed.id, self.issued.id})

    def test_a_waiting_upload_cannot_be_viewed_by_id(self):
        res = APIClient().get(f"/api/v1/records-share/{self.grant.token}/documents/{self.waiting.id}/view/")
        self.assertEqual(res.status_code, 404)

    def test_a_waiting_upload_cannot_be_requested_for_download(self):
        res = APIClient().post(f"/api/v1/records-share/{self.grant.token}/downloads/", {"doc_id": self.waiting.id}, format="json")
        self.assertEqual(res.status_code, 404)
        self.grant.refresh_from_db()
        self.assertIsNone(self.grant.pending_download_id)

    def test_a_confirmed_upload_can_still_be_requested(self):
        res = APIClient().post(f"/api/v1/records-share/{self.grant.token}/downloads/", {"doc_id": self.confirmed.id}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["data"]["state"], "requested")

    def test_the_hospital_history_leaves_out_a_waiting_upload(self):
        docs = PatientService.get_shared_history(awpid=AWPID)["documents"]
        self.assertEqual({d["id"] for d in docs}, {self.confirmed.id, self.issued.id})

    @override_settings(RECORDS_REVIEW_FROM="")
    def test_with_the_review_step_off_everything_is_shared_as_before(self):
        ids = {d["id"] for d in _vault_documents(AWPID)}
        self.assertEqual(ids, {self.waiting.id, self.confirmed.id, self.issued.id})
