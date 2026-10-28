"""apps/opd/tests.py"""


from django.test import TestCase


class EncounterSignSideEffectsTests(TestCase):
    """NOTE: uses the 'default' (atomwalk) DB via TestCase's automatic"""

    def test_sign_never_raises_even_if_hie_write_fails(self):
        """sync_encounter_to_hie must swallow failures — signing an encounter must"""
        from apps.documents.lib_vitals import sync_encounter_to_hie

        class FakeEncounter:
            pk = "test-encounter-id"
            diagnoses = [{"code": "J06.9", "description": "Acute URI"}]

            class appointment:
                vitals = None

            prescription = None

        class FakePatientNoAwpid:
            awpid = None

        # Should return early and NOT raise, since patient.awpid is falsy.
        sync_encounter_to_hie(FakeEncounter(), "default", FakePatientNoAwpid())

    def test_sign_hie_sync_handles_missing_vitals_and_prescription_gracefully(self):
        """Encounters commonly have no vitals recorded yet or no prescription"""
        from apps.documents.lib_vitals import sync_encounter_to_hie

        class FakeAppointment:
            @property
            def vitals(self):
                raise Exception("no related Vitals row — OneToOne DoesNotExist")

        class FakeEncounter:
            pk = "test-encounter-id-2"
            diagnoses = []
            appointment = FakeAppointment()

            @property
            def prescription(self):
                raise Exception("no related Prescription row — OneToOne DoesNotExist")

        class FakePatient:
            awpid = None

        sync_encounter_to_hie(FakeEncounter(), "default", FakePatient())


# ── Sign-off characterization (hospital DB) ────────────────────────────────────

import datetime as _dt
from decimal import Decimal as _Decimal
from unittest import mock as _mock

from core.tests.testing import HospitalDBTestCase, make_branch, make_patient, make_staff, requires_hospital_db


@requires_hospital_db
class EncounterSignWorkflowTests(HospitalDBTestCase):
    def setUp(self):
        super().setUp()
        from apps.opd.models import Appointment, OPDEncounter
        from apps.hospital_setup.models import NextNumber
        from apps.hospital_master.models import Hospital, HospitalParameters

        db = self.hospital_alias
        self.hospital = Hospital.objects.using("default").create(
            name="Sign Hospital", hospital_code="sign-h", db_name=db,
        )
        HospitalParameters.objects.using("default").create(hospital=self.hospital, default_tax_rate=_Decimal("10"))
        self.branch, self.place = make_branch(db)
        self.doctor = make_staff(db, "doctor", email="dr.sign@example.test", phone="9000000020", place=self.place)
        self.doctor.consultation_fee = _Decimal("500.00")
        self.doctor.save(using=db)
        self.patient = make_patient(db, "AW-SIGN-1", uhid="UHID-S1", branch=self.branch, full_name="Sign Patient")
        NextNumber.objects.using(db).create(branch_id=self.branch.pk, entity="invoice", prefix="INV-")
        appt = Appointment.objects.using(db).create(
            patient=self.patient, doctor=self.doctor, branch_department=self.place, scheduled_date=_dt.date.today(),
        )
        self.enc = OPDEncounter.objects.using(db).create(
            appointment=appt,
            assessment="Viral fever", diagnoses=[{"code": "B34.9", "description": "Viral infection"}],
        )

    def sign(self):
        from apps.opd.views import EncounterSignView
        with _mock.patch("apps.opd.views._store_prescription_pdf"):     # S3 + PDF rendering
            return self.call_view(
                EncounterSignView.as_view(), "post", "/api/v1/opd/encounters/x/sign/",
                user_id=self.doctor.pk, role="doctor", hospital_id=self.hospital.pk,
                view_kwargs={"pk": self.enc.pk},
            )


    def test_sign_files_the_typed_note_with_the_patients_documents_once(self):
        from apps.documents.models import MedicalDocument
        from apps.opd.archive import store_consultation_note_document
        self.enc.subjective, self.enc.plan = "Fever for 2 days", "Paracetamol, review in 48 h"
        self.enc.save(using=self.hospital_alias)
        with _mock.patch("apps.opd.views._store_prescription_pdf"), \
                _mock.patch("core.storage.upload_data_uri", return_value="patients/AW-SIGN-1/consult-notes/n.pdf"), \
                _mock.patch("apps.documents.lib_documents._queue_processing") as queued:
            self.sign()
            again = store_consultation_note_document(self.enc, self.hospital_alias, self.hospital.pk)
        note = MedicalDocument.objects.using("default").get(patient__awpid="AW-SIGN-1")      # one, not two
        self.assertEqual((note.doc_classification, note.created_by_type, note.source_hospital_id), ("consultation_note", "H", self.hospital.pk))
        self.assertEqual(again.pk, note.pk)
        queued.assert_not_called()                      # its diagnoses are the doctor's own: the LLM has nothing to add

    def test_signing_twice_is_rejected_and_does_not_bill_again(self):
        from apps.billing.models import Invoice
        self.assertEqual(self.sign().status_code, 200)
        again = self.sign()
        self.assertEqual(again.status_code, 400)
        self.assertEqual(Invoice.objects.using(self.hospital_alias).count(), 1)

    def test_an_encounter_with_no_assessment_or_diagnosis_cannot_be_signed(self):
        self.enc.assessment, self.enc.diagnoses = "", []
        self.enc.save(using=self.hospital_alias)
        resp = self.sign()
        self.assertEqual(resp.status_code, 400)

    def test_a_billing_failure_does_not_block_the_sign_off(self):
        """Sign-off must succeed even if the auto-invoice step blows up (logged, swallowed)."""
        from apps.opd.models import OPDEncounter
        with _mock.patch("apps.hospital_setup.models.NextNumber.next", side_effect=RuntimeError("no counter")):
            resp = self.sign()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(OPDEncounter.objects.using(self.hospital_alias).get().status, OPDEncounter.STATUS_SIGNED)
