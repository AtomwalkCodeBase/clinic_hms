"""The consultation pad link: each consultation has its own token, which says which patient and hospital it is for."""
import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from apps.hospital_patients.consult_pad_views import ConsultPadView, _open_session_for_token
from apps.atomwalk.models import ConsultSession, Patient
from core.testing import ensure_hospital


class ConsultPadTokenTests(TestCase):
    databases = {"default"}

    def setUp(self):
        self.patient = Patient.objects.using("default").create(awpid="AW-PAD", full_name="Pad Patient", gender="F")

    def session(self, hospital_id=1, **fields):
        return ConsultSession.objects.using("default").create(
            patient=self.patient, hospital=ensure_hospital(hospital_id), encounter_id=uuid.uuid4(),
            expires_at=timezone.now() + timedelta(hours=12), **fields)

    def test_every_session_gets_its_own_random_token(self):
        a, b = self.session(), self.session()
        self.assertNotEqual(a.token, b.token)
        self.assertGreaterEqual(len(a.token), 40)

    def test_an_open_session_is_found_by_its_token_with_the_patient(self):
        s = self.session()
        identity, found = _open_session_for_token(s.token)
        self.assertEqual((identity.awpid, found.id), ("AW-PAD", s.id))

    def test_an_unknown_token_is_not_valid(self):
        self.assertEqual(_open_session_for_token("nope"), (None, None))

    def test_a_closed_or_expired_session_still_names_the_patient_but_is_not_writable(self):
        signed = self.session(status=ConsultSession.STATUS_SIGNED)
        identity, found = _open_session_for_token(signed.token)
        self.assertEqual((identity.awpid, found), ("AW-PAD", None))

        stale = self.session()
        ConsultSession.objects.using("default").filter(pk=stale.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(_open_session_for_token(stale.token)[1], None)
        self.assertEqual(ConsultSession.objects.using("default").get(pk=stale.pk).status, ConsultSession.STATUS_EXPIRED)

    def test_two_hospitals_seeing_the_same_patient_at_once_each_keep_their_own_session(self):
        here, there = self.session(hospital_id=1), self.session(hospital_id=2)
        self.assertEqual(_open_session_for_token(here.token)[1].hospital_id, 1)
        self.assertEqual(_open_session_for_token(there.token)[1].hospital_id, 2)

    def test_the_phone_page_reports_whether_a_consultation_is_active(self):
        view = ConsultPadView.as_view()
        open_session = self.session()
        data = view(APIRequestFactory().get("/x/"), token=open_session.token).data["data"]
        self.assertEqual((data["active"], data["session_id"], data["patient_name"]), (True, open_session.id, "Pad Patient"))
        closed = self.session(status=ConsultSession.STATUS_SIGNED)
        self.assertFalse(view(APIRequestFactory().get("/x/"), token=closed.token).data["data"]["active"])
        self.assertEqual(view(APIRequestFactory().get("/x/"), token="nope").status_code, 404)
