"""
core/utils/hashing.py
---------------------
DPDP Act 2023 compliant hashing utilities.

mobile_hash: SHA-256 of the normalized phone number (+91XXXXXXXXXX format).
We never store plain mobile numbers in the Registry DB — only the hash.
This allows patient lookup by phone without storing the phone number itself.
"""

import hashlib
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


def hash_mobile(mobile: str) -> str:
    """
    Return the SHA-256 hash of a normalized mobile number.

    This is the value stored in patient_identity.mobile_hash.
    Used for patient lookup and deduplication without storing PII.

    Args:
        mobile: Raw mobile number in any supported format.

    Returns:
        64-character hex string (SHA-256 digest).
    """
    normalized = normalize_mobile(mobile)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def verify_mobile(mobile: str, stored_hash: str) -> bool:
    """
    Check if a given mobile number matches a stored hash.

    Args:
        mobile:      Raw mobile number to check.
        stored_hash: The SHA-256 hash stored in patient_identity.mobile_hash.

    Returns:
        True if the mobile matches the hash, False otherwise.
    """
    try:
        computed = hash_mobile(mobile)
        return computed == stored_hash
    except ValueError:
        return False
