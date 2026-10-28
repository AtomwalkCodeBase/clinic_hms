"""Checks on what comes in from outside: uploaded files (is the content really what it says), mobile numbers and e-mail addresses (do they exist
in the real world), and the one way a mobile number is written down."""

import base64
import binascii
import logging
import re

from django.conf import settings

logger = logging.getLogger(__name__)


# ── Files ────────────────────────────────────────────────────────────────────
# Magic-byte signatures for the file types this app actually accepts.
_SIGNATURES = {
    "application/pdf": (b"%PDF",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
}

ALLOWED_MIME_TYPES = tuple(_SIGNATURES.keys())


class FileValidationError(Exception):
    """Raised when a data URI is malformed or its real content doesn't match an allowed type."""


def validate_data_uri(data_uri: str, *, allowed_types=ALLOWED_MIME_TYPES) -> str:
    """Parse a "data:<mime>;base64,<payload>" string, decode enough of the"""
    if not data_uri or not isinstance(data_uri, str):
        raise FileValidationError("No file data provided.")

    if not data_uri.startswith("data:"):
        raise FileValidationError("File must be a base64 data URI.")

    try:
        header, b64_payload = data_uri.split(",", 1)
    except ValueError:
        raise FileValidationError("Malformed file data.")

    declared_mime = header[5:].split(";")[0].strip().lower() or "application/octet-stream"

    # Only need the first few dozen bytes to check a magic-byte signature —
    head_chunk = b64_payload[:64]
    head_chunk += "=" * (-len(head_chunk) % 4)
    try:
        head_bytes = base64.b64decode(head_chunk, validate=False)
    except (binascii.Error, ValueError):
        raise FileValidationError("File data is not valid base64.")

    if declared_mime not in allowed_types:
        raise FileValidationError(
            f"Unsupported file type '{declared_mime}'. Allowed: {', '.join(allowed_types)}."
        )

    signatures = _SIGNATURES.get(declared_mime, ())
    if signatures and not any(head_bytes.startswith(sig) for sig in signatures):
        raise FileValidationError(
            "The file's actual content doesn't match its declared type. "
            "The upload may be corrupted or mislabeled."
        )

    return declared_mime


def validate_bytes(raw: bytes, *, allowed_types=ALLOWED_MIME_TYPES) -> str:
    """Same magic-byte check as validate_data_uri(), but for raw bytes already in"""
    if not raw:
        raise FileValidationError("Empty file.")
    head = raw[:16]
    for mime, sigs in _SIGNATURES.items():
        if mime in allowed_types and any(head.startswith(s) for s in sigs):
            return mime
    raise FileValidationError(
        f"Unsupported file type. Allowed: {', '.join(allowed_types)}."
    )


# ── Mobile numbers and e-mail addresses ──────────────────────────────────────

def validate_mobile_real(mobile: str, region: str = "IN"):
    """Returns (is_valid: bool, reason: str). reason is "" when valid."""
    try:
        import phonenumbers
        from phonenumbers import NumberParseException, PhoneNumberType
    except ImportError:
        # phonenumbers not installed in this environment — degrade to
        logger.warning("phonenumbers package not installed — skipping real-world mobile validation.")
        return True, ""

    try:
        parsed = phonenumbers.parse(mobile, region)
    except NumberParseException:
        return False, "Enter a valid mobile number."

    if not phonenumbers.is_valid_number(parsed):
        return False, "This doesn't look like a real mobile number."

    number_type = phonenumbers.number_type(parsed)
    if number_type == PhoneNumberType.FIXED_LINE:
        return False, "Enter a mobile number, not a landline."

    return True, ""


def validate_email_domain(email: str, timeout: float = 5.0):
    """Returns (is_valid: bool, reason: str). reason is "" when valid or when"""
    if "@" not in email:
        return False, "Enter a valid email address."
    domain = email.rsplit("@", 1)[-1].strip()
    if not domain:
        return False, "Enter a valid email address."

    try:
        import dns.resolver
    except ImportError:
        logger.warning("dnspython package not installed — skipping email domain validation.")
        return True, ""

    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=timeout)
        if len(answers) == 0:
            return False, "This email domain can't receive mail."
        return True, ""
    except dns.resolver.NXDOMAIN:
        return False, "This email domain doesn't exist."
    except dns.resolver.NoAnswer:
        # No MX record — some small domains route mail via a bare A record
        return False, "This email domain can't receive mail."
    except Exception as exc:
        logger.warning("MX lookup failed for domain=%s: %s — failing open.", domain, exc)
        return True, ""


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
