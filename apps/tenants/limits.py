"""
apps/tenants/limits.py
-----------------------
Shared, fail-closed subscription-limit enforcement.

Every tier caps three things: doctors, branches, and everyone-else-staff
(nurse/front_desk/lab_tech/pharmacist/hospital_admin, counted together
against max_staff — doctors have their own dedicated max_doctors cap).
A tier's limits live on Subscription (apps.tenants.models), sourced at
provisioning time from TIER_FEATURE_DEFAULTS (apps.tenants.constants).

Previously this counting logic was copy-pasted three times (Branch create,
staff invite, platform-admin usage display) with each write-time check
wrapped in `except Exception: pass` — meaning a DB hiccup or a typo'd
tenant_id silently ALLOWED the create instead of blocking it, which
defeats the entire point of a hard cap. enforce_limit() below fails
CLOSED instead: if the subscription or tenant DB can't be reached, the
request is rejected with a clear, retryable message rather than let
through.
"""

import logging

from apps.org.models import StaffUser, Branch

logger = logging.getLogger(__name__)

# Roles counted against max_staff. Doctors are deliberately excluded here —
# they're counted against max_doctors instead (see check_limit below).
_NON_DOCTOR_ROLES = ["hospital_admin", "nurse", "front_desk", "lab_tech", "pharmacist"]

LIMIT_LABELS = {
    "doctors":  "doctor",
    "branches": "branch",
    "staff":    "staff member",
}


def get_usage_counts(db_name):
    """Live counts from one tenant's own database: {doctors, branches, staff}."""
    doctors = StaffUser.objects.using(db_name).filter(role="doctor", is_active=True).count()
    branches = Branch.objects.using(db_name).filter(is_active=True).count()
    staff = StaffUser.objects.using(db_name).filter(
        role__in=_NON_DOCTOR_ROLES, is_active=True
    ).count()
    return {"doctors": doctors, "branches": branches, "staff": staff}


class LimitCheckFailed(Exception):
    """Raised by check_limit() — carries a user-facing message and HTTP status."""
    def __init__(self, message, status=403):
        super().__init__(message)
        self.message = message
        self.status = status


def check_limit(tenant, db_name, resource, increment=1):
    """
    Raises LimitCheckFailed if adding `increment` more of `resource`
    ("doctors" | "branches" | "staff") would exceed the tenant's
    subscription limit. Returns None (silently) if within limits.

    Fails CLOSED: any error resolving the subscription or counting current
    usage blocks the request (status=503, retryable) instead of allowing
    it through — a hard cap that can be silently bypassed by an unrelated
    DB error isn't actually a hard cap.
    """
    from apps.tenants.models import Subscription

    try:
        sub = Subscription.objects.using("default").get(tenant=tenant)
    except Subscription.DoesNotExist:
        logger.error("check_limit: no Subscription for tenant_id=%s", tenant.id)
        raise LimitCheckFailed(
            "Unable to verify your plan limits right now. Please try again shortly.",
            status=503,
        )

    limit_field = {"doctors": "max_doctors", "branches": "max_branches", "staff": "max_staff"}[resource]
    limit = getattr(sub, limit_field)
    if limit <= 0:
        return  # 0 = unlimited on this tier

    try:
        usage = get_usage_counts(db_name)
    except Exception as exc:
        logger.error("check_limit: usage count failed for %s (%s): %s", db_name, resource, exc)
        raise LimitCheckFailed(
            "Unable to verify your current usage right now. Please try again shortly.",
            status=503,
        )

    current = usage[resource]
    if current + increment > limit:
        label = LIMIT_LABELS[resource]
        plural = "" if limit == 1 else "s"
        raise LimitCheckFailed(
            f"{label.capitalize()} limit reached ({limit} {label}{plural} allowed on the "
            f"{sub.license_tier} plan). Please upgrade your plan to add more.",
            status=403,
        )
