"""The doctor-only Internal Note lives on the consult session, not in the patient's documents."""
import uuid
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.opd.views import EncounterInternalNoteView
from apps.records.models import MedicalDocument
from apps.records.tests.helpers import identity
from apps.registry.models import ConsultSession
from core.authentication import MockUser


class InternalNoteViewTests(TestCase):
    databases = {"default"}

    def setUp(self):
        identity("AWP-T1")
        self.enc = uuid.uuid4()
        self.sess = ConsultSession.objects.create(awpid="AWP-T1", tenant_id=3, encounter_id=self.enc,
                                                  note_pdf="patients/AWP-T1/consult-notes/n.pdf")

    def get(self, role="doctor", tenant_id=3, enc=None, **params):
        request = APIRequestFactory().get("/x/", params)
        force_authenticate(request, user=MockUser({"user_id": 1, "role": role}))
        request.tenant_id = tenant_id
        return EncounterInternalNoteView.as_view()(request, pk=enc or self.enc)

    @mock.patch("core.storage.signed_url", return_value="https://s3/signed")
    def test_a_doctor_of_the_hospital_opens_the_note(self, signed):
        resp = self.get()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual((resp.data["data"]["file_data"], resp.data["data"]["mime_type"]), ("https://s3/signed", "application/pdf"))
        signed.assert_called_once_with("patients/AWP-T1/consult-notes/n.pdf", download_name=None)

    @mock.patch("core.storage.signed_url", return_value="https://s3/signed")
    def test_the_download_variant_asks_for_an_attachment(self, signed):
        self.get(download="1")
        self.assertEqual(signed.call_args.kwargs["download_name"], "Handwritten Consultation Note.pdf")

    def test_another_hospital_cannot_open_it(self):
        self.assertEqual(self.get(tenant_id=99).status_code, 404)

    def test_only_a_doctor_can(self):
        for role in ("patient", "nurse", "front_desk"):
            self.assertEqual(self.get(role=role).status_code, 403, role)

    def test_a_visit_without_a_note_has_nothing_to_open(self):
        self.assertEqual(self.get(enc=uuid.uuid4()).status_code, 404)

    def test_the_note_is_never_one_of_the_patients_documents(self):
        self.assertEqual(MedicalDocument.objects.count(), 0)
