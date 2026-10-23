from django.db import IntegrityError, transaction

from apps.hospital_setup.models import Bed, Room
from apps.ipd.models import Admission, AdmissionReferral
from core.tests.testing import HospitalDBTestCase, make_branch, make_patient, make_staff


class OpenAdmissionRulesTests(HospitalDBTestCase):
    def setUp(self):
        super().setUp()
        db = self.hospital_alias
        self.branch, place = make_branch(db)
        self.department = place.department
        self.staff = make_staff(db, "doctor", phone="9000000001", place=place)
        self.room = Room.objects.using(db).create(floor=place.floor, name="W1")
        self.patients = [make_patient(db, f"AWP-I{i}", uhid=f"U-{i}", branch=self.branch, full_name=f"P{i}") for i in (1, 2)]

    def admit(self, patient, number, status="admitted", bed=None):
        db = self.hospital_alias
        referral = AdmissionReferral.objects.using(db).create(
            patient=patient, department=self.department, admission_type="planned", admission_source="walk_in",
            reason_for_admission="r", recommended_by=self.staff)
        with transaction.atomic(using=db):
            return Admission.objects.using(db).create(
                admission_number=number, branch=self.branch, referral=referral, patient=patient, department=self.department,
                admission_type="planned", admission_source="walk_in", ordering_doctor=self.staff, logged_by_staff=self.staff,
                reason_for_admission="r", status=status, bed=bed)

    def test_a_patient_cannot_have_two_open_admissions(self):
        self.admit(self.patients[0], "ADM-1")
        with self.assertRaises(IntegrityError):
            self.admit(self.patients[0], "ADM-2")

    def test_a_patient_can_be_admitted_again_after_discharge(self):
        self.admit(self.patients[0], "ADM-1", status="discharged")
        self.admit(self.patients[0], "ADM-2")

    def test_two_open_admissions_cannot_share_a_bed(self):
        bed = Bed.objects.using(self.hospital_alias).create(room=self.room, bed_number="1")
        self.admit(self.patients[0], "ADM-1", bed=bed)
        with self.assertRaises(IntegrityError):
            self.admit(self.patients[1], "ADM-2", bed=bed)
