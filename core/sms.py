"""
core/sms.py
------------
Pluggable SMS sender. Unlike email, there is no free/built-in SMS transport
— sending a real text message requires a paid gateway account that belongs
to the hospital/Atomwalk. MSG91 is wired in below (India-focused, handles
DLT — the mandatory telecom-regulator template registration for Indian
transactional SMS — via templates configured on their dashboard).

Until a real provider is configured (SMS_BACKEND="log", the default), the
message is written to the app log at INFO level so it's visible to whoever
is running the server — check the server console/log for the OTP code
during local dev. There is no API-response echo of the code in any mode.

MSG91 specifics (SMS_BACKEND="msg91"):
  MSG91 sends pre-approved DLT templates, not arbitrary free text — the
  message content itself is fixed at template-creation time on the MSG91
  dashboard, with a variable slot for the OTP code. This module fills that
  variable (MSG91_OTP_VAR_NAME, default "VAR1") rather than building a full
  message string, unlike the log/dev fallback below which can say anything.
  Required settings: MSG91_AUTH_KEY, MSG91_TEMPLATE_ID (the DLT-approved
  template's ID from the MSG91 dashboard). Sender ID is baked into the
  template at creation time on MSG91's side, not sent per-request.
  API reference: https://docs.msg91.com/sms/send-sms
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def send_sms(to: str, message: str) -> bool:
    """
    Free-text SMS — used by the log/dev fallback. NOT used for MSG91, which
    sends pre-approved templates instead (see send_otp_sms below).
    """
    backend = getattr(settings, "SMS_BACKEND", "log")
    if backend == "msg91":
        logger.warning("send_sms() (free text) called with SMS_BACKEND=msg91 — "
                        "MSG91 only sends approved templates; use send_otp_sms(). "
                        "Falling back to log. to=%s", to)
        return _log_fallback(to, message)
    return _log_fallback(to, message)


def _log_fallback(to: str, message: str) -> bool:
    logger.info("SMS[log-fallback] to=%s message=%r "
                "(no SMS gateway configured — set SMS_BACKEND=msg91 + "
                "MSG91_AUTH_KEY/MSG91_TEMPLATE_ID in production; see core/sms.py)",
                to, message)
    return True


def send_otp_sms(to: str, code: str, purpose_label: str) -> bool:
    """
    Primary entry point for OTP delivery. Dispatches to whichever backend
    is configured — log (dev fallback, free text) or msg91 (real delivery,
    template-based).
    """
    backend = getattr(settings, "SMS_BACKEND", "log")

    if backend == "msg91":
        return _send_via_msg91(to, code)

    message = (f"Your Atomwalk verification code for {purpose_label} is {code}. "
               f"Valid for 10 minutes. Do not share this code.")
    return _log_fallback(to, message)


def _send_via_msg91(to: str, code: str) -> bool:
    auth_key    = getattr(settings, "MSG91_AUTH_KEY", "")
    template_id = getattr(settings, "MSG91_TEMPLATE_ID", "")
    var_name    = getattr(settings, "MSG91_OTP_VAR_NAME", "VAR1")

    if not auth_key or not template_id:
        logger.error("SMS_BACKEND=msg91 but MSG91_AUTH_KEY/MSG91_TEMPLATE_ID "
                      "not configured — falling back to log. to=%s", to)
        return _log_fallback(to, f"[MSG91 not configured] OTP={code}")

    # MSG91 expects the country code prefixed with no leading '+' (e.g.
    # "919876543210") — `to` here is always a bare 10-digit Indian mobile
    # number (see core.otp.detect_channel / callers), so 91 is prefixed
    # unconditionally rather than trying to detect an existing prefix.
    mobile = to if to.startswith("91") and len(to) == 12 else f"91{to}"

    try:
        import requests
    except ImportError:
        logger.error("SMS_BACKEND=msg91 requires the 'requests' package "
                      "(pip install requests) — falling back to log. to=%s", to)
        return _log_fallback(to, f"[requests not installed] OTP={code}")

    payload = {
        "template_id": template_id,
        "short_url": "0",
        "recipients": [
            {"mobiles": mobile, var_name: code},
        ],
    }
    headers = {
        "accept": "application/json",
        "authkey": auth_key,
        "content-type": "application/json",
    }

    try:
        resp = requests.post(
            "https://control.msg91.com/api/v5/flow",
            json=payload, headers=headers, timeout=10,
        )
        if resp.status_code == 200:
            body = resp.json() if resp.content else {}
            if body.get("type") == "success":
                return True
            logger.error("MSG91 returned 200 but non-success body: %r to=%s", body, to)
            return False
        logger.error("MSG91 send failed: status=%s body=%s to=%s", resp.status_code, resp.text[:500], to)
        return False
    except Exception as exc:
        logger.error("MSG91 send raised an exception: %s to=%s", exc, to)
        return False
