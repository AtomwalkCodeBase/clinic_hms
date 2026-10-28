"""core/storage.py"""

import base64
import logging
import re
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from storages.backends.s3boto3 import S3Boto3Storage

logger = logging.getLogger(__name__)

_FOLDER_MAX_LEN = 60


def sanitize_folder_name(name: str) -> str:
    """Normalize a hospital admin's chosen S3 folder name into a safe key"""
    if not name:
        return ""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug[:_FOLDER_MAX_LEN].rstrip("-")


def hospital_folder(hospital) -> str:
    """The S3 folder segment for this hospital's uploads: its db_name, which is unique and already a safe slug."""
    return hospital.db_name


def identity_slug(*, name: str = "", identifier: str = "") -> str:
    """A safe S3 key segment identifying WHO an upload belongs to — e.g."""
    parts = " ".join(p for p in (name, identifier) if p)
    return sanitize_folder_name(parts)

# Maps a verified mime_type (see core.validation.ALLOWED_MIME_TYPES) to
_EXT_BY_MIME = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
}

# Every upload category in the app, keyed by the same short slug every
UPLOAD_CATEGORIES = {
    "staff-photo":             "Staff Photo",
    "doctor-signature":        "Doctor Signature",
    "hospital-logo":           "Hospital Logo",
    "lab-report":              "Lab Report",
    "patient-photo":           "Patient Photo",
    "patient-document":        "Patient Document",
    "vaccination-certificate": "Vaccination Certificate",
    "shared-lab-result":       "Lab Result",
    "consult-note":            "Consultation Note",
    "prescription":            "Prescription",
}


def display_file_name(category: str, mime_type: str, *, detail: str = "", name: str = "", identifier: str = "") -> str:
    """The file name to store/show for an upload — always derived from its"""
    label = detail.strip() if detail else UPLOAD_CATEGORIES.get(category, category.replace("-", " ").title())
    ext = _EXT_BY_MIME.get(mime_type, "bin")
    who = " - ".join(p for p in (name.strip() if name else "", identifier.strip() if identifier else "") if p)
    base = f"{label} - {who}" if who else label
    # Filesystem-safe — this becomes a browser download filename (see
    base = re.sub(r'[\\/:*?"<>|]', "-", base)
    return f"{base}.{ext}"


class StorageError(Exception):
    """Raised when file storage isn't configured, or an upload genuinely fails."""


def _storage():
    """The project's default file storage (settings.DEFAULT_FILE_STORAGE): S3 through core.storage.mediaStorage,"""
    if getattr(settings, "DEFAULT_FILE_STORAGE", "").endswith("mediaStorage") and not settings.AWS_STORAGE_BUCKET_NAME:
        raise StorageError(
            "File storage isn't configured yet — set AWS_S3_BUCKET, AWS_S3_REGION, "
            "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in the environment."
        )
    from django.core.files.storage import storages
    return storages["default"]


def put_bytes(key: str, data: bytes, *, mime_type: str) -> str:
    """Write raw bytes under `key`; returns the name it was stored under."""
    content = ContentFile(data)
    content.content_type = mime_type
    return _storage().save(key, content)


def upload_data_uri(data_uri: str, *, prefix: str, mime_type: str, category: str, identity: str = "") -> str:
    """Decode a "data:<mime>;base64,<payload>" string and store it under `prefix` (and `identity`, when given), named after"""
    try:
        _, b64_payload = data_uri.split(",", 1)
    except ValueError:
        raise StorageError("Malformed file data.")
    try:
        raw = base64.b64decode(b64_payload)
    except Exception as exc:
        raise StorageError("File data is not valid base64.") from exc

    ext = _EXT_BY_MIME.get(mime_type, "bin")
    base = f"{prefix.strip('/')}/{identity}" if identity else prefix.strip('/')
    key = f"{base}/{category}-{uuid.uuid4().hex[:16]}.{ext}"
    try:
        return put_bytes(key, raw, mime_type=mime_type)
    except StorageError:
        raise
    except Exception as exc:
        logger.error("Upload failed for key=%s", key, exc_info=True)
        raise StorageError("Upload to storage failed. Please try again.") from exc


def _attachment_disposition(name: str) -> str:
    """A `Content-Disposition: attachment` value S3 accepts for any title (ASCII fallback plus RFC 6266 filename*)."""
    import unicodedata
    from urllib.parse import quote

    cleaned = re.sub(r'[\r\n"\\/]', " ", name or "").strip() or "download"
    ascii_name = unicodedata.normalize("NFKD", cleaned.replace("—", "-").replace("–", "-"))
    ascii_name = ascii_name.encode("ascii", "ignore").decode("ascii")
    ascii_name = re.sub(r"\s+", " ", ascii_name).strip(" .") or "download"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(cleaned, safe='')}"


def signed_url(key: str, *, expires_in: int = None, download_name: str = None) -> str:
    """A time-limited link to the stored file. Forgiving: returns "" for a blank key, or when storage isn't configured or"""
    key = getattr(key, "name", key)            # a model's FileField value is accepted as well as its path
    if not key:
        return ""
    try:
        storage = _storage()
    except StorageError:
        return ""
    try:
        try:
            kwargs = {"expire": expires_in or settings.AWS_S3_URL_EXPIRY}
            if download_name:
                kwargs["parameters"] = {"ResponseContentDisposition": _attachment_disposition(download_name)}
            return storage.url(key, **kwargs)
        except TypeError:                              # a local storage takes no signing options
            return storage.url(key)
    except Exception:
        logger.error("Signing a link failed for key=%s", key, exc_info=True)
        return ""


def delete(key: str) -> None:
    """Best-effort delete (a replaced photo or logo). Never raises."""
    key = getattr(key, "name", key)
    if not key:
        return
    try:
        _storage().delete(key)
    except Exception:
        logger.warning("Delete failed for key=%s", key, exc_info=True)


def get_bytes(key: str) -> bytes:
    """A stored file's full body. Raises StorageError if storage is unset."""
    storage = _storage()
    with storage.open(key, "rb") as fh:
        return fh.read()


class mediaStorage(S3Boto3Storage):
    """The project's file storage (settings.DEFAULT_FILE_STORAGE): one S3 bucket, every key under settings.S3_KEY_PREFIX."""
    location = settings.S3_KEY_PREFIX
    file_overwrite = False
    default_acl = None

    def get_available_name(self, name, max_length=None):
        return name
