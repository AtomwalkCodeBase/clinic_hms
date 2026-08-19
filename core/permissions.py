"""
core/permissions.py
-------------------
Reusable DRF permission classes for Atomwalk HMS.

Two types of permission:
  1. Role-based  — IsDoctor, IsNurse, IsFrontDesk, etc.
  2. Tier-based  — RequireTier('pro') factory

Usage in views:
    permission_classes = [IsAuthenticated, IsDoctor]
    permission_classes = [IsAuthenticated, IsFrontDesk, RequireTier('growth')]

Role-based checks pass for either of two things: the user's literal `role`
claim equals the role in question (the fast path — true for the 6 system
roles StaffUser.role can be), OR the user's `role` is "custom" and that role
key appears in their `acts_as` claim (a hospital-defined Role — see
apps.org.rbac.resolve_acts_as — that was explicitly built to act as that
identity, e.g. a solo-clinic "does everything" role). See _acts_as() below.
Platform admin and patient are never reachable via a custom Role (they're
not staff-side system roles), so IsPlatformAdmin/IsPatient stay pure literal
checks.
"""

from rest_framework.permissions import BasePermission

# ─── Tier ordering ─────────────────────────────────────────────────────────────
TIER_ORDER = ["starter", "growth", "pro", "enterprise"]

# ─── Role constants ────────────────────────────────────────────────────────────
ROLE_PLATFORM_ADMIN = "platform_admin"
ROLE_HOSPITAL_ADMIN = "hospital_admin"
ROLE_DOCTOR         = "doctor"
ROLE_NURSE          = "nurse"
ROLE_FRONT_DESK     = "front_desk"
ROLE_LAB_TECH       = "lab_tech"
ROLE_PHARMACIST     = "pharmacist"
ROLE_PATIENT        = "patient"


def _acts_as(user, *role_keys):
    """True if `user` is literally one of `role_keys`, or is role="custom"
    with any of `role_keys` in their acts_as claim (see module docstring)."""
    role = getattr(user, "role", None)
    if role in role_keys:
        return True
    if role != "custom":
        return False
    acts_as = getattr(user, "acts_as", None) or ()
    return any(k in acts_as for k in role_keys)


class IsPlatformAdmin(BasePermission):
    message = "Access restricted to Atomwalk platform administrators."
    def has_permission(self, request, view):
        return request.user.is_authenticated and getattr(request.user, "role", None) == ROLE_PLATFORM_ADMIN


class IsHospitalAdmin(BasePermission):
    message = "Access restricted to hospital administrators."
    def has_permission(self, request, view):
        return request.user.is_authenticated and _acts_as(request.user, ROLE_HOSPITAL_ADMIN)


class IsDoctor(BasePermission):
    message = "Access restricted to doctors."
    def has_permission(self, request, view):
        return request.user.is_authenticated and _acts_as(request.user, ROLE_DOCTOR)


class IsNurse(BasePermission):
    message = "Access restricted to nurses."
    def has_permission(self, request, view):
        return request.user.is_authenticated and _acts_as(request.user, ROLE_NURSE)


class IsFrontDesk(BasePermission):
    message = "Access restricted to front desk staff."
    def has_permission(self, request, view):
        return request.user.is_authenticated and _acts_as(request.user, ROLE_FRONT_DESK)


class IsLabTech(BasePermission):
    message = "Access restricted to lab technicians."
    def has_permission(self, request, view):
        return request.user.is_authenticated and _acts_as(request.user, ROLE_LAB_TECH)


class IsPharmacist(BasePermission):
    message = "Access restricted to pharmacists."
    def has_permission(self, request, view):
        return request.user.is_authenticated and _acts_as(request.user, ROLE_PHARMACIST)


class IsPatient(BasePermission):
    message = "Access restricted to patients."
    def has_permission(self, request, view):
        return request.user.is_authenticated and getattr(request.user, "role", None) == ROLE_PATIENT


class IsHospitalStaff(BasePermission):
    """Any authenticated hospital staff member (not platform admin, not patient)."""
    message = "Access restricted to hospital staff."
    STAFF_ROLES = {ROLE_HOSPITAL_ADMIN, ROLE_DOCTOR, ROLE_NURSE, ROLE_FRONT_DESK, ROLE_LAB_TECH, ROLE_PHARMACIST}

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        role = getattr(request.user, "role", None)
        # role="custom" is always hospital staff by definition — a custom
        # Role only ever exists inside a tenant DB and only ever gets
        # assigned to a StaffUser there, so there's no acts_as-emptiness
        # case where this should be False the way there is for the more
        # specific Is* checks above.
        return role in self.STAFF_ROLES or role == "custom"


class IsDoctorOrNurse(BasePermission):
    """Doctors and nurses share access to clinical input endpoints."""
    message = "Access restricted to doctors and nurses."
    def has_permission(self, request, view):
        return request.user.is_authenticated and _acts_as(request.user, ROLE_DOCTOR, ROLE_NURSE)


def RequireTier(minimum_tier: str):
    """
    Factory — returns a DRF permission class enforcing a minimum license tier.

    Args:
        minimum_tier: One of 'starter', 'growth', 'pro', 'enterprise'.

    Usage:
        permission_classes = [IsAuthenticated, IsDoctor, RequireTier('pro')]

    Prefer RequireFeature() below for gating an actual module (lab, pharmacy,
    etc.) — feat_* flags are the real per-tenant source of truth (see
    tenants.Subscription docstring) and can be overridden per hospital
    independent of tier, which a tier-name comparison can't express. This is
    kept for the rarer case of gating on tier itself.
    """
    if minimum_tier not in TIER_ORDER:
        raise ValueError(f"Invalid tier '{minimum_tier}'. Must be one of: {TIER_ORDER}")

    class TierPermission(BasePermission):
        message = (
            f"This feature requires the '{minimum_tier}' license tier or higher. "
            "Please upgrade your subscription to access this feature."
        )

        def has_permission(self, request, view):
            sub = getattr(request.user, "subscription", None)
            user_tier = sub.license_tier if sub else "starter"
            if user_tier not in TIER_ORDER:
                return False
            return TIER_ORDER.index(user_tier) >= TIER_ORDER.index(minimum_tier)

    TierPermission.__name__ = f"RequiresTier_{minimum_tier.capitalize()}"
    return TierPermission


def RequireFeature(flag_name: str):
    """
    Factory — returns a DRF permission class enforcing a boolean feature gate
    on the tenant's Subscription (e.g. 'feat_lab', 'feat_pharmacy').

    request.user.subscription is populated by JWTTenantAuthentication for any
    hospital-staff request (see core/authentication.py) — None for platform
    admin or patient requests, which this permission always denies (those
    endpoints should be using role-based permissions instead, not this one).

    Usage:
        permission_classes = [IsAuthenticated, IsHospitalStaff, RequireFeature('feat_lab')]
    """
    class FeaturePermission(BasePermission):
        message = (
            f"This hospital's plan doesn't include this feature ({flag_name}). "
            "Contact Atomwalk support to upgrade."
        )

        def has_permission(self, request, view):
            sub = getattr(request.user, "subscription", None)
            return bool(sub) and bool(getattr(sub, flag_name, False))

    FeaturePermission.__name__ = f"RequiresFeature_{flag_name}"
    return FeaturePermission
