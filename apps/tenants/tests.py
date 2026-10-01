"""apps/tenants/tests.py — tenant alias registration and provenance lookup."""

import threading

from django.conf import settings
from django.test import TestCase

from core.db_router import _thread_local, set_tenant_db
from apps.tenants.models import Tenant
from apps.tenants.utils import ensure_tenant_db, resolve_source_tenant_id


class EnsureTenantDbTests(TestCase):
    databases = {"default"}

    def tearDown(self):
        settings.DATABASES.pop("aw_tenant_unit_a", None)
        settings.DATABASES.pop("aw_tenant_unit_b", None)

    def test_registers_an_unknown_alias_from_the_tenant_template(self):
        ensure_tenant_db("aw_tenant_unit_a")
        cfg = settings.DATABASES["aw_tenant_unit_a"]
        self.assertEqual(cfg["NAME"], "aw_tenant_unit_a")
        self.assertEqual(cfg["ENGINE"], "django.db.backends.postgresql")
        # keys Django's DatabaseWrapper reads directly must be present
        for key in ("AUTOCOMMIT", "ATOMIC_REQUESTS", "TIME_ZONE", "OPTIONS", "CONN_MAX_AGE", "TEST"):
            self.assertIn(key, cfg)

    def test_is_idempotent_and_never_replaces_an_existing_alias(self):
        ensure_tenant_db("aw_tenant_unit_a")
        first = settings.DATABASES["aw_tenant_unit_a"]
        ensure_tenant_db("aw_tenant_unit_a")
        self.assertIs(settings.DATABASES["aw_tenant_unit_a"], first)
        registry_cfg = settings.DATABASES["default"]
        ensure_tenant_db("default")
        self.assertIs(settings.DATABASES["default"], registry_cfg)

    def test_concurrent_registration_yields_one_config(self):
        seen = []
        barrier = threading.Barrier(8)

        def worker():
            barrier.wait(timeout=5)
            ensure_tenant_db("aw_tenant_unit_b")
            seen.append(id(settings.DATABASES["aw_tenant_unit_b"]))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        [t.start() for t in threads]
        [t.join(timeout=10) for t in threads]
        self.assertEqual(len(set(seen)), 1)


class ResolveSourceTenantIdTests(TestCase):
    databases = {"default"}

    def tearDown(self):
        if hasattr(_thread_local, "tenant_id"):
            del _thread_local.tenant_id
        set_tenant_db(None)

    def test_looks_the_tenant_up_from_its_db_alias(self):
        t = Tenant.objects.using("default").create(name="H", subdomain="h-res", db_name="aw_tenant_res")
        self.assertEqual(resolve_source_tenant_id("aw_tenant_res"), t.id)

    def test_unknown_or_empty_alias_is_zero(self):
        self.assertEqual(resolve_source_tenant_id("nope"), 0)
        self.assertEqual(resolve_source_tenant_id(None), 0)

    def test_an_explicit_thread_local_id_from_the_seed_commands_wins(self):
        _thread_local.tenant_id = 77
        self.assertEqual(resolve_source_tenant_id("whatever"), 77)
