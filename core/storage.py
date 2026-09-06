"""
core/storage.py
----------------
S3-backed storage for user-uploaded files (profile photos, hospital logos,
doctor signatures, lab reports, patient-uploaded documents, vaccination
certificates).

Replaces the old convention of storing files as base64 data URIs directly in
a Postgres TextField (StaffUser.photo, PatientAccount.photo, Tenant.logo,
DoctorProfile.digital_signature, LabReport.file_url, and
registry.SharedDocument / SharedLabResult / SharedVaccination.file_data) —
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
core.file_validation.validate_data_uri() FIRST (verifies real magic bytes,
not just the client's claimed mime_type) and pass the verified mime_type
into upload_data_uri() here — this module doesn't re-validate content type.
"""

import base64
import logging
import re
import uuid

from django.conf import settings

logger = logging.getLogger(__name__)

_FOLDER_MAX_LEN = 60


def sanitize_folder_name(name: str) -> str:
    """
    Normalize a hospital admin's chosen S3 folder name into a safe key
    segment: lowercase, alphanumeric + hyphens only, no leading/trailing or
    repeated hyphens. Returns "" for a blank/all-invalid input — callers
    treat that the same as "not set" (see tenant_folder() below).
    """
    if not name:
        return ""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug[:_FOLDER_MAX_LEN].rstrip("-")


def tenant_folder(tenant) -> str:
    """
    The S3 folder segment to use for this tenant's uploads — their own
    chosen Tenant.storage_folder (hospital admin editable via
    /api/v1/org/settings/) if they've set one, otherwise the auto-generated
    db_name. This is the ONE place that fallback is resolved, so every
    upload call site (staff photos, doctor signatures, hospital logo, lab
    reports) picks up a folder rename automatically instead of needing to
    be updated one by one.

    Takes the Tenant model instance, not just its id/db_name, since
    storage_folder already went through sanitize_folder_name() at write
    time (see TenantSettingsView.patch()) — no re-sanitizing needed here.
    """
    return tenant.storage_folder or tenant.db_name


def identity_slug(*, name: str = "", identifier: str = "") -> str:
    """
    A safe S3 key segment identifying WHO an upload belongs to — e.g.
    identity_slug(name="Riya Sharma", identifier="AWP1029384") ->
    "riya-sharma-awp1029384" — so staff can find "everything for this
    patient/staff member" by browsing or listing-with-prefix in the S3
    console instead of having to open files one by one to check.

    `identifier` should be the durable, unique handle: a patient's AWPID
    for anything patient-owned (SharedDocument.awpid, SharedVaccination.awpid,
    PatientAccount.awpid, Patient.awpid, SharedLabResult.awpid), or a staff
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

# Maps a verified mime_type (see core.file_validation.ALLOWED_MIME_TYPES) to
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
    """Raised when S3 isn't configured, or an upload/delete genuinely fails."""


def _client():
    if not settings.AWS_S3_BUCKET:
        raise StorageError(
            "File storage isn't configured yet — set AWS_S3_BUCKET, AWS_S3_REGION, "
            "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in the environment."
        )
    import boto3
    return boto3.client(
        "s3",
        region_name=settings.AWS_S3_REGION,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID or None,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY or None,
        # Without this, boto3 can fall back to the legacy global
        # "s3.amazonaws.com" host for presigned URLs, whose requests get
        # routed to the us-east-1 frontend — but the URL is still SIGNED
        # for AWS_S3_REGION, so AWS rejects it with "AuthorizationQuery
        # ParametersError: the region '<region>' is wrong; expecting
        # 'us-east-1'". Pinning the regional endpoint explicitly keeps the
        # host and the signature's credential scope in agreement for any
        # bucket region, not just us-east-1.
        endpoint_url=f"https://s3.{settings.AWS_S3_REGION}.amazonaws.com",
    )


