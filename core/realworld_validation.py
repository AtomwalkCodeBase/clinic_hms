"""
core/realworld_validation.py
------------------------------
Validation that goes beyond "is this the right shape" (regex) to "could
this plausibly be a real, reachable mobile number / email address" —
requested so registration and contact-info changes reject obviously-fake
input (555-000-0000-style numbers, typo'd domains) before an OTP is ever
"sent" to it.

validate_mobile_real() — uses Google's libphonenumber (the `phonenumbers`
package) to parse against India's real numbering plan and reject anything
that isn't a valid, currently-assignable mobile number (landlines,
malformed numbers, etc.). Fully offline — no network call, no cost.

validate_email_domain() — looks up the domain's MX records over DNS. A
domain with no mail exchanger can't receive email at all, which a regex
can never catch (e.g. "user@gmial.com" is regex-valid and DNS-invalid).
Fails OPEN on a DNS timeout/error (returns True) — a slow resolver
shouldn't block someone with a perfectly real address; the OTP itself is
the real proof of deliverability.
"""

import logging

logger = logging.getLogger(__name__)


def validate_mobile_real(mobile: str, region: str = "IN"):
    """
    Returns (is_valid: bool, reason: str). reason is "" when valid.
    """
    try:
        import phonenumbers
        from phonenumbers import NumberParseException, PhoneNumberType
    except ImportError:
        # phonenumbers not installed in this environment — degrade to
        # "can't check further, don't block the user" rather than a 500.
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
    """
    Returns (is_valid: bool, reason: str). reason is "" when valid or when
    the check couldn't be completed (fail-open).
    """
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
        # instead, which is nonstandard but real; deliberately NOT treated
        # as a fallback pass here (per spec: no A-record fallback, to avoid
        # missing genuine typo'd domains like gmial.com that do have an A
        # record for their parking page but no mail exchanger at all).
        return False, "This email domain can't receive mail."
    except Exception as exc:
        logger.warning("MX lookup failed for domain=%s: %s — failing open.", domain, exc)
        return True, ""
