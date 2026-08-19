"""
core/otp.py
------------
Shared OTP generation, hashing, verification, and "action token" issuance
used by every OTP flow in the system (staff + patient password reset,
patient self-registration, day-to-day patient OTP login, patient
mobile-number re-verification).

Flow, the same for every purpose:
  1. request_otp()  — creates an OTPCode row (registry DB), sends the code
                       via core.email/core.sms, enforces a resend cooldown.
  2. verify_otp()   — checks the submitted code against the OTPCode row,
                       caps failed attempts, marks the row used, and on
                       success returns a short-lived signed JWT ("action
                       token") — NOT the raw ability to reset a password or
                       create an account directly. This mirrors the
                       existing _make_invite_token pattern in
                       apps.auth_app.views (staff invite → setup-password)
                       rather than inventing a second convention.
  3. decode_action_token() — the next-step endpoint (reset-password,
                       complete-registration, patient-otp-login, confirm
                       mobile-change) calls this to prove step 2 actually
                       happened, and for whom.

Codes are 6 digits, numeric, generated with `secrets` (not `random`) so
they're not predictable. Only the SHA-256 hash (salted with OTP_HASH_PEPPER)
is ever stored — a leaked otp_code row can't be replayed.
"""

import hashlib
import logging
import secrets
from datetime import timedelta

import jwt
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

OTP_LENGTH = 6
OTP_TTL_MINUTES = 10
ACTION_TOKEN_TTL_MINUTES = 10
MAX_VERIFY_ATTEMPTS = 5
RESEND_COOLDOWN_SECONDS = 60


class OTPError(Exception):
    """Raised with a user-facing message for any request/verify failure."""
    def __init__(self, message):
        self.message = message
        super().__init__(message)


def _pepper() -> str:
    # settings.OTP_HASH_PEPPER already resolves the DEBUG-only fallback to
    # JWT_SIGNING_KEY (see atomwalk/settings/base.py) — required standalone
    # in production so this hash can be rotated independently of the JWT
    # signing key.
    return settings.OTP_HASH_PEPPER


def generate_code() -> str:
    """6-digit numeric OTP, generated with a CSPRNG."""
    return "".join(str(secrets.randbelow(10)) for _ in range(OTP_LENGTH))


def hash_code(code: str) -> str:
    return hashlib.sha256(f"{code}{_pepper()}".encode("utf-8")).hexdigest()


def detect_channel(identifier: str) -> str:
    return "email" if "@" in identifier else "sms"


def resend_cooldown_remaining(purpose: str, identifier: str) -> int:
    """Seconds until another OTP may be requested for this purpose+identifier. 0 = allowed now."""
    from apps.registry.models import OTPCode
    last = (
        OTPCode.objects.using("default")
        .filter(purpose=purpose, identifier=identifier)
        .order_by("-created_at")
        .first()
    )
    if not last:
        return 0
    elapsed = (timezone.now() - last.created_at).total_seconds()
    remaining = RESEND_COOLDOWN_SECONDS - elapsed
    return max(0, int(remaining))


def create_otp(purpose, identifier, target_type="", target_id=None, target_db=""):
    """
    Create and persist a new OTPCode row. Does NOT send it — callers pair
    this with core.email.send_otp_email / core.sms.send_otp_sms.
    Returns (otp_row, raw_code, channel).
    """
    from apps.registry.models import OTPCode

    remaining = resend_cooldown_remaining(purpose, identifier)
    if remaining > 0:
        raise OTPError(f"Please wait {remaining}s before requesting another code.")

    code = generate_code()
    channel = detect_channel(identifier)
    otp = OTPCode.objects.using("default").create(
        purpose=purpose,
        identifier=identifier,
        channel=channel,
        code_hash=hash_code(code),
        target_type=target_type,
        target_id=target_id,
        target_db=target_db,
        expires_at=timezone.now() + timedelta(minutes=OTP_TTL_MINUTES),
    )
    return otp, code, channel


def verify_otp(purpose, identifier, submitted_code):
    """
    Verify a submitted code against the most recent unused OTPCode row for
    this purpose+identifier. Raises OTPError with a user-facing message on
    any failure. On success, marks the row used and returns it.
    """
    from apps.registry.models import OTPCode

    otp = (
        OTPCode.objects.using("default")
        .filter(purpose=purpose, identifier=identifier, is_used=False)
        .order_by("-created_at")
        .first()
    )
    if not otp:
        raise OTPError("No active code found. Please request a new one.")
    if otp.expires_at < timezone.now():
        raise OTPError("This code has expired. Please request a new one.")
    if otp.attempts >= MAX_VERIFY_ATTEMPTS:
        raise OTPError("Too many incorrect attempts. Please request a new code.")

    if otp.code_hash != hash_code(str(submitted_code).strip()):
        otp.attempts += 1
        otp.save(using="default", update_fields=["attempts"])
        left = MAX_VERIFY_ATTEMPTS - otp.attempts
        if left <= 0:
            raise OTPError("Too many incorrect attempts. Please request a new code.")
        raise OTPError(f"Incorrect code. {left} attempt(s) remaining.")

    otp.is_used = True
    otp.save(using="default", update_fields=["is_used"])
    return otp


def make_action_token(purpose, identifier, target_type="", target_id=None, target_db=""):
    """
    Signed, short-lived JWT proving "this identifier just verified an OTP
    for this purpose". Presented to the next-step endpoint instead of the
    raw OTP so a code can never be replayed once consumed, and so the
    next-step endpoint doesn't need to re-touch the OTPCode table at all.
    """
    payload = {
        "purpose":     purpose,
        "identifier":  identifier,
        "target_type": target_type,
        "target_id":   target_id,
        "target_db":   target_db,
        "token_type":  "otp_action",
        "exp":         timezone.now() + timedelta(minutes=ACTION_TOKEN_TTL_MINUTES),
        "jti":         secrets.token_hex(8),
    }
    return jwt.encode(payload, settings.JWT_SIGNING_KEY, algorithm="HS256")


def decode_action_token(token, expected_purpose):
    """Decode + validate an action token. Raises OTPError with a user-facing message."""
    try:
        payload = jwt.decode(token, settings.JWT_SIGNING_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise OTPError("This verification has expired. Please start again.")
    except jwt.InvalidTokenError:
        raise OTPError("Invalid verification token.")

    if payload.get("token_type") != "otp_action":
        raise OTPError("Invalid verification token.")
    if payload.get("purpose") != expected_purpose:
        raise OTPError("Invalid verification token.")
    return payload


def mask_identifier(identifier: str) -> str:
    """'9876543210' -> '98••••••10'; 'jane@example.com' -> 'j••e@example.com' — for display only."""
    if "@" in identifier:
        local, _, domain = identifier.partition("@")
        if len(local) <= 2:
            masked_local = local[:1] + "•" * max(0, len(local) - 1)
        else:
            masked_local = local[0] + "•" * (len(local) - 2) + local[-1]
        return f"{masked_local}@{domain}"
    if len(identifier) <= 4:
        return "•" * len(identifier)
    return identifier[:2] + "•" * (len(identifier) - 4) + identifier[-2:]
