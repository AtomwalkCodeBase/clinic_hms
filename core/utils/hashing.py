"""
core/utils/hashing.py
---------------------
DPDP Act 2023 compliant hashing utilities.

patient.mobile: the 10-digit mobile number, stored as is (see stored_mobile).
"""

import re
import logging

logger = logging.getLogger(__name__)

# Country code to prepend if not already present
DEFAULT_COUNTRY_CODE = "+91"


def normalize_mobile(mobile: str) -> str:
    """
    Normalize a mobile number to +91XXXXXXXXXX format.

    Accepts: '9876543210', '09876543210', '+919876543210', '919876543210'
    Returns: '+919876543210'

    Raises:
        ValueError if the number cannot be normalized to 10 digits.
    """
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
    """
    The mobile number as it is stored in patient.mobile: the 10 digits only (no +91, spaces or dashes).

    Args:
        mobile: Raw mobile number in any supported format.

    Raises:
        ValueError if the number is not a valid 10-digit mobile number.
    """
    return normalize_mobile(mobile)[len(DEFAULT_COUNTRY_CODE):]
