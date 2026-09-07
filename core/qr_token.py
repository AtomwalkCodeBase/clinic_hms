"""
core/qr_token.py
----------------
Signed tokens for the QR codes the HMS prints on prescriptions and lab
reports. The token is what the patient's phone scans; the portal verifies it
before linking an uploaded photo back to the original hospital record.

Format:  <b64url(payload_json)>.<b64url(hmac_sha256(payload_json, secret))>

payload_json = {"v":1, "t":"RX"|"LAB", "id":"<public_document_id>",
                "awp":"<awpid>", "iat":<unix_ts>}

Verification is: signature valid (it really is a token this HMS issued) AND
the awpid in the token matches the patient uploading it. A forged or foreign
code fails at one of those two checks — a bare document id is never trusted
on its own.

The secret is settings.DOC_QR_SECRET, falling back to SECRET_KEY. It has its
own env var because rotating it invalidates every previously printed QR.
"""

import base64
import hashlib
import hmac
import json
import time

from django.conf import settings

_TYPE_TO_DOCTYPE = {"RX": "prescription", "LAB": "lab_report"}
_DOCTYPE_TO_TYPE = {"prescription": "RX", "lab_report": "LAB"}


def _secret() -> bytes:
    s = getattr(settings, "DOC_QR_SECRET", "") or settings.SECRET_KEY
    return s.encode("utf-8")


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue(*, doc_type: str, public_document_id: str, awpid: str) -> str:
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


def verify(token: str) -> QRResult:
    """
    Parse and authenticate a scanned token. Never raises — returns a QRResult
    whose .ok is False (with .reason) on anything malformed, unsigned or
    incomplete. Callers still have to check .awpid against the current patient.
    """
    if not token or not isinstance(token, str) or "." not in token:
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
