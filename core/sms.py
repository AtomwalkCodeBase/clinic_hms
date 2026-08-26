"""
core/sms.py
------------
Pluggable SMS sender. Unlike email, there is no free/built-in SMS transport
— sending a real text message requires a paid gateway account that belongs
to the hospital/Atomwalk. Two providers are wired in: MSG91 (a commercial
India-focused aggregator, handles DLT template registration) and Android
Gateway (self-hosted — turns a phone with a SIM into the "gateway", so cost
is whatever's already in the SIM's own plan instead of a per-message API fee).

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

Android Gateway specifics (SMS_BACKEND="android_gateway"):
  Uses "SMS Gateway for Android" (github.com/capcom6/android-sms-gateway,
  Apache-2.0) — install the app on a phone with a SIM, it exposes a REST
  API that relays outbound SMS through the phone's normal cellular SMS,
  billed at whatever the SIM's own plan/bundle costs rather than a
  per-message aggregator fee. Unlike MSG91 this backend sends free text,
  same as the log fallback, so no DLT template is needed here — but the
  hospital's own DLT/TRAI registration obligations for transactional SMS
  in India still apply regardless of which gateway sends it.
  Required settings: SMS_GATEWAY_BASE_URL (the phone's own address in
  Local mode, e.g. "http://192.168.1.50:8080", or a Private/Cloud server
  URL — see docs.sms-gate.app/getting-started), SMS_GATEWAY_USERNAME,
  SMS_GATEWAY_PASSWORD (both shown on the app's Home screen).
  Local mode requires the Django server to be on the same network as the
  phone; it will not work from a server that can't reach the phone's LAN.
  API reference: https://docs.sms-gate.app/integration/api/

Fallback chain (SMS_FALLBACK_BACKEND, optional):
  If set to a different backend name, that backend is tried automatically
  whenever the primary SMS_BACKEND's actual send attempt fails (HTTP error,
  non-success response, exception) — not when it's merely unconfigured,
  which already falls back to the log in each backend's own function above.
  e.g. SMS_BACKEND=android_gateway + SMS_FALLBACK_BACKEND=msg91 means a
  phone/gateway outage doesn't silently stop OTP delivery — it drops
  through to MSG91 automatically. msg91 can only be a fallback for OTP
  sends (send_otp_sms), not free text (send_sms), since it only sends
  pre-approved templates.
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def send_sms(to: str, message: str) -> bool:
    """
    Free-text SMS — used by the log/dev fallback and by Android Gateway,
    both of which can send arbitrary text. NOT used for MSG91, which sends
    pre-approved templates instead (see send_otp_sms below).

    Tries SMS_BACKEND first; if that backend is configured but the actual
    send attempt fails (not just "unconfigured" — see each backend's own
    function), retries once via SMS_FALLBACK_BACKEND if one is set. See the
    "Fallback chain" section of the module docstring.
    """
    backend = getattr(settings, "SMS_BACKEND", "log")
    fallback_backend = getattr(settings, "SMS_FALLBACK_BACKEND", "")

    if _send_free_text_via(backend, to, message):
        return True

    if fallback_backend and fallback_backend != backend:
        logger.warning("send_sms(): SMS_BACKEND=%s failed for to=%s — "
                        "retrying via SMS_FALLBACK_BACKEND=%s.",
                        backend, to, fallback_backend)
        return _send_free_text_via(fallback_backend, to, message)

    return False


def _send_free_text_via(backend: str, to: str, message: str) -> bool:
    if backend == "msg91":
        logger.warning("send_sms() (free text) called with SMS_BACKEND=msg91 — "
                        "MSG91 only sends approved templates; use send_otp_sms(). "
                        "Falling back to log. to=%s", to)
        return _log_fallback(to, message)
    if backend == "android_gateway":
        return _send_via_android_gateway(to, message)
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
    is configured, with an optional one-hop fallback — see the "Fallback
    chain" section of the module docstring.
    """
    backend = getattr(settings, "SMS_BACKEND", "log")
    fallback_backend = getattr(settings, "SMS_FALLBACK_BACKEND", "")

    if _send_otp_via(backend, to, code, purpose_label):
        return True

    if fallback_backend and fallback_backend != backend:
        logger.warning("send_otp_sms(): SMS_BACKEND=%s failed for to=%s — "
                        "retrying via SMS_FALLBACK_BACKEND=%s.",
                        backend, to, fallback_backend)
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


def _send_via_android_gateway(to: str, message: str) -> bool:
    base_url = getattr(settings, "SMS_GATEWAY_BASE_URL", "")
    username = getattr(settings, "SMS_GATEWAY_USERNAME", "")
    password = getattr(settings, "SMS_GATEWAY_PASSWORD", "")

    if not base_url or not username or not password:
        logger.error("SMS_BACKEND=android_gateway but SMS_GATEWAY_BASE_URL/"
                      "SMS_GATEWAY_USERNAME/SMS_GATEWAY_PASSWORD not fully "
                      "configured — falling back to log. to=%s", to)
        return _log_fallback(to, f"[Android Gateway not configured] {message}")

    # The gateway expects E.164 (leading '+') — `to` here is always a bare
    # 10-digit Indian mobile number (see core.otp.detect_channel / callers),
    # so +91 is prefixed unconditionally rather than trying to detect an
    # existing prefix.
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
                      "log. to=%s", to)
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
                      resp.status_code, resp.text[:500], to)
        return False
    except Exception as exc:
        # Most commonly a connection failure — the Django server can't
        # reach the phone (Local mode requires the same network; the phone
        # may be off, the app closed, or the IP changed since configuring
        # SMS_GATEWAY_BASE_URL).
        logger.error("Android Gateway send raised an exception: %s to=%s", exc, to)
        return False
