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


def get_effective_permissions(staff, db_name):
    """
    Union of:
      - the default permission set for staff.role (the system role — always
        applies, this is the fast-path everyone already gets)
      - permissions granted by any extra Role rows assigned via UserRole
        (only meaningful for tenants using custom RBAC)

    Best-effort: never raises. A lookup failure just means "no extra
    permissions beyond the system default" — the caller falls back to the
    hardcoded role, so nothing breaks for the 95%+ of tenants that never
    touch custom roles.
    """
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
