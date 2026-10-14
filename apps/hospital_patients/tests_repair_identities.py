"""repair_patient_identities: a hospital patient with no shared identity gets one, and nothing else changes."""
import datetime as dt

from apps.hospital_patients.management.commands.repair_patient_identities import restore_identities
from apps.atomwalk.models import Patient
from core.testing import HospitalDBTestCase, requires_hospital_db
from core.utils.hashing import hash_mobile, normalize_mobile


@requires_hospital_db
class RepairIdentityTests(HospitalDBTestCase):
    def setUp(self):
        super().setUp()
        from apps.org.models import Branch
        from apps.hospital_patients.models import HospitalPatient
        self.branch = Branch.objects.using(self.hospital_alias).create(name="Main")
        self.HospitalPatient = HospitalPatient

    def patient(self, awpid, **fields):
        return self.HospitalPatient.objects.using(self.hospital_alias).create(
            awpid=awpid, uhid=f"U-{awpid}", branch=self.branch, full_name=fields.pop("full_name", "Someone"), **fields)

    def identities(self):
        return Patient.objects.using("default")

    def test_a_report_changes_nothing(self):
        self.patient("AW-LOST")
        self.assertEqual([p.awpid for p in restore_identities(self.hospital_alias)], ["AW-LOST"])
        self.assertFalse(self.identities().filter(awpid="AW-LOST").exists())

    def test_a_missing_identity_is_restored_from_the_hospital_row(self):
        self.patient("AW-ADULT", full_name="Asha Rao", gender="F", mobile="9876543210", date_of_birth=dt.date(1990, 1, 2))
        self.patient("AW-KID", full_name="Kid One", is_dependent=True, mobile="9111111111")
        restore_identities(self.hospital_alias, apply=True)
        adult = self.identities().get(awpid="AW-ADULT")
        self.assertEqual((adult.full_name, adult.gender, adult.date_of_birth, adult.mobile_hash),
                         ("Asha Rao", "F", dt.date(1990, 1, 2), hash_mobile(normalize_mobile("9876543210"))))
        kid = self.identities().get(awpid="AW-KID")
        self.assertEqual((kid.is_dependent, kid.mobile_hash), (True, None))          # a dependent never gets a mobile hash

    def test_it_is_safe_to_run_twice_and_never_touches_an_existing_identity(self):
        self.patient("AW-HAVE", full_name="Hospital Name")
        self.identities().create(awpid="AW-HAVE", full_name="Atomwalk Name")
        self.patient("AW-NEW")
        restore_identities(self.hospital_alias, apply=True)
        self.assertEqual(restore_identities(self.hospital_alias, apply=True), [])
        self.assertEqual(self.identities().get(awpid="AW-HAVE").full_name, "Atomwalk Name")
        self.assertEqual(self.identities().count(), 2)

    def test_a_mobile_already_used_by_someone_else_is_not_reused(self):
        self.identities().create(awpid="AW-OWNER", full_name="Owner", mobile_hash=hash_mobile(normalize_mobile("9000000001")))
        self.patient("AW-DUP", mobile="9000000001")
        restore_identities(self.hospital_alias, apply=True)
        self.assertIsNone(self.identities().get(awpid="AW-DUP").mobile_hash)
