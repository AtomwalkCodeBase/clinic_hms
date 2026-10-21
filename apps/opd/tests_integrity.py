from django.db import IntegrityError, transaction

from apps.documents.tests.tests import identity
from apps.hospital_setup.models import Branch
from apps.opd.models import HospitalPatient
from apps.patients.models import PatientRelationship
from core.tests.testing import HospitalDBTestCase


class HospitalPatientTests(HospitalDBTestCase):
    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.using(self.hospital_alias).create(name="Main")

    def patient(self, awpid, uhid, **fields):
        return HospitalPatient.objects.using(self.hospital_alias).create(awpid=awpid, uhid=uhid, branch=self.branch, full_name=awpid, **fields)

    def test_a_dependent_reads_the_guardian_from_the_shared_link(self):
        guardian, child = identity("AWP-G1"), identity("AWP-K1")
        PatientRelationship.objects.using("default").create(guardian=guardian, dependent=child, relationship="child")
        kid = self.patient("AWP-K1", "U-1", is_dependent=True)
        self.assertEqual(kid.guardian_relation, "child")
        self.assertEqual(kid.guardian_awpid, "AWP-G1")

    def test_a_patient_who_is_not_a_dependent_has_no_guardian(self):
        self.assertIsNone(self.patient("AWP-A1", "U-2").guardian_link)

    def test_one_person_cannot_be_registered_twice_in_a_hospital(self):
        self.patient("AWP-A1", "U-3")
        with self.assertRaises(IntegrityError), transaction.atomic(using=self.hospital_alias):
            self.patient("AWP-A1", "U-4")