def upload_data_uri(data_uri: str, *, prefix: str, mime_type: str, category: str, identity: str = "") -> str:
    """
    Decode a "data:<mime>;base64,<payload>" string and upload it to S3 under
    a key namespaced by `prefix` (e.g. "staff-photos/aw_sunrise_clinic") and
    named after `category` (a key from UPLOAD_CATEGORIES, e.g. "staff-photo")
    — never after whatever filename the uploader's device gave it. `mime_type`
    should already be the VERIFIED type from
    core.file_validation.validate_data_uri(), not the client's raw claim.

    `identity` (from identity_slug() above) — when given, becomes a folder
    segment between `prefix` and the file itself, e.g.
    "patient-documents/riya-sharma-awp1029384/patient-document-a1b2c3.pdf".
    This is what makes "find every file for this patient/staff member"
    a matter of browsing/listing one S3 prefix instead of opening files one
    by one — pass it whenever the caller has a patient AWPID or staff email
    on hand. Optional (defaults to no identity folder) since a few upload
    types genuinely aren't tied to one person — the hospital logo belongs to
    the clinic, not an individual.

    Returns the S3 object key to store in the model field — never a URL.
    Callers must call signed_url() separately whenever the file is actually
    served back to a client. Callers that also store a user-facing file_name
    (LabReport, SharedDocument, SharedVaccination) should set it from
    display_file_name(category, mime_type), not from client input either.

    Raises StorageError if S3 isn't configured or the upload fails — callers
    should catch this and turn it into a 503/500 response via core.response,
    the same way they already catch FileValidationError for a 400.
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
    # Short random suffix (not a full UUID) keeps keys unique without making
    # them unreadable — e.g. "staff-photo-a1b2c3d4e5f6.jpg", so the category
    # is legible at a glance in the S3 console, not just in the folder path.
    base = f"{prefix.strip('/')}/{identity}" if identity else prefix.strip('/')
    key = f"{base}/{category}-{uuid.uuid4().hex[:16]}.{ext}"

    client = _client()
    try:
        client.put_object(
            Bucket=settings.AWS_S3_BUCKET,
            Key=key,
            Body=raw,
            ContentType=mime_type,
            ServerSideEncryption="AES256",
        )
    except Exception as exc:
        logger.error("S3 upload failed for key=%s", key, exc_info=True)
        raise StorageError("Upload to storage failed. Please try again.") from exc
    return key


def signed_url(key: str, *, expires_in: int = None, download_name: str = None) -> str:
    """
    Generate a time-limited presigned GET URL for an S3 key.

    Deliberately forgiving rather than raising: returns "" for a blank/None
    key (so callers can do signed_url(obj.photo) unconditionally, no
    `if obj.photo else ""` guard needed everywhere), and also returns "" —
    instead of raising — if S3 isn't configured or the presign call fails,
    since a missing avatar/signature/report shouldn't 500 an entire profile
    or history page; it just renders as no-file, same as an empty field
    always has.

    `download_name`: when given, the URL carries a `Content-Disposition:
    attachment; filename="..."` override so the browser SAVES the file (with
    that name) instead of rendering it inline. Used by the "Download" actions
    on prescription / handwriting PDFs.
    """
    if not key:
        return ""
    try:
        client = _client()
    except StorageError:
        return ""
    expires_in = expires_in or settings.AWS_S3_URL_EXPIRY
    params = {"Bucket": settings.AWS_S3_BUCKET, "Key": key}
    if download_name:
        safe = download_name.replace('"', "").replace("\n", " ").strip() or "download"
        params["ResponseContentDisposition"] = f'attachment; filename="{safe}"'
    try:
        return client.generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=expires_in,
        )
    except Exception:
        logger.error("S3 presign failed for key=%s", key, exc_info=True)
        return ""


def delete(key: str) -> None:
    """
    Best-effort delete — e.g. when a photo/signature/logo is replaced or
    removed. Never raises; a failed cleanup shouldn't block the request that
    triggered it (the new file has already been uploaded and saved by the
    time this runs in every call site below).
    """
    if not key:
        return
    try:
        _client().delete_object(Bucket=settings.AWS_S3_BUCKET, Key=key)
    except Exception:
        logger.warning("S3 delete failed for key=%s", key, exc_info=True)
