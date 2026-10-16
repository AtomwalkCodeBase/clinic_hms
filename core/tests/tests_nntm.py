from apps.hospital_setup.models import Branch, NextNumber
from core.tests.testing import HospitalDBTestCase, requires_hospital_db
from core.utils.nntm import get_next_number


@requires_hospital_db
class BranchNumberingTests(HospitalDBTestCase):
    def test_branches_never_produce_the_same_number(self):
        db = self.hospital_alias
        first = Branch.objects.using(db).create(name="Main")
        second = Branch.objects.using(db).create(name="East")
        for b in (first, second):
            NextNumber.objects.using(db).create(branch_id=b.id, entity="uhid", prefix="UHID-")

        self.assertEqual(get_next_number(first.id, "uhid", using=db)[0], "UHID-000001")
        self.assertEqual(get_next_number(second.id, "uhid", using=db)[0], f"UHID-B{second.id}-000001")
