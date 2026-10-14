"""
apps/atomwalk/tests.py
----------------------
Provenance of the hospital -> atomwalk write-through: every mirrored row must carry the
atomwalk id of the hospital that wrote it (`source_hospital_id`).

Regression: opd.sync_encounter_to_hie, lab/views attach-document, lab/signals and patients/signals
read `_thread_local.hospital_id`, which core.middleware never sets, so every live request
stamped 0. Needs the hospital_test alias:
  python manage.py test apps.atomwalk --settings=atomwalk.settings.test   (skipped otherwise)
"""

import base64
import datetime
import uuid
from types import SimpleNamespace
from unittest import mock

from django.utils import timezone

from core.testing import HospitalDBTestCase, ensure_hospital, requires_hospital_db

from apps.lab.models import LabReport, LabRequest, LabTest
from apps.lab.views import LabRequestAttachDocumentView
from apps.opd.models import Appointment, OPDEncounter
from apps.atomwalk.hie import sync_encounter_to_hie
from apps.org.models import Branch, StaffUser
from apps.hospital_patients.models import Allergy, HospitalPatient
from apps.atomwalk.models import MedicalDocument
from apps.atomwalk.models import ClinicalEvent, LabResult, Patient, SharedAllergy
from apps.hospitals.models import Hospital


def _hospital(db_name, subdomain, name):
    return Hospital.objects.using("default").create(name=name, subdomain=subdomain, db_name=db_name)


class ProvenanceFixtureMixin:
    def make_fixture(self):
        db = self.hospital_alias
        self.hospital = _hospital(db, "hospital-test", "Test Hospital")
        self.branch = Branch.objects.using(db).create(name="Main")
        self.doctor = StaffUser.objects.using(db).create(
            email="dr@example.test", role="doctor", phone="9000000010", branch=self.branch,
        )
        self.patient = HospitalPatient.objects.using(db).create(
            awpid="AW-PROV-1", uhid="UHID-P1", branch=self.branch, full_name="Prov Patient",
        )
        Patient.objects.using("default").get_or_create(awpid="AW-PROV-1", defaults={"full_name": "Prov Patient"})


def _fake_encounter():
    """Only what sync_encounter_to_hie reads: no vitals, no prescription."""
    class NoRx:
        def __getattr__(self, name):
            raise AttributeError(name)

    enc = NoRx()
    enc.id = "enc-1"
    enc.diagnoses = [{"code": "J06.9", "description": "Acute URI"}]
    enc.appointment = SimpleNamespace(vitals=None)
    return enc


@requires_hospital_db
class SyncToHieTests(ProvenanceFixtureMixin, HospitalDBTestCase):
    def test_uses_the_hospital_id_it_is_given(self):
        self.make_fixture()
        sync_encounter_to_hie(_fake_encounter(), self.hospital_alias, self.patient, hospital_id=self.hospital.id)
        self.assertEqual(ClinicalEvent.objects.using("default").get().source_hospital_id, self.hospital.id)

    def test_resolves_the_hospital_from_the_db_alias_when_not_given(self):
        self.make_fixture()
        sync_encounter_to_hie(_fake_encounter(), self.hospital_alias, self.patient)
        self.assertEqual(ClinicalEvent.objects.using("default").get().source_hospital_id, self.hospital.id)

    def test_two_hospitals_do_not_overwrite_each_others_rows(self):
        """With both stamped 0 the update_or_create key (awpid, hospital, ICD code) collapsed to one row."""
        self.make_fixture()
        ensure_hospital(11)
        ensure_hospital(22)
        sync_encounter_to_hie(_fake_encounter(), self.hospital_alias, self.patient, hospital_id=11)
        sync_encounter_to_hie(_fake_encounter(), self.hospital_alias, self.patient, hospital_id=22)
        rows = ClinicalEvent.objects.using("default").order_by("source_hospital_id")
        self.assertEqual([r.source_hospital_id for r in rows], [11, 22])


@requires_hospital_db
class AllergySignalTests(ProvenanceFixtureMixin, HospitalDBTestCase):
    def test_shared_allergy_carries_the_hospital_id(self):
        self.make_fixture()
        Allergy.objects.using(self.hospital_alias).create(patient=self.patient, substance="Penicillin")
        self.assertEqual(SharedAllergy.objects.using("default").get().source_hospital_id, self.hospital.id)


@requires_hospital_db
class LabHospitalIdTests(ProvenanceFixtureMixin, HospitalDBTestCase):
    def make_lab_request(self):
        db = self.hospital_alias
        test = LabTest.objects.using(db).create(name="CBC")
        doctor_uuid = uuid.uuid4()
        appt = Appointment.objects.using(db).create(
            patient_id=self.patient.uuid, patient_awpid=self.patient.awpid, doctor_user_id=doctor_uuid,
            doctor_name="Dr Test", scheduled_date=datetime.date.today(),
        )
        enc = OPDEncounter.objects.using(db).create(
            appointment=appt, patient_id=self.patient.uuid, doctor_user_id=doctor_uuid,
        )
        return LabRequest.objects.using(db).create(
            patient=self.patient, encounter=enc, test=test, requested_by=self.doctor, branch=self.branch,
        )

    def test_delivered_report_mirrors_carry_the_hospital_id(self):
        self.make_fixture()
        req = self.make_lab_request()
        with mock.patch("apps.lab.archive.store_lab_report_document") as archive:
            LabReport.objects.using(self.hospital_alias).create(
                request=req, patient=self.patient, report_number="LR-1",
                status="delivered", delivered_at=timezone.now(), result_summary="ok",
            )
        self.assertEqual(LabResult.objects.using("default").get().source_hospital_id, self.hospital.id)
        self.assertEqual(archive.call_args.args[2], self.hospital.id)   # the vault-mirror gets it too

    def test_attach_document_view_stamps_the_request_hospital(self):
        self.make_fixture()
        Patient.objects.using("default").get_or_create(awpid=self.patient.awpid, defaults={"full_name": "Prov"})
        req = self.make_lab_request()
        pdf = "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4\n%test\n").decode()
        with mock.patch("core.storage.upload_data_uri", return_value="patient-documents/x.pdf"):
            resp = self.call_view(
                LabRequestAttachDocumentView.as_view(), "post", "/api/v1/lab/requests/1/attach-document/",
                user_id=self.doctor.id, role="lab_tech", data={"file_data": pdf, "title": "Outside CBC"},
                hospital_id=self.hospital.id, features=("feat_lab",), view_kwargs={"pk": req.pk},
            )
        self.assertLess(resp.status_code, 300, resp.data)
        doc = MedicalDocument.objects.using("default").get(source_type="lab_request")
        self.assertEqual(doc.source_hospital_id, self.hospital.id)
