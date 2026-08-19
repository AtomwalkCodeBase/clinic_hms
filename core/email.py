"""
core/email.py
---------------
Thin wrapper over Django's own email machinery (django.core.mail) — this
codebase had no EMAIL_BACKEND configured at all before this file existed
(see atomwalk/settings/base.py). In DEBUG it defaults to Django's console
backend (prints the email to the server log — no account needed, fully
functional for local dev/demo). In production it requires real SMTP
credentials via env vars (EMAIL_HOST / EMAIL_HOST_USER / EMAIL_HOST_PASSWORD
etc.) — same "the hospital's own account, not ours" pattern already used
for the payment gateway: Atomwalk can't supply a working mail relay on the
customer's behalf, but the integration is real and will work the moment
they plug in an SMTP account (Gmail app password, SES, SendGrid SMTP, etc).

Never raises — a failed email must not break the request that triggered it
(same never-break-the-caller contract as core/audit.py::log_action).
"""

import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


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
    """
    Sent once, at provisioning time, to the hospital's admin email — the only
    place the raw temp password is delivered. The provisioning UI deliberately
    stops showing it on screen (see platform-admin DashboardPage.jsx), so this
    email is the admin's sole record of it until they set their own password.
    """
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
