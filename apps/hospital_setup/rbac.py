"""apps/org/rbac.py"""

import logging

from django.db.models import Q

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


def acts_as_q(*role_keys, prefix=""):
    """A filter for the staff who are one of these system roles, or hold a role the hospital defined that acts as one of them.

    `prefix` reaches the staff row from another model: acts_as_q("doctor", prefix="doctor__")."""
    system = Q(**{f"{prefix}group__is_system_role": True, f"{prefix}group__system_role_key__in": role_keys})
    custom = Q(**{f"{prefix}group__is_system_role": False})
    acts = Q()
    for key in role_keys:
        acts |= Q(**{f"{prefix}group__acts_as__contains": [key]})
    return system | (custom & acts)


def role_q(key, prefix=""):
    """A filter for the staff whose own user group is this system role exactly; "custom" is any role the hospital defined."""
    if key == "custom":
        return Q(**{f"{prefix}group__is_system_role": False})
    return Q(**{f"{prefix}group__is_system_role": True, f"{prefix}group__system_role_key": key})


def system_role(db_name, key):
    """The system role row (doctor, nurse...) of a hospital database: the user group a staff member of that role belongs to."""
    from apps.hospital_setup.models import Role
    return Role.objects.using(db_name).get(is_system_role=True, system_role_key=key)


def resolve_acts_as(staff):
    """Which system-role identities this staff member should be treated as,"""
    group = staff.group
    if group.is_system_role:
        return {group.system_role_key} if group.system_role_key else set()
    return set(group.acts_as or [])


def get_effective_permissions(staff, db_name):
    """Union of:"""
    group = staff.group
    if not group.is_system_role:
        try:
            codes = set(group.permissions.using(db_name).values_list("code", flat=True))
        except Exception:
            logging.getLogger(__name__).warning(
                "get_effective_permissions: custom_role permission lookup failed "
                "for staff_id=%s db=%s", getattr(staff, "id", None), db_name, exc_info=True,
            )
            codes = set()
    else:
        codes = set(SYSTEM_ROLE_PERMISSIONS.get(group.system_role_key, ()))
    try:
        for role in staff.extra_roles.using(db_name).all():
            codes.update(role.permissions.using(db_name).values_list("code", flat=True))
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
    from apps.hospital_setup.models import Permission, Role

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
        have = set(role.permissions.using(db).values_list("code", flat=True))
        role.permissions.add(*[permissions[code] for code in sorted(wanted - have)])
        if have - wanted:
            role.permissions.remove(*Permission.objects.using(db).filter(code__in=have - wanted))
    Permission.objects.using(db).exclude(code__in=PERMISSION_CATALOG).delete()
