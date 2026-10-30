from django.db.models import Q

from apps.hospital_setup.models import (
    MODULE_HEADERS, MODULES, ROLE_ADMIN, ROLE_ALL, ROLE_CHOICES, ROLE_DOCTOR, ROLE_FRONT_DESK, ROLE_NURSE,
)

# The name of each role in the API and in the sign-in token (the stored role is one letter). A hospital's admin is the Admin role.
ROLE_KEY = {
    ROLE_DOCTOR: "doctor", ROLE_NURSE: "nurse", ROLE_FRONT_DESK: "front_desk",
    ROLE_ADMIN: "hospital_admin", ROLE_ALL: "all",
}
GROUP_ROLE = {key: role for role, key in ROLE_KEY.items()}
ROLE_LABELS = {ROLE_KEY[role]: label for role, label in ROLE_CHOICES}
ACTS_AS_ALL = ["doctor", "nurse", "front_desk"]

# What each role can act as, besides itself: "all" is every role, an admin runs the hospital but is not a doctor, nurse or front desk.
_ACTS_AS = {ROLE_ALL: ["hospital_admin", *ACTS_AS_ALL]}


def api_role(staff):
    return ROLE_KEY[staff.get_role()]


def resolve_acts_as(staff):
    role = staff.get_role()
    return {ROLE_KEY[role], *_ACTS_AS.get(role, ())}


def jwt_acts_as(staff):
    return list(_ACTS_AS.get(staff.get_role(), ()))


def acts_as_q(*role_keys, prefix=""):
    """Staff who act as any of these roles: those with the role itself and those whose role covers it."""
    roles = {role for role in ROLE_KEY if ROLE_KEY[role] in role_keys or set(_ACTS_AS.get(role, ())) & set(role_keys)}
    return Q(**{f"{prefix}user_group__role__in": roles})


def role_q(key, prefix=""):
    return Q(**{f"{prefix}user_group__role": GROUP_ROLE[key]}) if key in GROUP_ROLE else Q(pk__in=[])


def system_role(db_name, key):
    from apps.hospital_setup.models import UserGroup
    group = UserGroup.objects.using(db_name).filter(role=GROUP_ROLE[key]).order_by("pk").first()
    return group or UserGroup.objects.using(db_name).create(name=ROLE_LABELS[key], role=GROUP_ROLE[key])


def default_modules(role_key):
    """The modules a role always has (a role key as in the API: doctor, nurse, front_desk, hospital_admin, all)."""
    role = GROUP_ROLE.get(role_key)
    if role in (ROLE_ALL, ROLE_ADMIN):
        return set(MODULE_HEADERS)
    return {module for module, (_header, roles) in MODULE_HEADERS.items() if role in roles}


def modules_of(rows):
    """The module keys switched on in any of these lists (the `modules` of UserPermission rows)."""
    return {module for keys in rows for module in keys if module in MODULES}


def granted_module_names(staff, db_name):
    """The modules beyond their role's own that the staff member's user group was granted."""
    from apps.hospital_setup.models import UserPermission
    return modules_of(UserPermission.objects.using(db_name).filter(user_group_id=staff.user_group_id).values_list("modules", flat=True))


def get_effective_modules(staff, db_name):
    """The modules of a staff member: their role's own plus the ones their user group was granted."""
    return default_modules(api_role(staff)) | granted_module_names(staff, db_name)


def sync_roles_and_permissions(db):
    for key in ROLE_LABELS:
        system_role(db, key)
