"""core/utils/realworld_validation.py"""

import logging

logger = logging.getLogger(__name__)


def validate_mobile_real(mobile: str, region: str = "IN"):
    """Returns (is_valid: bool, reason: str). reason is "" when valid."""
    try:
        import phonenumbers
        from phonenumbers import NumberParseException, PhoneNumberType
    except ImportError:
        # phonenumbers not installed in this environment — degrade to
        logger.warning("phonenumbers package not installed — skipping real-world mobile validation.")
        return True, ""

    try:
        parsed = phonenumbers.parse(mobile, region)
    except NumberParseException:
        return False, "Enter a valid mobile number."

    if not phonenumbers.is_valid_number(parsed):
        return False, "This doesn't look like a real mobile number."

    number_type = phonenumbers.number_type(parsed)
    if number_type == PhoneNumberType.FIXED_LINE:
        return False, "Enter a mobile number, not a landline."

    return True, ""


def validate_email_domain(email: str, timeout: float = 5.0):
    """Returns (is_valid: bool, reason: str). reason is "" when valid or when"""
    if "@" not in email:
        return False, "Enter a valid email address."
    domain = email.rsplit("@", 1)[-1].strip()
    if not domain:
        return False, "Enter a valid email address."

    try:
        import dns.resolver
    except ImportError:
        logger.warning("dnspython package not installed — skipping email domain validation.")
        return True, ""

    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=timeout)
        if len(answers) == 0:
            return False, "This email domain can't receive mail."
        return True, ""
    except dns.resolver.NXDOMAIN:
        return False, "This email domain doesn't exist."
    except dns.resolver.NoAnswer:
        # No MX record — some small domains route mail via a bare A record
        return False, "This email domain can't receive mail."
    except Exception as exc:
        logger.warning("MX lookup failed for domain=%s: %s — failing open.", domain, exc)
        return True, ""
