"""core/utils/hashing.py"""

import re
import logging

logger = logging.getLogger(__name__)

# Country code to prepend if not already present
DEFAULT_COUNTRY_CODE = "+91"


def normalize_mobile(mobile: str) -> str:
    """Normalize a mobile number to +91XXXXXXXXXX format."""
    # Strip all non-digit characters except leading +
    cleaned = re.sub(r"[^\d+]", "", mobile.strip())

    # Remove leading +91 or 91 or 0
    if cleaned.startswith("+91"):
        digits = cleaned[3:]
    elif cleaned.startswith("91") and len(cleaned) == 12:
        digits = cleaned[2:]
    elif cleaned.startswith("0"):
        digits = cleaned[1:]
    else:
        digits = cleaned

    if len(digits) != 10 or not digits.isdigit():
        raise ValueError(
            f"Cannot normalize '{mobile}' to a valid 10-digit Indian mobile number."
        )

    return f"{DEFAULT_COUNTRY_CODE}{digits}"


def stored_mobile(mobile: str) -> str:
    """The mobile number as it is stored in patient.mobile: the 10 digits only (no +91, spaces or dashes)."""
    return normalize_mobile(mobile)[len(DEFAULT_COUNTRY_CODE):]
