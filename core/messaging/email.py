"""core/messaging/email.py"""

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
