"""One-time codes, the signed "this identifier just verified a code" tokens, and revoked sign-in tokens — all kept in Redis (settings.REDIS_URL),
so they expire on their own and need no database table.

Keys:  otp:<purpose>:<identifier>         the pending code (hash + who it is for + wrong attempts so far), lives OTP_TTL_SECONDS
       otp-wait:<purpose>:<identifier>    present while a new code may not yet be asked for (RESEND_COOLDOWN_SECONDS)
       revoked:<jti>                      a signed-out token, lives until that token would have expired anyway"""

import hashlib
import logging
import secrets
import time
from datetime import timedelta
from functools import lru_cache
from types import SimpleNamespace

import jwt
import redis
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

OTP_LENGTH = 6
OTP_TTL_SECONDS = 600
ACTION_TOKEN_TTL_MINUTES = 10
MAX_VERIFY_ATTEMPTS = 5
RESEND_COOLDOWN_SECONDS = 60
DEFAULT_REVOKE_SECONDS = 7 * 24 * 3600


class Purpose:
    PASSWORD_RESET_STAFF = "password_reset_staff"
    PASSWORD_RESET_PATIENT = "password_reset_patient"
    REGISTRATION_PATIENT = "registration_patient"
    LOGIN_PATIENT = "login_patient"
    CONTACT_CHANGE_PATIENT = "contact_change_patient"


class OTPError(Exception):
    """Raised with a user-facing message for any request/verify failure."""
    def __init__(self, message):
        self.message = message
        super().__init__(message)


@lru_cache(maxsize=1)
def _redis():
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def generate_code() -> str:
    """6-digit numeric OTP, generated with a CSPRNG."""
    return "".join(str(secrets.randbelow(10)) for _ in range(OTP_LENGTH))


def hash_code(code: str) -> str:
    return hashlib.sha256(f"{code}{settings.OTP_HASH_PEPPER}".encode("utf-8")).hexdigest()


def detect_channel(identifier: str) -> str:
    return "email" if "@" in identifier else "sms"


def create_otp(purpose, identifier, target_type="", target_id=None, target_db=""):
    """Store a new code for this purpose and identifier (replacing any earlier one). Does NOT send it — callers pair this with a sender.
    Returns (code, channel)."""
    r = _redis()
    wait_key = f"otp-wait:{purpose}:{identifier}"
    if not r.set(wait_key, 1, nx=True, ex=RESEND_COOLDOWN_SECONDS):
        raise OTPError(f"Please wait {max(1, r.ttl(wait_key))}s before requesting another code.")
    code = generate_code()
    key = f"otp:{purpose}:{identifier}"
    r.delete(key)
    r.hset(key, mapping={"code_hash": hash_code(code), "target_type": target_type or "", "target_id": "" if target_id is None else target_id,
                         "target_db": target_db or "", "attempts": 0})
    r.expire(key, OTP_TTL_SECONDS)
    return code, detect_channel(identifier)


def verify_otp(purpose, identifier, submitted_code):
    """Check a submitted code against the pending one. A right code is used up; five wrong ones lock it. Returns who the code was for."""
    r = _redis()
    key = f"otp:{purpose}:{identifier}"
    row = r.hgetall(key)
    if not row:
        raise OTPError("No active code found. Please request a new one.")
    if int(row["attempts"]) >= MAX_VERIFY_ATTEMPTS:
        raise OTPError("Too many incorrect attempts. Please request a new code.")
    if row["code_hash"] != hash_code(str(submitted_code).strip()):
        attempts = r.hincrby(key, "attempts", 1)
        if attempts >= MAX_VERIFY_ATTEMPTS:
            raise OTPError("Too many incorrect attempts. Please request a new code.")
        raise OTPError(f"Incorrect code. {MAX_VERIFY_ATTEMPTS - attempts} attempt(s) remaining.")
    r.delete(key)
    return SimpleNamespace(target_type=row["target_type"], target_id=int(row["target_id"]) if row["target_id"] != "" else None, target_db=row["target_db"])


def make_action_token(purpose, identifier, target_type="", target_id=None, target_db=""):
    """Signed, short-lived JWT proving "this identifier just verified an OTP"."""
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

    if payload.get("token_type") != "otp_action" or payload.get("purpose") != expected_purpose:
        raise OTPError("Invalid verification token.")
    return payload


def revoke_token(jti, exp=None):
    """Sign a token out: it is refused from now until the time it would have expired anyway (`exp`, seconds since 1970)."""
    seconds = int(exp - time.time()) if exp else DEFAULT_REVOKE_SECONDS
    if seconds > 0:
        _redis().set(f"revoked:{jti}", 1, ex=seconds)


def is_revoked(jti):
    """True when the token was signed out. If Redis cannot be reached the check passes (and is logged): the access tokens are short-lived."""
    try:
        return bool(_redis().exists(f"revoked:{jti}"))
    except redis.RedisError:
        logger.exception("could not check whether token %s was revoked", jti)
        return False


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
