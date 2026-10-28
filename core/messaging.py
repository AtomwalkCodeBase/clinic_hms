"""Sending e-mail and SMS: the one place the project talks to a mail server or an SMS gateway.

Which SMS gateway is used comes from settings (SMS_BACKEND, SMS_FALLBACK_BACKEND, MSG91_*, SMS_GATEWAY_*); with none configured the message is only logged."""

import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


# ── E-mail ───────────────────────────────────────────────────────────────────

def send_email(to: str, subject: str, body: str) -> bool:
    if not to:
        return False
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[to],
            fail_silently=False,
        )
        return True
    except Exception as exc:
        logger.error("send_email failed to=%s subject=%r: %s", to, subject, exc)
        return False


def send_otp_email(to: str, code: str, purpose_label: str) -> bool:
    subject = f"Your Atomwalk verification code: {code}"
    body = (
        f"Your one-time verification code for {purpose_label} is:\n\n"
        f"    {code}\n\n"
        f"This code expires in 10 minutes. If you didn't request this, "
        f"you can safely ignore this email.\n\n"
        f"— Atomwalk Healthcare Platform"
    )
    return send_email(to, subject, body)


def send_temp_password_email(to: str, full_name: str, temp_password: str, login_hint: str) -> bool:
    subject = "Your Atomwalk account is ready"
    body = (
        f"Hi {full_name},\n\n"
        f"An account has been created for you on Atomwalk HMS.\n\n"
        f"    Login: {login_hint}\n"
        f"    Temporary password: {temp_password}\n\n"
        f"You'll be asked to set your own password the first time you sign in.\n\n"
        f"— Atomwalk Healthcare Platform"
    )
    return send_email(to, subject, body)


def send_hospital_provisioned_email(to: str, hospital_name: str, hospital_code: str,
                                     employee_id: str, admin_mobile: str, temp_password: str) -> bool:
    """Sent once, at provisioning time, to the hospital's admin email — the only"""
    subject = f"Your Atomwalk hospital admin account is ready — {hospital_name}"
    body = (
        f"Hi,\n\n"
        f"Your hospital, {hospital_name}, has been provisioned on Atomwalk HMS "
        f"and an administrator account has been created for you.\n\n"
        f"    Hospital Code:        {hospital_code}\n"
        f"    Employee ID:          {employee_id}\n"
        f"    Temporary password:   {temp_password}\n\n"
        f"You can sign in either way:\n"
        f"    1. Mobile number ({admin_mobile}) + the temporary password above, or\n"
        f"    2. Hospital Code + Employee ID + the temporary password above.\n\n"
        f"You'll be asked to set your own password the first time you sign in. "
        f"Keep this email until you've done so, then you can delete it.\n\n"
        f"— Atomwalk Healthcare Platform"
    )
    return send_email(to, subject, body)


# ── SMS ──────────────────────────────────────────────────────────────────────

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
                "MSG91_AUTH_KEY/MSG91_TEMPLATE_ID in production; see core/messaging.py)",
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
            settings.MSG91_FLOW_URL,
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
    elif to.startswith(settings.DEFAULT_COUNTRY_CODE.lstrip("+")) and len(to) == len(settings.DEFAULT_COUNTRY_CODE) - 1 + settings.MOBILE_NUMBER_LENGTH:
        phone = f"+{to}"
    else:
        phone = f"{settings.DEFAULT_COUNTRY_CODE}{to}"

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
