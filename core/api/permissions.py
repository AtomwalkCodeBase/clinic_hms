"""core/api/permissions.py"""

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
        return role in self.STAFF_ROLES or role == "custom"


class IsDoctorOrNurse(BasePermission):
    """Doctors and nurses share access to clinical input endpoints."""
    message = "Access restricted to doctors and nurses."
    def has_permission(self, request, view):
        return request.user.is_authenticated and _acts_as(request.user, ROLE_DOCTOR, ROLE_NURSE)


class IsDoctorOrFrontDesk(BasePermission):
    """Doctor + front desk share write access to pediatric Birth History —"""
    message = "Access restricted to front desk staff and doctors."
    def has_permission(self, request, view):
        return request.user.is_authenticated and _acts_as(request.user, ROLE_DOCTOR, ROLE_FRONT_DESK)


def RequireTier(minimum_tier: str):
    """Factory — returns a DRF permission class enforcing a minimum license tier."""
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
    """Factory — returns a DRF permission class enforcing a boolean feature gate"""
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
