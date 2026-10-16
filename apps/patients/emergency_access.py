"""apps/patients/emergency_access.py"""

import secrets
from datetime import timedelta

import jwt
from django.conf import settings
from django.utils import timezone

EMERGENCY_TOKEN_TTL_MINUTES = 20


class EmergencyTokenError(Exception):
    """Raised for an expired/invalid/malformed emergency access token."""


def make_emergency_token(awpid: str) -> str:
    """Mint a short-lived token granting read-only emergency-summary access"""
    payload = {
        "token_type": "emergency_access",
        "awpid": awpid,
        "exp": timezone.now() + timedelta(minutes=EMERGENCY_TOKEN_TTL_MINUTES),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, settings.JWT_SIGNING_KEY, algorithm="HS256")


def decode_emergency_token(token: str) -> str:
    """Returns the awpid this token grants access to, or raises EmergencyTokenError."""
    try:
        payload = jwt.decode(token, settings.JWT_SIGNING_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise EmergencyTokenError("This emergency code has expired. Ask the patient to show a fresh QR code.")
    except jwt.InvalidTokenError:
        raise EmergencyTokenError("Invalid or corrupted emergency code.")

    if payload.get("token_type") != "emergency_access":
        raise EmergencyTokenError("Invalid emergency code.")
    awpid = payload.get("awpid")
    if not awpid:
        raise EmergencyTokenError("Invalid emergency code.")
    return awpid
