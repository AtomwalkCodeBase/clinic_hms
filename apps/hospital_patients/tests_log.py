import datetime as dt

from apps.hospital_patients.hospital_log import event_for, record_document, record_event
from apps.hospital_patients.models import HospitalDocument, HospitalEvent
from core.tests.testing import HospitalDBTestCase, ensure_hospital, make_branch, make_patient, make_staff, requires_hospital_db


@requires_hospital_db
class HospitalEventTests(HospitalDBTestCase):
    def setUp(self):
        super().setUp()
        self.db = self.hospital_alias
        self.branch, self.place = make_branch(self.db)
        self.doctor = make_staff(self.db, "doctor", phone="9000000091", first_name="Dee", place=self.place)
        self.patient = make_patient(self.db, "AW-LOG-1", uhid="UHID-LOG1", branch=self.branch)

    def events(self, event_type):
        return list(HospitalEvent.objects.using(self.db).filter(event_type=event_type))

    def test_registering_a_patient_logs_a_registration_event(self):
        (event,) = self.events("registration")
        self.assertEqual((event.patient_id, event.is_active), (self.patient.pk, True))

    def test_a_booking_a_signed_consultation_a_prescription_and_a_bill_each_log_one_event(self):
        from apps.billing.models import Invoice
        from apps.opd.models import Appointment, OPDEncounter, Prescription
        appt = Appointment.objects.using(self.db).create(patient=self.patient, doctor=self.doctor, branch_department=self.place, scheduled_date=dt.date.today())
        (booked,) = self.events("appointment")
        self.assertEqual((booked.patient_id, booked.branch_department_id), (self.patient.pk, self.place.pk))
        enc = OPDEncounter.objects.using(self.db).create(appointment=appt)
        self.assertEqual(self.events("consultation"), [])
        enc.sign(using=self.db)
        enc.save(using=self.db)           # saved again after signing: still one consultation event
        (signed,) = self.events("consultation")
        self.assertEqual((signed.patient_id, signed.created_by_id), (self.patient.pk, self.doctor.pk))
        Prescription.objects.using(self.db).create(encounter=enc)
        self.assertEqual(len(self.events("prescription")), 1)
        Invoice.objects.using(self.db).create(patient=self.patient, branch=self.branch, invoice_number="INV-LOG")
        (billed,) = self.events("billing")
        self.assertEqual(billed.patient_id, self.patient.pk)

    def test_an_event_is_found_by_the_patient_the_kind_and_the_time(self):
        first = record_event(self.db, self.patient.pk, "lab")
        later = record_event(self.db, self.patient.pk, "lab")
        later.created_at = first.created_at + dt.timedelta(hours=1)
        later.save(using=self.db, update_fields=["created_at"])
        self.assertEqual(event_for(self.db, self.patient.pk, "lab", first.created_at).pk, first.pk)
        self.assertEqual(event_for(self.db, self.patient.pk, "lab", later.created_at).pk, later.pk)

    def test_an_event_has_one_document_and_a_new_file_replaces_the_old(self):
        event = record_event(self.db, self.patient.pk, "prescription")
        self.assertIsNone(record_document(self.db, event, "a.pdf"))
        self.assertEqual(record_document(self.db, event, "b.pdf"), "a.pdf")
        (document,) = HospitalDocument.objects.using(self.db).filter(event=event)
        self.assertEqual(document.file.name, "b.pdf")
