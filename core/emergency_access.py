"""
core/emergency_access.py
--------------------------
Short-lived, signed tokens behind the patient portal's "Emergency QR"
feature: a patient (or a family member linked to their account) can show a
QR code that, when scanned by literally any phone's camera, opens a
read-only emergency-summary page — no login, no app install, works at any
hospital whether or not it's part of this network. This is for the
"unregistered/nearby/emergency hospital" scenario, distinct from the
HIE cross-hospital sharing model (apps.registry's Shared* tables + the
Patient.hie_consent_given gate) — that gate protects passive/ambient
cross-hospital staff access; this is an explicit, patient-initiated,
time-boxed disclosure to whichever doctor is physically in front of her.

Reuses the same signed-JWT pattern as core.otp.make_action_token() (short
TTL, jti, HS256 with JWT_SIGNING_KEY) but with its own token_type so it can
never be confused with, or accidentally accepted by, the OTP action-token
flow — that's a different security concern with a different lifecycle and
claim shape.

Security notes:
  - A JWT's payload is base64url-encoded, NOT encrypted — anyone holding
    the token (or the QR image) can decode and read every claim in it
    without ever calling this server. The payload here is therefore kept
    to the bare minimum needed to look up the right patient: awpid, exp,
    jti. No PHI (name, allergies, contact info, medications) is ever
    embedded in the token itself — decode_emergency_token() only hands
    back the awpid; every actual clinical field is fetched fresh,
    server-side, by the view that receives the decoded token.
  - Deliberately NOT revocable early — the token is stateless (nothing to
    delete to invalidate it), so the exposure window is kept short
    (EMERGENCY_TOKEN_TTL_MINUTES) instead. A patient who wants a fresh
    window just re-opens the QR screen, which mints a new token; the old
    one simply expires on its own a few minutes later rather than
    lingering indefinitely.
"""

import secrets
from datetime import timedelta

import jwt
from django.conf import settings
from django.utils import timezone

EMERGENCY_TOKEN_TTL_MINUTES = 20


class EmergencyTokenError(Exception):
    """Raised for an expired/invalid/malformed emergency access token."""


def make_emergency_token(awpid: str) -> str:
    """
    Mint a short-lived token granting read-only emergency-summary access
    for this one patient (self or a linked family member — the caller is
    responsible for having already verified the requesting account is
    allowed to see this awpid, same as every other portal endpoint that
    accepts a patient_awpid).
    """
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
