"""core/messaging/sms.py"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def _mask(number) -> str:
    """Phone number safe for logs: only the last 4 digits."""
    digits = str(number or "")
    return ("*" * max(len(digits) - 4, 0)) + digits[-4:]


def send_sms(to: str, message: str) -> bool:
    """Free-text SMS — used by the log/dev fallback and by Android Gateway,"""
    backend = getattr(settings, "SMS_BACKEND", "log")
    fallback_backend = getattr(settings, "SMS_FALLBACK_BACKEND", "")

    if _send_free_text_via(backend, to, message):
        return True

    if fallback_backend and fallback_backend != backend:
        logger.warning("send_sms(): SMS_BACKEND=%s failed for to=%s — "
                        "retrying via SMS_FALLBACK_BACKEND=%s.",
                        backend, _mask(to), fallback_backend)
        return _send_free_text_via(fallback_backend, to, message)

    return False


def _send_free_text_via(backend: str, to: str, message: str) -> bool:
    if backend == "msg91":
        logger.warning("send_sms() (free text) called with SMS_BACKEND=msg91 — "
                        "MSG91 only sends approved templates; use send_otp_sms(). "
                        "Falling back to log. to=%s", _mask(to))
        return _log_fallback(to, message)
    if backend == "android_gateway":
        return _send_via_android_gateway(to, message)
    return _log_fallback(to, message)


def _log_fallback(to: str, message: str) -> bool:
    logger.info("SMS[log-fallback] to=%s message=%r "
                "(no SMS gateway configured — set SMS_BACKEND=msg91 + "
                "MSG91_AUTH_KEY/MSG91_TEMPLATE_ID in production; see core/messaging/sms.py)",
                to, message)
    return True


def send_otp_sms(to: str, code: str, purpose_label: str) -> bool:
    """Primary entry point for OTP delivery. Dispatches to whichever backend"""
    backend = getattr(settings, "SMS_BACKEND", "log")
    fallback_backend = getattr(settings, "SMS_FALLBACK_BACKEND", "")

    if _send_otp_via(backend, to, code, purpose_label):
        return True

    if fallback_backend and fallback_backend != backend:
        logger.warning("send_otp_sms(): SMS_BACKEND=%s failed for to=%s — "
                        "retrying via SMS_FALLBACK_BACKEND=%s.",
                        backend, _mask(to), fallback_backend)
        return _send_otp_via(fallback_backend, to, code, purpose_label)

    return False


def _send_otp_via(backend: str, to: str, code: str, purpose_label: str) -> bool:
    if backend == "msg91":
        return _send_via_msg91(to, code)

    message = (f"Your Atomwalk verification code for {purpose_label} is {code}. "
               f"Valid for 10 minutes. Do not share this code.")

    if backend == "android_gateway":
        return _send_via_android_gateway(to, message)

    return _log_fallback(to, message)


def _send_via_msg91(to: str, code: str) -> bool:
    auth_key    = getattr(settings, "MSG91_AUTH_KEY", "")
    template_id = getattr(settings, "MSG91_TEMPLATE_ID", "")
    var_name    = getattr(settings, "MSG91_OTP_VAR_NAME", "VAR1")

    if not auth_key or not template_id:
        logger.error("SMS_BACKEND=msg91 but MSG91_AUTH_KEY/MSG91_TEMPLATE_ID "
                      "not configured — falling back to log. to=%s", _mask(to))
        return _log_fallback(to, f"[MSG91 not configured] OTP={code}")

    # MSG91 expects the country code prefixed with no leading '+' (e.g.
    mobile = to if to.startswith("91") and len(to) == 12 else f"91{to}"

    try:
        import requests
    except ImportError:
        logger.error("SMS_BACKEND=msg91 requires the 'requests' package "
                      "(pip install requests) — falling back to log. to=%s", _mask(to))
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
            logger.error("MSG91 returned 200 but non-success body: %r to=%s", body, _mask(to))
            return False
        logger.error("MSG91 send failed: status=%s body=%s to=%s", resp.status_code, resp.text[:500], _mask(to))
        return False
    except Exception as exc:
        logger.error("MSG91 send raised an exception: %s to=%s", exc, _mask(to))
        return False


def _send_via_android_gateway(to: str, message: str) -> bool:
    base_url = getattr(settings, "SMS_GATEWAY_BASE_URL", "")
    username = getattr(settings, "SMS_GATEWAY_USERNAME", "")
    password = getattr(settings, "SMS_GATEWAY_PASSWORD", "")

    if not base_url or not username or not password:
        logger.error("SMS_BACKEND=android_gateway but SMS_GATEWAY_BASE_URL/"
                      "SMS_GATEWAY_USERNAME/SMS_GATEWAY_PASSWORD not fully "
                      "configured — falling back to log. to=%s", _mask(to))
        return _log_fallback(to, f"[Android Gateway not configured] {message}")

    # The gateway expects E.164 (leading '+') — `to` here is always a bare
    if to.startswith("+"):
        phone = to
    elif to.startswith("91") and len(to) == 12:
        phone = f"+{to}"
    else:
        phone = f"+91{to}"

    try:
        import requests
    except ImportError:
        logger.error("SMS_BACKEND=android_gateway requires the 'requests' "
                      "package (pip install requests) — falling back to "
                      "log. to=%s", _mask(to))
        return _log_fallback(to, f"[requests not installed] {message}")

    payload = {
        "textMessage": {"text": message},
        "phoneNumbers": [phone],
    }

    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/3rdparty/v1/messages",
            json=payload, auth=(username, password), timeout=10,
        )
        if resp.status_code in (200, 201, 202):
            return True
        logger.error("Android Gateway send failed: status=%s body=%s to=%s",
                      resp.status_code, resp.text[:500], _mask(to))
        return False
    except Exception as exc:
        # Most commonly a connection failure — the Django server can't
        logger.error("Android Gateway send raised an exception: %s to=%s", exc, _mask(to))
        return False
