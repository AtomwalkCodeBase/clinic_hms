"""
core/file_validation.py
------------------------
Server-side content-type verification for base64 data-URI uploads.

The app accepts file uploads (lab reports, patient documents, profile
photos) as base64 data URIs in JSON bodies (e.g. "data:application/pdf;
base64,JVBERi0x..."), not multipart file uploads. Every one of those upload
endpoints was trusting the client-supplied `mime_type`/data-URI-declared MIME
type at face value with no verification against the actual file bytes — a
client could label anything as "image/png" and have it stored and later
served back to another user's browser with that content-type, or simply
bypass any client-side type filtering entirely.

This checks the real magic bytes of the decoded payload against an allow-list
instead of trusting the label. Deliberately conservative: only the file types
this app actually needs to handle (PDF reports/scans, JPEG/PNG images) are
accepted; anything else is rejected outright rather than best-effort sniffed.
"""

import base64
import binascii

# Magic-byte signatures for the file types this app actually accepts.
# Checked against the first bytes of the DECODED payload, not the client's
# claimed mime_type or the data URI's declared type.
_SIGNATURES = {
    "application/pdf": (b"%PDF",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
}

ALLOWED_MIME_TYPES = tuple(_SIGNATURES.keys())


class FileValidationError(Exception):
    """Raised when a data URI is malformed or its real content doesn't match an allowed type."""


def validate_data_uri(data_uri: str, *, allowed_types=ALLOWED_MIME_TYPES) -> str:
    """
    Parse a "data:<mime>;base64,<payload>" string, decode enough of the
    payload to check its real magic bytes, and return the VERIFIED mime type
    (which may differ from whatever the client declared, if we trust the
    bytes over the label — here we just reject on mismatch instead).

    Raises FileValidationError with a user-facing message on anything
    malformed or not in the allow-list. Callers should catch this and turn
    it into a 400 response via core.response.error().
    """
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
    # decoding the whole payload here would be wasteful for a multi-MB PDF.
    # Slice must be a multiple of 4 chars (base64 block size) before padding,
    # or b64decode raises on otherwise-valid input just because we truncated
    # it mid-block.
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
