"""
core/storage.py
----------------
S3-backed storage for user-uploaded files (profile photos, hospital logos,
doctor signatures, lab reports, patient-uploaded documents, vaccination
certificates).

Replaces the old convention of storing files as base64 data URIs directly in
a Postgres TextField (StaffUser.photo, PatientAccount.photo, Hospital.logo,
DoctorProfile.digital_signature, LabReport.file_url, and
atomwalk.MedicalDocument / LabResult / ImmunizationRecord.file_data) —
that was fine for a demo but doesn't scale: every row load pulls the full
file bytes through Postgres, backups balloon with binary data, and there's
no CDN/caching in front of any of it.

Every one of those fields now stores an S3 OBJECT KEY (a short string, e.g.
"staff-photos/aw_sunrise_clinic/9f2c1a6e....jpg") instead of the raw base64
payload. The bucket is PRIVATE — files are never served from a plain public
URL — so reading a file back means generating a short-lived presigned URL
via signed_url() at request time, not returning the stored key to the
frontend directly.

Callers should always run the incoming data URI through
core.utils.file_validation.validate_data_uri() FIRST (verifies real magic bytes,
not just the client's claimed mime_type) and pass the verified mime_type
into upload_data_uri() here — this module doesn't re-validate content type.
"""

import base64
import logging
import mimetypes
import posixpath
import re
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible

logger = logging.getLogger(__name__)

_FOLDER_MAX_LEN = 60


def sanitize_folder_name(name: str) -> str:
    """
    Normalize a hospital admin's chosen S3 folder name into a safe key
    segment: lowercase, alphanumeric + hyphens only, no leading/trailing or
    repeated hyphens. Returns "" for a blank/all-invalid input — callers
    treat that the same as "not set" (see hospital_folder() below).
    """
    if not name:
        return ""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug[:_FOLDER_MAX_LEN].rstrip("-")


def hospital_folder(hospital) -> str:
    """The S3 folder segment for this hospital's uploads: its db_name, which is unique and already a safe slug."""
    return hospital.db_name


def identity_slug(*, name: str = "", identifier: str = "") -> str:
    """
    A safe S3 key segment identifying WHO an upload belongs to — e.g.
    identity_slug(name="Riya Sharma", identifier="AWP1029384") ->
    "riya-sharma-awp1029384" — so staff can find "everything for this
    patient/staff member" by browsing or listing-with-prefix in the S3
    console instead of having to open files one by one to check.

    `identifier` should be the durable, unique handle: a patient's AWPID
    for anything patient-owned (MedicalDocument.patient, ImmunizationRecord.patient,
    PatientAccount.awpid, Patient.awpid, LabResult.patient), or a staff
    member's email for staff-owned uploads (StaffUser/DoctorProfile don't
    have an AWPID — they're not patients). `name` is included only to make
    the key human-readable while browsing; the identifier is what's actually
    reliable for lookup, so this still returns something useful if name is
    blank. Returns "" if both are blank — callers treat that as "no
    identity available, key without one" (see upload_data_uri()'s `identity`
    param), never an error.
    """
    parts = " ".join(p for p in (name, identifier) if p)
    return sanitize_folder_name(parts)

# Maps a verified mime_type (see core.utils.file_validation.ALLOWED_MIME_TYPES) to
# the extension used for the stored S3 key — cosmetic only (S3 doesn't care),
# but makes keys human-readable in the AWS console when debugging.
_EXT_BY_MIME = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
}

# Every upload category in the app, keyed by the same short slug every
# call site passes as upload_data_uri()'s `category` argument. This is the
# single source of truth for "what kind of upload is this" — used to name
# both the S3 key and the file_name shown back to users, so a file's
# identity is always driven by WHERE it was uploaded from, never by
# whatever the uploader happened to name it on their own device (a scan
# called "IMG_20240304(2)_final.pdf" or a signature saved as "sig.png"
# tells you nothing and, worse, could collide/leak across categories).
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
    """
    The file name to store/show for an upload — always derived from its
    category (or, when given, the specific item within that category) plus
    who it belongs to, never from the client-supplied original filename.

    Every upload used to collapse to the same generic name per category
    (e.g. every vaccination certificate was "Vaccination Certificate.png",
    indistinguishable from any other patient's or any other vaccine's once
    downloaded outside its S3 folder — the folder path only survives inside
    this app's UI, not in a browser's Downloads folder). Passing `detail`
    (the specific vaccine/test/document name) and `name`/`identifier` (the
    same values passed to identity_slug() for the S3 folder) bakes that
    context into the visible filename itself:
      display_file_name("vaccination-certificate", "image/png",
                         detail="Typhoid Booster", name="Diya Krishnan",
                         identifier="AWPID-20260812-S1CNZSUV")
      -> "Typhoid Booster - Diya Krishnan - AWPID-20260812-S1CNZSUV.png"

    All three are optional and independently omittable — callers with no
    natural per-item detail (hospital logo) or no personal identity to
    attach (also hospital logo) get the original plain "<Category>.<ext>"
    behavior with no signature change needed at existing call sites.
    """
    label = detail.strip() if detail else UPLOAD_CATEGORIES.get(category, category.replace("-", " ").title())
    ext = _EXT_BY_MIME.get(mime_type, "bin")
    who = " - ".join(p for p in (name.strip() if name else "", identifier.strip() if identifier else "") if p)
    base = f"{label} - {who}" if who else label
    # Filesystem-safe — this becomes a browser download filename (see
    # openDataUrlInNewTab / any "download" attribute using file_name), and
    # none of the characters below are legal in a Windows/macOS filename.
    base = re.sub(r'[\\/:*?"<>|]', "-", base)
    return f"{base}.{ext}"


class StorageError(Exception):
    """Raised when file storage isn't configured, or an upload genuinely fails."""


def _storage():
    """The project's default file storage (settings.DEFAULT_FILE_STORAGE): S3 through core.storage_backend.mediaStorage,
    or the media folder when LOCAL_OR_AWS_S3_MEDIA is not "S3". Every helper below goes through it, so a key given to
    one is the same key the models' FileFields use."""
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
    """
    Decode a "data:<mime>;base64,<payload>" string and store it under `prefix` (and `identity`, when given), named after
    `category` — never after the uploader's file name. `mime_type` should be the VERIFIED type from
    core.utils.file_validation.validate_data_uri(). Returns the stored name to keep in the model field, never a URL.
    Raises StorageError if storage isn't configured or the upload fails.
    """
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
    """
    A time-limited link to the stored file. Forgiving: returns "" for a blank key, or when storage isn't configured or
    signing fails, so a missing file renders as "no file" instead of a 500. `download_name` makes the browser save the
    file under that name instead of showing it.
    """
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
