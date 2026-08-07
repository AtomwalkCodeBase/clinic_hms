"""
core/utils/awpid.py
-------------------
AWPID (Atomwalk Patient ID) generator.

AWPID is Atomwalk's own global patient identifier — equivalent to ABHA ID
but platform-native, no government dependency, no ABDM overhead.

Format: AWPID-YYYYMMDD-XXXXXXXX
  e.g.  AWPID-20260731-A3F9K2M1

Design:
  - Date prefix: makes IDs roughly sortable by creation date.
  - 8-char random suffix: 36^8 ≈ 2.8 trillion possible values.
  - Prefix 'AWPID-' is consistent and easily identifiable.
  - Uniqueness guaranteed by retry on collision (extremely rare).
"""

import secrets
import string
import logging
from datetime import date

logger = logging.getLogger(__name__)

# Character set for the random suffix (uppercase alphanumeric, no ambiguous chars)
_CHARSET = string.ascii_uppercase + string.digits
_SUFFIX_LENGTH = 8
_MAX_RETRIES = 10


def generate_awpid() -> str:
    """
    Generate a unique AWPID string.

    Returns:
        A string like 'AWPID-20260731-A3F9K2M1'.

    Note:
        Does NOT guarantee DB-level uniqueness by itself.
        The caller must check for uniqueness in patient_identity before saving.
        Use generate_unique_awpid() for safe creation.
    """
    date_part = date.today().strftime("%Y%m%d")
    suffix = "".join(secrets.choice(_CHARSET) for _ in range(_SUFFIX_LENGTH))
    return f"AWPID-{date_part}-{suffix}"


def generate_unique_awpid() -> str:
    """
    Generate an AWPID that is guaranteed to be unique in the registry DB.

    Retries up to _MAX_RETRIES times if a collision is found.

    Returns:
        A unique AWPID string.

    Raises:
        RuntimeError if unable to generate a unique ID after max retries (extremely unlikely).
    """
    from apps.registry.models import PatientIdentity

    for attempt in range(1, _MAX_RETRIES + 1):
        candidate = generate_awpid()
        if not PatientIdentity.objects.filter(awpid=candidate).exists():
            logger.debug("AWPID generated in %d attempt(s): %s", attempt, candidate)
            return candidate

    raise RuntimeError(
        f"Failed to generate a unique AWPID after {_MAX_RETRIES} attempts. "
        "This is extremely unlikely — check for data issues."
    )
