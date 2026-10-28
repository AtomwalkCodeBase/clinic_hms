"""core/api/permissions.py"""

from rest_framework.permissions import BasePermission

# ─── Tier ordering ─────────────────────────────────────────────────────────────
TIER_ORDER = ["starter", "growth", "pro", "enterprise"]

# ─── Role constants ────────────────────────────────────────────────────────────
ROLE_PLATFORM_ADMIN = "platform_admin"
ROLE_HOSPITAL_ADMIN = "hospital_admin"
ROLE_ALL            = "all"
ROLE_DOCTOR         = "doctor"
ROLE_NURSE          = "nurse"
ROLE_FRONT_DESK     = "front_desk"
ROLE_PATIENT        = "patient"


def _acts_as(user, *role_keys):
    """True if `user` has one of `role_keys` as their role, or in the roles they act as (a user group with the role "all" acts as every role)."""
    if getattr(user, "role", None) in role_keys:
        return True
    return any(k in (getattr(user, "acts_as", None) or ()) for k in role_keys)


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


class IsPatient(BasePermission):
    message = "Access restricted to patients."
    def has_permission(self, request, view):
        return request.user.is_authenticated and getattr(request.user, "role", None) == ROLE_PATIENT


class IsHospitalStaff(BasePermission):
    """Any authenticated hospital staff member (not platform admin, not patient)."""
    message = "Access restricted to hospital staff."
    STAFF_ROLES = {ROLE_HOSPITAL_ADMIN, ROLE_ALL, ROLE_DOCTOR, ROLE_NURSE, ROLE_FRONT_DESK}

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return getattr(request.user, "role", None) in self.STAFF_ROLES


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

    TierPermission.is_gate = True
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

    FeaturePermission.is_gate = True
    FeaturePermission.__name__ = f"RequiresFeature_{flag_name}"
    return FeaturePermission


# ─── Modules ───────────────────────────────────────────────────────────────────
# A user group can be granted modules beyond its role (UserPermission). A granted module opens that module's endpoints to the group's
# staff whatever their role; the plan's feature and tier gates still apply. A role's own access does not depend on modules.

def granted_modules(request):
    """The modules the signed-in staff member's user group was granted, read from the hospital database once per request."""
    modules = getattr(request, "_granted_modules", None)
    if modules is None:
        user = request.user
        if getattr(user, "is_authenticated", False) and getattr(user, "role", None) in IsHospitalStaff.STAFF_ROLES:
            from apps.hospital_setup.models import UserPermission
            from apps.hospital_setup.rbac import modules_of
            modules = frozenset(modules_of(UserPermission.objects.using(request.hospital_db).filter(
                user_group__ug_staff__pk=user.pk).values_list("modules", flat=True)))
        else:
            modules = frozenset()
        request._granted_modules = modules
    return modules


def in_module(view_class, *modules):
    """The same view, also open to staff whose user group was granted one of `modules`. Only the plan's gates are still checked for them."""
    class ModuleView(view_class):
        def check_permissions(self, request):
            if granted_modules(request).intersection(modules):
                for permission in self.get_permissions():
                    if getattr(permission, "is_gate", False) and not permission.has_permission(request, self):
                        self.permission_denied(request, message=getattr(permission, "message", None))
                return
            super().check_permissions(request)

    ModuleView.__name__, ModuleView.__qualname__, ModuleView.__module__, ModuleView.__doc__ = (
        view_class.__name__, view_class.__qualname__, view_class.__module__, view_class.__doc__)
    return ModuleView
