"""
apps/org/rbac.py
-----------------
Table-driven RBAC helpers — see docs/onboarding_auth_rbac_architecture.md 4.3.

Two things live here:
  PERMISSION_CATALOG        — the fixed, deploy-time list of grantable actions.
  SYSTEM_ROLE_PERMISSIONS   — which of those every one of the 6 system roles
                               grants by default (mirrors the hardcoded Is*
                               DRF permission classes in core/permissions.py —
                               this is a parallel, additive description of
                               the same reality, not a replacement for them).

Both are consumed by the 0013 migration's data-seeding step (to populate the
`permission` and `role`/`role_permission` tables in every tenant DB) and by
get_effective_permissions() below, which a view can call when it wants to
check something finer-grained than "is this a doctor" — e.g. whether THIS
particular staff member (who might hold an extra custom role on top of their
primary one) can do X. Most endpoints don't need this and should keep using
the existing Is* fast-path classes; reach for this only for genuinely
per-tenant-configurable checks.
"""

import logging

PERMISSION_CATALOG = {
    "patient.view":          "View patient records",
    "patient.register":      "Register new patients",
    "encounter.create":      "Create consultation notes",
    "encounter.sign":        "Sign/finalise consultation notes",
    "prescription.create":   "Prescribe medicines",
    "prescription.dispense": "Dispense prescriptions",
    "lab.order":              "Order lab tests",
    "lab.catalog.manage":     "Manage the lab test catalog",
    "lab.process":             "Process lab requests",
    "lab.report.upload":       "Upload/deliver lab reports",
    "vitals.record":            "Record patient vitals",
    "appointment.manage":        "Create/manage appointments",
    "queue.manage":               "Manage the check-in / consultation queue",
    "billing.manage":              "Handle billing intake and transactions",
    "staff.manage":                  "Invite, edit, deactivate staff",
    "branch.manage":                  "Create/edit branches and departments",
    "role.manage":                     "Create/edit custom roles (enterprise)",
    "subscription.view":                "View hospital subscription/usage",
    "profile.edit.own":                   "Edit own profile",
}

# System role key -> set of permission codes it grants by default. Keys must
# match StaffUser.ROLE_CHOICES exactly (used to resolve a staff member's
# primary role to a permission set without needing a UserRole row).
SYSTEM_ROLE_PERMISSIONS = {
    "hospital_admin": set(PERMISSION_CATALOG.keys()),  # oversight — everything
    "doctor": {
        "patient.view", "encounter.create", "encounter.sign",
        "prescription.create", "lab.order", "queue.manage", "profile.edit.own",
    },
    "nurse": {
        "patient.view", "vitals.record", "queue.manage", "lab.order",
        "profile.edit.own",
    },
    "front_desk": {
        "patient.register", "appointment.manage", "queue.manage",
        "billing.manage", "profile.edit.own",
    },
    "lab_tech": {
        "lab.catalog.manage", "lab.process", "lab.report.upload",
        "profile.edit.own",
    },
    "pharmacist": {
        "prescription.dispense", "billing.manage", "profile.edit.own",
    },
}

SYSTEM_ROLE_LABELS = {
    "hospital_admin": "Hospital Admin",
    "doctor":         "Doctor",
    "nurse":          "Nurse",
    "front_desk":     "Front Desk",
    "lab_tech":       "Lab Technician",
    "pharmacist":     "Pharmacist",
}

# Keys a Role.acts_as list may legally contain — the same 6 system roles a
# StaffUser.role can be, minus "custom" itself (a custom role can't act as
# "custom", that's not a real identity).
ACTS_AS_CHOICES = [k for k in SYSTEM_ROLE_LABELS.keys()]


def resolve_acts_as(staff):
    """
    Which system-role identities this staff member should be treated as,
    for every "is this person a doctor/nurse/..." check throughout the app
    (core.permissions Is* classes, DoctorListView, tenants.limits doctor
    counting, patient-facing doctor search, etc.) — not just permission
    codes, but actual identity/discoverability.

    - System-role staff (role in the fixed 6): always exactly {staff.role}.
      A doctor is a doctor; this never depends on custom_role even if one
      happens to be set (it shouldn't be, but this keeps the fast path
      correct regardless).
    - Custom-role staff (role="custom"): whatever their custom_role.acts_as
      says — e.g. ["doctor", "nurse", "front_desk"] for a solo-clinic role.
      Empty list (not an error) if custom_role is somehow unset — degrades
      to "acts as nothing", not "acts as everything".

    Always returns a set; never raises.
    """
    if staff.role != "custom":
        return {staff.role} if staff.role else set()
    custom_role = getattr(staff, "custom_role", None)
    if not custom_role:
        return set()
    return set(custom_role.acts_as or [])


def get_effective_permissions(staff, db_name):
    """
    Union of:
      - the default permission set for staff.role (the system role — always
        applies, this is the fast-path everyone already gets), OR for
        role="custom", the permission codes granted directly by
        staff.custom_role (its own Role.permissions — not inferred from
        acts_as, so a custom role can grant a permission without claiming
        the matching identity, or vice versa)
      - permissions granted by any extra Role rows assigned via UserRole
        (only meaningful for tenants using custom RBAC)

    Best-effort: never raises. A lookup failure just means "no extra
    permissions beyond the system default" — the caller falls back to the
    hardcoded role, so nothing breaks for the 95%+ of tenants that never
    touch custom roles.
    """
    if staff.role == "custom":
        custom_role = getattr(staff, "custom_role", None)
        if custom_role:
            try:
                codes = set(custom_role.permissions.using(db_name).values_list("code", flat=True))
            except Exception:
                logging.getLogger(__name__).warning(
                    "get_effective_permissions: custom_role permission lookup failed "
                    "for staff_id=%s db=%s", getattr(staff, "id", None), db_name, exc_info=True,
                )
                codes = set()
        else:
            codes = set()
    else:
        codes = set(SYSTEM_ROLE_PERMISSIONS.get(staff.role, ()))
    try:
        from .models import UserRole
        extra_roles = (
            UserRole.objects.using(db_name)
            .filter(staff_id=staff.id)
            .select_related("role")
            .prefetch_related("role__permissions")
        )
        for ur in extra_roles:
            codes.update(ur.role.permissions.using(db_name).values_list("code", flat=True))
    except Exception:
        # Degrades to system-default permissions on any lookup failure — by
        # design, since custom roles are an enterprise add-on and most
        # tenants never touch this path. But a real bug here (e.g. a schema
        # drift breaking UserRole/Role joins) would otherwise be completely
        # silent, surfacing only as "my custom permissions aren't working"
        # support tickets with nothing in the logs to go on.
        logging.getLogger(__name__).warning(
            "get_effective_permissions: extra-role lookup failed for staff_id=%s db=%s",
            getattr(staff, "id", None), db_name, exc_info=True,
        )
    return codes


def has_permission(staff, code, db_name):
    return code in get_effective_permissions(staff, db_name)
