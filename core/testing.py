"""
core/testing.py
---------------
Shared helpers for tests that need a tenant database.

Use TenantDBTestCase with `--settings=atomwalk.settings.test` (which defines the
"tenant_test" alias). Under any other settings module the test classes are skipped.
"""

import unittest
from types import SimpleNamespace

from django.conf import settings
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from core.authentication import MockUser
from core.db_router import set_tenant_db

TENANT_ALIAS = "tenant_test"
HAS_TENANT_DB = TENANT_ALIAS in settings.DATABASES

requires_tenant_db = unittest.skipUnless(
    HAS_TENANT_DB,
    "needs the tenant_test alias — run with --settings=atomwalk.settings.test",
)


class TenantDBMixin:
    """Wires a test case to the registry ("default") and the "tenant_test" alias."""

    databases = {"default", TENANT_ALIAS} if HAS_TENANT_DB else {"default"}
    tenant_alias = TENANT_ALIAS

    def setUp(self):
        super().setUp()
        set_tenant_db(self.tenant_alias)
        self.addCleanup(set_tenant_db, None)

    def call_view(self, view, method, path, *, user_id, role, data=None, tenant_id=1,
                  features=("feat_pharmacy",), view_kwargs=None):
        """
        Invoke a DRF view the way JWTTenantMiddleware + JWTTenantAuthentication would:
        a MockUser as request.user and tenant_db / tenant_id set on the request.
        """
        factory = APIRequestFactory()
        request = getattr(factory, method)(path, data or {}, format="json")
        user = MockUser({"user_id": user_id, "role": role, "tenant_id": tenant_id})
        user.subscription = SimpleNamespace(**{f: True for f in features})
        force_authenticate(request, user=user)
        request.tenant_db = self.tenant_alias
        request.tenant_id = tenant_id
        return view(request, **(view_kwargs or {}))


class TenantDBTestCase(TenantDBMixin, TestCase):
    """Rolled-back-per-test; use for everything except real concurrency."""


class TenantDBTransactionTestCase(TenantDBMixin, TransactionTestCase):
    """Commits for real (tables are flushed afterwards); needed when several threads/connections
    must see each other's writes, e.g. row-lock tests."""
