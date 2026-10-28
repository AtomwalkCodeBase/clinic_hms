from django.db import IntegrityError, transaction

from apps.documents.tests.tests import identity
from apps.patients.models import Patient, PatientRelationship
from core.tests.testing import HospitalDBTestCase, make_branch, make_patient


class HospitalPatientTests(HospitalDBTestCase):
    def setUp(self):
        super().setUp()
        self.branch, _place = make_branch(self.hospital_alias)

    def patient(self, awpid, uhid, **fields):
        return make_patient(self.hospital_alias, awpid, uhid=uhid, branch=self.branch, full_name=awpid, **fields)

    def test_a_dependent_reads_the_guardian_from_the_shared_link(self):
        guardian, child = identity("AWP-G1"), identity("AWP-K1")
        Patient.objects.using("default").filter(pk=child.pk).update(is_dependent=True)
        PatientRelationship.objects.using("default").create(guardian=guardian, dependent=child, relationship="child")
        kid = self.patient("AWP-K1", "U-1")
        self.assertEqual(kid.get_patient_details()["guardian_relation"], "child")
        self.assertEqual(kid.get_patient_details()["guardian_awpid"], "AWP-G1")

    def test_a_patient_who_is_not_a_dependent_has_no_guardian(self):
        self.assertEqual(self.patient("AWP-A1", "U-2").get_patient_details()["guardian_awpid"], "")

    def test_one_person_cannot_be_registered_twice_in_a_hospital(self):
        self.patient("AWP-A1", "U-3")
        with self.assertRaises(IntegrityError), transaction.atomic(using=self.hospital_alias):
            self.patient("AWP-A1", "U-4")
