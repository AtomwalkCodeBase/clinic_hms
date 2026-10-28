"""apps/hospital_setup/tests_numbering.py — NextNumber counters and the audit-log writer."""
from django.test import TestCase

from apps.hospital_setup.models import Branch, NextNumber
from core.tests.testing import HospitalDBTestCase, requires_hospital_db


@requires_hospital_db
class BranchNumberingTests(HospitalDBTestCase):
    def test_branches_never_produce_the_same_number(self):
        db = self.hospital_alias
        first = Branch.objects.using(db).create(name="Main")
        second = Branch.objects.using(db).create(name="East")
        for b in (first, second):
            NextNumber.objects.using(db).create(branch_id=b.pk, entity="uhid", prefix="UHID-")

        self.assertEqual(NextNumber.next(first.pk, "uhid", db)[0], "UHID-000001")
        self.assertEqual(NextNumber.next(second.pk, "uhid", db)[0], f"UHID-B{second.pk}-000001")


class AuditLogHelperTests(TestCase):
    def test_log_action_never_raises_on_bad_db(self):
        """Auditing must never break the request it's auditing. Pointing at a"""
        from apps.hospital_setup.compliance_services import log_action
        try:
            log_action(None, "this-db-alias-does-not-exist", action="test.noop")
        except Exception as exc:  # noqa: BLE001 — this is exactly what we're asserting against
            self.fail(f"log_action raised instead of swallowing the error: {exc}")
