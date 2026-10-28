"""Small helpers shared by several apps: ages, patient ids (AWPID), distances, random pad tokens and the signed QR tokens printed on prescriptions."""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import string
import time
from datetime import date
from math import atan2, cos, radians, sin, sqrt

from django.conf import settings

logger = logging.getLogger(__name__)


# ── Age ──────────────────────────────────────────────────────────────────────

def age_years_months(dob):
    """Returns (years, months) elapsed from dob to today, or None if dob is"""
    if not dob:
        return None
    today = date.today()
    years = today.year - dob.year
    months = today.month - dob.month
    if today.day < dob.day:
        months -= 1
    if months < 0:
        years -= 1
        months += 12
    if years < 0:
        return None
    return years, months


def age_years(dob):
    """Whole-years age only (backward-compatible with the old int field)."""
    ym = age_years_months(dob)
    return ym[0] if ym else None


# ── Patient id ───────────────────────────────────────────────────────────────

# Character set for the random suffix (uppercase alphanumeric, no ambiguous chars)
_CHARSET = string.ascii_uppercase + string.digits
_SUFFIX_LENGTH = 8
_MAX_RETRIES = 10


def generate_awpid() -> str:
    """Generate a unique AWPID string."""
    date_part = date.today().strftime("%Y%m%d")
    suffix = "".join(secrets.choice(_CHARSET) for _ in range(_SUFFIX_LENGTH))
    return f"AWPID-{date_part}-{suffix}"


def generate_unique_awpid() -> str:
    """Generate an AWPID that is guaranteed to be unique in the atomwalk DB."""
    from apps.patients.models import Patient

    for attempt in range(1, _MAX_RETRIES + 1):
        candidate = generate_awpid()
        if not Patient.objects.filter(awpid=candidate).exists():
            logger.debug("AWPID generated in %d attempt(s): %s", attempt, candidate)
            return candidate

    raise RuntimeError(
        f"Failed to generate a unique AWPID after {_MAX_RETRIES} attempts. "
        "This is extremely unlikely — check for data issues."
    )


# ── Distance ─────────────────────────────────────────────────────────────────

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance between two lat/lng points, in kilometers."""
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * atan2(sqrt(a), sqrt(1 - a))


def parse_lat_lng(request):
    """Pulls optional ?lat=&lng= query params off a request, validated to real"""
    lat_raw = (request.query_params.get("lat") or "").strip()
    lng_raw = (request.query_params.get("lng") or "").strip()
    if not lat_raw or not lng_raw:
        return None, None
    try:
        lat, lng = float(lat_raw), float(lng_raw)
    except ValueError:
        return None, None
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        return None, None
    return lat, lng


# ── Consult-pad token ────────────────────────────────────────────────────────

def new_pad_token():
    return secrets.token_urlsafe(32)


# ── QR tokens on printed prescriptions ───────────────────────────────────────

_TYPE_TO_DOCTYPE = {"RX": "prescription"}
_DOCTYPE_TO_TYPE = {"prescription": "RX"}


def _secret() -> bytes:
    s = getattr(settings, "DOC_QR_SECRET", "") or settings.SECRET_KEY
    return s.encode("utf-8")


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue_qr_token(*, doc_type: str, public_document_id: str, awpid: str) -> str:
    """
    Build the token string to encode into a QR. `doc_type` is "prescription"
    or "lab_report"; `public_document_id` is the quotable id (rx_number /
    report_number); `awpid` is the owning patient.
    """
    t = _DOCTYPE_TO_TYPE.get(doc_type)
    if not t:
        raise ValueError(f"qr_token.issue: unsupported doc_type {doc_type!r}")
    payload = json.dumps(
        {"v": 1, "t": t, "id": str(public_document_id), "awp": str(awpid), "iat": int(time.time())},
        separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    sig = hmac.new(_secret(), payload, hashlib.sha256).digest()
    return _b64e(payload) + "." + _b64e(sig)


def issue_qr_url(*, doc_type: str, public_document_id: str, awpid: str) -> str:
    """Same as issue_qr_token(), but wrapped in the public view-report link that's"""
    token = issue_qr_token(doc_type=doc_type, public_document_id=public_document_id, awpid=awpid)
    return f"{settings.FRONTEND_URL.rstrip('/')}/view-report/{token}"


class QRResult:
    __slots__ = ("ok", "reason", "doc_type", "public_document_id", "awpid")

    def __init__(self, ok, reason="", doc_type="", public_document_id="", awpid=""):
        self.ok = ok
        self.reason = reason
        self.doc_type = doc_type
        self.public_document_id = public_document_id
        self.awpid = awpid

    def __repr__(self):
        return f"<QRResult ok={self.ok} reason={self.reason!r} type={self.doc_type!r} id={self.public_document_id!r}>"


def _extract_token(raw: str) -> str:
    """Accepts either a bare token or a full ".../view-report/<token>" URL (a"""
    s = (raw or "").strip()
    if "/" in s:
        s = s.rstrip("/").rsplit("/", 1)[-1]
    return s


def verify_qr_token(token: str) -> QRResult:
    """Parse and authenticate a scanned token — bare, or wrapped in the"""
    if not token or not isinstance(token, str):
        return QRResult(False, "malformed")
    token = _extract_token(token)
    if "." not in token:
        return QRResult(False, "malformed")
    body_b64, sig_b64 = token.split(".", 1)
    try:
        body = _b64d(body_b64)
        sig = _b64d(sig_b64)
    except Exception:
        return QRResult(False, "malformed")

    expected = hmac.new(_secret(), body, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        return QRResult(False, "bad_signature")

    try:
        data = json.loads(body)
    except Exception:
        return QRResult(False, "malformed")
    if data.get("v") != 1:
        return QRResult(False, "unsupported_version")

    doc_type = _TYPE_TO_DOCTYPE.get(data.get("t"))
    if not doc_type or not data.get("id") or not data.get("awp"):
        return QRResult(False, "incomplete")
    return QRResult(True, "", doc_type, str(data["id"]), str(data["awp"]))
