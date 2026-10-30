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

    def qr(self):
        from apps.opd.views import EncounterConsultSessionView
        with _mock.patch("apps.opd.qr.render_qr_data_uri", return_value="data:image/png;base64,x"):
            return self.call_view(
                EncounterConsultSessionView.as_view(), "post", "/api/v1/opd/encounters/x/consult-session/",
                user_id=self.doctor.pk, role="doctor", hospital_id=self.hospital.pk,
                view_kwargs={"pk": self.enc.pk},
            )

    def test_pressing_the_qr_button_twice_gives_the_same_qr_and_one_session(self):
        from apps.opd.models import ConsultSession
        from apps.patients.models import Patient
        Patient.objects.using("default").get_or_create(awpid="AW-SIGN-1", defaults={"full_name": "Sign Patient"})
        first, second = self.qr(), self.qr()
        self.assertEqual((first.status_code, second.status_code), (200, 200))
        self.assertEqual(first.data["data"]["pad_url"], second.data["data"]["pad_url"])
        self.assertEqual(ConsultSession.objects.using(self.hospital_alias).filter(encounter=self.enc).count(), 1)

    def test_a_signed_encounter_gets_no_qr_and_signing_leaves_its_session_alone(self):
        from apps.opd.models import ConsultSession
        from apps.patients.models import Patient
        Patient.objects.using("default").get_or_create(awpid="AW-SIGN-1", defaults={"full_name": "Sign Patient"})
        token = self.qr().data["data"]["pad_url"].rsplit("/", 1)[1]
        with _mock.patch("core.storage.upload_data_uri", return_value="x.pdf"), _mock.patch("apps.documents.lib_documents._queue_processing"):
            self.assertEqual(self.sign().status_code, 200)
        self.assertEqual(ConsultSession.objects.using(self.hospital_alias).get(encounter=self.enc).token, token)
        self.assertEqual(self.qr().status_code, 400)

    def test_the_visit_history_lists_a_signed_visit_with_its_archived_prescription(self):
        from apps.documents.models import MedicalDocument
        from apps.opd.views import AppointmentHistoryView
        from apps.patients.models import Patient
        ident, _ = Patient.objects.using("default").get_or_create(awpid="AW-SIGN-1", defaults={"full_name": "Sign Patient"})
        doc = MedicalDocument.objects.using("default").create(
            patient=ident, source_type=MedicalDocument.Source.ENCOUNTER_HANDWRITTEN_RX, source_id=self.enc.pk, doc_classification="prescription")
        resp = self.call_view(AppointmentHistoryView.as_view(), "get", "/api/v1/opd/history/", user_id=self.doctor.pk, role="doctor",
                              hospital_id=self.hospital.pk)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["results"][0]["handwritten_prescription_doc_id"], doc.pk)

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


@requires_hospital_db
class AppointmentPlaceTests(HospitalDBTestCase):
    def setUp(self):
        super().setUp()
        from apps.hospital_setup.models import BranchDepartment, Department
        db = self.hospital_alias
        self.branch, self.place = make_branch(db)
        self.doctor = make_staff(db, "doctor", phone="9000000061", place=self.place)
        self.patient = make_patient(db, "AW-PL-1", branch=self.branch)
        self.other = BranchDepartment.objects.using(db).create(
            branch=self.branch, department=Department.objects.using(db).create(name="Cardiology"), floor=self.place.floor)

    def appointment(self, place, **extra):
        from apps.opd.models import Appointment
        return Appointment(patient=self.patient, doctor=self.doctor, branch_department=place, scheduled_date=_dt.date.today(), **extra)

    def test_a_doctor_cannot_be_booked_in_a_department_they_do_not_work_in(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.appointment(self.other).save(using=self.hospital_alias)
        self.appointment(self.place).save(using=self.hospital_alias)

    def test_a_status_update_is_not_rechecked_but_a_move_to_another_department_is(self):
        from django.core.exceptions import ValidationError
        appt = self.appointment(self.place)
        appt.save(using=self.hospital_alias)
        appt.status = appt.STATUS_WAITING
        appt.save(using=self.hospital_alias, update_fields=["status"])
        appt.branch_department = self.other
        with self.assertRaises(ValidationError):
            appt.save(using=self.hospital_alias)

    def test_a_doctor_with_an_assignment_in_two_departments_can_be_booked_in_both(self):
        from apps.hospital_setup.models import StaffBranchAssignment
        db = self.hospital_alias
        StaffBranchAssignment.objects.using(db).filter(staff=self.doctor).update(department=self.place.department)
        StaffBranchAssignment.objects.using(db).create(staff=self.doctor, branch=self.branch, department=self.other.department)
        self.appointment(self.place).save(using=db)
        self.appointment(self.other).save(using=db)


@requires_hospital_db
class PrescriptionItemRouteTests(HospitalDBTestCase):
    def setUp(self):
        super().setUp()
        from apps.hospital_master.models import Hospital
        self.hospital = Hospital.objects.using("default").get_or_create(pk=1, defaults={"name": "H", "hospital_code": "pi-1", "db_name": self.hospital_alias})[0]
        self.doctor = make_staff(self.hospital_alias, "doctor", phone="9000000071")

    def call(self, verb, **kwargs):
        from apps.opd.views import PrescriptionItemView
        return self.call_view(PrescriptionItemView.as_view(), verb, "/x/", user_id=self.doctor.pk, role="doctor", hospital_id=self.hospital.pk, view_kwargs=kwargs)

    def test_deleting_the_item_collection_and_posting_to_one_item_are_405_not_500(self):
        zero = "00000000-0000-0000-0000-000000000000"
        self.assertEqual(self.call("delete", pk=zero).status_code, 405)
        self.assertEqual(self.call("post", pk=zero, item_id=zero).status_code, 405)
