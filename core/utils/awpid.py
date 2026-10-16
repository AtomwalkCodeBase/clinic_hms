"""core/utils/awpid.py"""

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
    """Generate a unique AWPID string."""
    date_part = date.today().strftime("%Y%m%d")
    suffix = "".join(secrets.choice(_CHARSET) for _ in range(_SUFFIX_LENGTH))
    return f"AWPID-{date_part}-{suffix}"


def generate_unique_awpid() -> str:
    """Generate an AWPID that is guaranteed to be unique in the atomwalk DB."""
    from apps.patients.models import Patient

    for attempt in range(1, _MAX_RETRIES + 1):
        candidate = generate_awpid()
        if not Patient.objects.filter(awpid=candidate).exists():
            logger.debug("AWPID generated in %d attempt(s): %s", attempt, candidate)
            return candidate

    raise RuntimeError(
        f"Failed to generate a unique AWPID after {_MAX_RETRIES} attempts. "
        "This is extremely unlikely — check for data issues."
    )
