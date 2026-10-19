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
