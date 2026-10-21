"""apps/org/rbac.py"""

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
    "birth_history.record":      "Record/edit a pediatric patient's birth history",
    "milestone.record":           "Record a pediatric developmental-milestone assessment",
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
SYSTEM_ROLE_PERMISSIONS = {
    "hospital_admin": set(PERMISSION_CATALOG.keys()),  # oversight — everything
    "doctor": {
        "patient.view", "encounter.create", "encounter.sign",
        "prescription.create", "lab.order", "queue.manage", "profile.edit.own",
        "birth_history.record", "milestone.record",
    },
    "nurse": {
        "patient.view", "vitals.record", "queue.manage", "lab.order",
        "profile.edit.own", "milestone.record",
    },
    "front_desk": {
        "patient.register", "appointment.manage", "queue.manage",
        "billing.manage", "profile.edit.own", "birth_history.record",
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
ACTS_AS_CHOICES = [k for k in SYSTEM_ROLE_LABELS.keys()]


def resolve_acts_as(staff):
    """Which system-role identities this staff member should be treated as,"""
    if staff.role != "custom":
        return {staff.role} if staff.role else set()
    custom_role = getattr(staff, "custom_role", None)
    if not custom_role:
        return set()
    return set(custom_role.acts_as or [])


def get_effective_permissions(staff, db_name):
    """Union of:"""
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
        from apps.hospital_setup.models import UserRole
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
        logging.getLogger(__name__).warning(
            "get_effective_permissions: extra-role lookup failed for staff_id=%s db=%s",
            getattr(staff, "id", None), db_name, exc_info=True,
        )
    return codes


def has_permission(staff, code, db_name):
    return code in get_effective_permissions(staff, db_name)


def sync_roles_and_permissions(db):
    """Make a hospital database's permission and system-role rows match this file; runs after every migrate."""
    from apps.hospital_setup.models import Permission, Role, RolePermission

    permissions = {
        code: Permission.objects.using(db).update_or_create(code=code, defaults={"description": text})[0]
        for code, text in PERMISSION_CATALOG.items()
    }
    for key, label in SYSTEM_ROLE_LABELS.items():
        role = (Role.objects.using(db).filter(system_role_key=key).first()
                or Role.objects.using(db).filter(name=label).first())
        if role is None:
            role = Role.objects.using(db).create(name=label, is_system_role=True, system_role_key=key)
        elif not role.is_system_role or role.system_role_key != key:
            Role.objects.using(db).filter(pk=role.pk).update(is_system_role=True, system_role_key=key)
        wanted = set(SYSTEM_ROLE_PERMISSIONS.get(key, ()))
        have = set(RolePermission.objects.using(db).filter(role=role).values_list("permission__code", flat=True))
        RolePermission.objects.using(db).bulk_create(
            [RolePermission(role=role, permission=permissions[code]) for code in sorted(wanted - have)])
        if have - wanted:
            RolePermission.objects.using(db).filter(role=role, permission__code__in=have - wanted).delete()
    Permission.objects.using(db).exclude(code__in=PERMISSION_CATALOG).delete()
