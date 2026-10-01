"""
Test settings — development settings plus one throwaway tenant database alias.

The router (core/db_router.py) migrates every tenant app only onto non-default
aliases, so with the stock DATABASES a `TestCase` can never touch a tenant table.
This module adds a single extra alias ("tenant_test") so tenant-app tests can run:

    python manage.py test --settings=atomwalk.settings.test

Tests opt in with core.testing.TenantDBTestCase. Under the normal settings those
tests are skipped, so `python manage.py test` keeps working unchanged.
"""

from .development import *  # noqa: F401,F403

DATABASES = dict(DATABASES)  # noqa: F405
DATABASES["tenant_test"] = {
    **TENANT_DB_CONFIG_TEMPLATE,  # noqa: F405
    "NAME": "aw_tenant_test",
    "TEST": {"NAME": "test_aw_tenant_test"},
}
