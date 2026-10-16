"""Test settings — development settings plus one throwaway hospital database alias."""

from .development import *  # noqa: F401,F403

DATABASES = dict(DATABASES)  # noqa: F405
DATABASES["hospital_test"] = {
    **HOSPITAL_DB_CONFIG_TEMPLATE,  # noqa: F405
    "NAME": "aw_hospital_test",
    "TEST": {"NAME": "test_aw_hospital_test"},
}

DEFAULT_FILE_STORAGE = "django.core.files.storage.InMemoryStorage"
