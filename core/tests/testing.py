"""core/tests/testing.py"""

import unittest
from types import SimpleNamespace

from django.conf import settings
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from core.api.authentication import MockUser
from core.db_router import set_hospital_db

HOSPITAL_ALIAS = "hospital_test"
HAS_HOSPITAL_DB = HOSPITAL_ALIAS in settings.DATABASES

requires_hospital_db = unittest.skipUnless(
    HAS_HOSPITAL_DB,
    "needs the hospital_test alias — run with python manage.py test",
)


class HospitalDBMixin:
    """Wires a test case to the atomwalk ("default") and the "hospital_test" alias."""

    databases = {"default", HOSPITAL_ALIAS} if HAS_HOSPITAL_DB else {"default"}
    hospital_alias = HOSPITAL_ALIAS

    def setUp(self):
        super().setUp()
        set_hospital_db(self.hospital_alias)
        self.addCleanup(set_hospital_db, None)

    def call_view(self, view, method, path, *, user_id, role, data=None, hospital_id=1,
                  features=("feat_pharmacy",), view_kwargs=None):
        """Invoke a DRF view the way JWTHospitalMiddleware + JWTHospitalAuthentication would:"""
        factory = APIRequestFactory()
        request = getattr(factory, method)(path, data or {}, format="json")
        user = MockUser({"user_id": user_id, "role": role, "hospital_id": hospital_id})
        user.subscription = SimpleNamespace(**{f: True for f in features})
        force_authenticate(request, user=user)
        request.hospital_db = self.hospital_alias
        request.hospital_id = hospital_id
        return view(request, **(view_kwargs or {}))


class HospitalDBTestCase(HospitalDBMixin, TestCase):
    """Rolled-back-per-test; use for everything except real concurrency."""


class HospitalDBTransactionTestCase(HospitalDBMixin, TransactionTestCase):
    """Commits for real (tables are flushed afterwards); needed when several threads/connections"""


def ensure_hospital(pk):
    """A hospital row with this id (tests that stamp a fact with "hospital 3" need hospital 3 to exist, now that it is a link)."""
    from apps.hospital_master.models import Hospital
    return Hospital.objects.using("default").get_or_create(
        id=int(pk), defaults={"name": f"Hospital {pk}", "hospital_code": f"hospital-{pk}", "db_name": f"hospital_db_{pk}"})[0]


# ── building blocks for tests: a branch with its place, staff in a user group, a patient with its shared record ──

def make_branch(db, name="Main"):
    """A branch, which always offers at least the default department; returns (branch, its default branch_department)."""
    from apps.hospital_setup.branch_utils import ensure_default_place
    from apps.hospital_setup.models import Branch
    branch = Branch.objects.using(db).create(name=name)
    return branch, ensure_default_place(db, branch)


def make_staff(db, role="doctor", *, place=None, **fields):
    """A staff member of a system role (their user group), working at `place` (a branch_department) when given."""
    from apps.hospital_setup.branch_utils import set_primary_place
    from apps.hospital_setup.models import StaffUser
    from apps.hospital_setup.rbac import system_role
    staff = StaffUser.objects.using(db).create(group=system_role(db, role), **fields)
    if place is not None:
        set_primary_place(staff, place, db)
    return staff


def make_patient(db, awpid, *, branch=None, uhid=None, full_name="Test Patient", **fields):
    """A hospital patient and its shared patient record: who they are (name, birth date, gender...) is in the shared record, in `fields`;
    the hospital's own row has the number and consents."""
    from apps.opd.models import HospitalPatient
    from apps.patients.models import Patient
    HospitalPatient_fields = {k: fields.pop(k) for k in ("dpdp_consent_captured", "dpdp_consent_at", "hie_consent_given", "hie_consent_at") if k in fields}
    Patient.objects.using("default").get_or_create(awpid=awpid, defaults={"full_name": full_name, **fields})
    return HospitalPatient.objects.using(db).create(awpid=awpid, uhid=uhid or f"U-{awpid}"[:20], **HospitalPatient_fields)
