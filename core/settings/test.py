"""
Test settings — development settings plus one throwaway hospital database alias.

The router (core/db_router.py) migrates every hospital app only onto non-default
aliases, so with the stock DATABASES a `TestCase` can never touch a hospital table.
This module adds a single extra alias ("hospital_test") so hospital-app tests can run:

    python manage.py test --settings=core.settings.test

Tests opt in with core.tests.testing.HospitalDBTestCase. Under the normal settings those
tests are skipped, so `python manage.py test` keeps working unchanged.
"""

from .development import *  # noqa: F401,F403

DATABASES = dict(DATABASES)  # noqa: F405
DATABASES["hospital_test"] = {
    **HOSPITAL_DB_CONFIG_TEMPLATE,  # noqa: F405
    "NAME": "aw_hospital_test",
    "TEST": {"NAME": "test_aw_hospital_test"},
}

DEFAULT_FILE_STORAGE = "django.core.files.storage.InMemoryStorage"
