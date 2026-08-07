"""
core/encrypted_fields.py
-------------------------
Field-level encryption at rest, backed by Fernet (symmetric, authenticated).

Usage on a model:
    from core.encrypted_fields import EncryptedTextField, EncryptedCharField
    notes = EncryptedTextField(blank=True)

Key management:
    settings.FIELD_ENCRYPTION_KEY must be a urlsafe-base64 32-byte key
    (generate with `Fernet.generate_key()`). Rotate by keeping the old key
    in FIELD_ENCRYPTION_KEY_FALLBACKS (list) — reads try each key in order,
    writes always use the primary key.

IMPORTANT — this is a utility, not yet applied to any existing populated
column. Retrofitting it onto a column that already has plaintext data
requires a migration that reads-then-rewrites every row under the new
field type, run during a maintenance window, not a routine deploy. See
the production-readiness audit for which fields are recommended first
(OPDEncounter.subjective/objective/assessment/plan, Patient.mobile/email).
"""

from django.conf import settings
from django.db import models


def _get_fernet():
    from cryptography.fernet import Fernet, MultiFernet
    key = getattr(settings, "FIELD_ENCRYPTION_KEY", None)
    if not key:
        raise RuntimeError(
            "FIELD_ENCRYPTION_KEY is not set. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"` "
            "and set it via env var — never hardcode it."
        )
    fallbacks = getattr(settings, "FIELD_ENCRYPTION_KEY_FALLBACKS", [])
    fernets = [Fernet(key.encode() if isinstance(key, str) else key)]
    for fk in fallbacks:
        fernets.append(Fernet(fk.encode() if isinstance(fk, str) else fk))
    return MultiFernet(fernets) if len(fernets) > 1 else fernets[0]


class _EncryptedFieldMixin:
    """Transparently encrypts on write, decrypts on read. Stored as text."""

    def get_prep_value(self, value):
        if value is None or value == "":
            return value
        f = _get_fernet()
        return f.encrypt(str(value).encode()).decode()

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        f = _get_fernet()
        try:
            return f.decrypt(value.encode()).decode()
        except Exception:
            # Not encrypted (e.g. legacy plaintext row pre-migration) — return as-is
            # rather than raising, so a partially-migrated table doesn't 500.
            return value


class EncryptedTextField(_EncryptedFieldMixin, models.TextField):
    pass


class EncryptedCharField(_EncryptedFieldMixin, models.CharField):
    def __init__(self, *args, **kwargs):
        # Ciphertext is longer than plaintext; give room regardless of the
        # logical max_length the field represents.
        kwargs.setdefault("max_length", 500)
        super().__init__(*args, **kwargs)
