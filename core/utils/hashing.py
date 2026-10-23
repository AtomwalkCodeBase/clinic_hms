"""core/utils/hashing.py"""

import re
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def normalize_mobile(mobile: str) -> str:
    """Normalize a mobile number to <country code><number>, e.g. +91XXXXXXXXXX (settings.DEFAULT_COUNTRY_CODE and MOBILE_NUMBER_LENGTH)."""
    code, length = settings.DEFAULT_COUNTRY_CODE, settings.MOBILE_NUMBER_LENGTH
    code_digits = code.lstrip("+")
    # Strip all non-digit characters except leading +
    cleaned = re.sub(r"[^\d+]", "", mobile.strip())

    # Remove the leading country code or a leading 0
    if cleaned.startswith(code):
        digits = cleaned[len(code):]
    elif cleaned.startswith(code_digits) and len(cleaned) == len(code_digits) + length:
        digits = cleaned[len(code_digits):]
    elif cleaned.startswith("0"):
        digits = cleaned[1:]
    else:
        digits = cleaned

    if len(digits) != length or not digits.isdigit():
        raise ValueError(f"Cannot normalize '{mobile}' to a valid {length}-digit mobile number.")

    return f"{code}{digits}"


def stored_mobile(mobile: str) -> str:
    """The mobile number as it is stored in patient.mobile: the digits only (no country code, spaces or dashes)."""
    return normalize_mobile(mobile)[len(settings.DEFAULT_COUNTRY_CODE):]
