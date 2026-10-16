"""core/utils/file_validation.py"""

import base64
import binascii

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
