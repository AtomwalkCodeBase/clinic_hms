"""apps/org/services.py"""

# NextNumber entity config: (entity_key, prefix, pad_length)
_NextNumber_ENTITIES = [
    ("uhid",         "UHID-", 6),
    ("invoice",      "INV-",  6),
    ("prescription", "RX-",   6),
    ("queue",        "Q-",    4),
]


def seed_next_numbers(branch_id: int, db_name: str) -> None:
    """Create NextNumber counter rows for a new branch (idempotent — skips if already exist)."""
    from apps.hospital_setup.models import NextNumber
    for entity, prefix, pad in _NextNumber_ENTITIES:
        NextNumber.objects.using(db_name).get_or_create(
            branch_id=branch_id,
            entity=entity,
            defaults={"prefix": prefix, "pad_length": pad, "last_number": 0},
        )


def next_employee_id(db_name: str) -> str:
    """Auto-generate the next Employee ID via NextNumber — see core/utils/nntm.py and"""
    from apps.hospital_setup.models import NextNumber
    from apps.hospital_setup.models import NextNumber

    NextNumber.objects.using(db_name).get_or_create(
        branch=None, entity="employee_id",
        defaults={"prefix": "EMP-", "pad_length": 6, "last_number": 0},
    )
    formatted_id, _ = NextNumber.next(None, "employee_id", db_name)
    return formatted_id


def login_of(staff):
    from django.contrib.auth.models import User
    return User.objects.using("default").get(username=str(staff.user_id))


def attach_logins(staff_list):
    """Load the logins of these staff in one query, so reading their name and e-mail does not query once per person. Returns the list."""
    import uuid
    from django.contrib.auth.models import User
    staff_list = list(staff_list)
    logins = {user.username: user for user in User.objects.using("default").filter(username__in=[str(s.user_id) for s in staff_list])}
    for staff in staff_list:
        if str(staff.user_id) in logins:
            staff.__dict__["login"] = logins[str(staff.user_id)]
    return staff_list


def by_name(staff_list):
    """These staff, sorted by first and last name (kept on the login)."""
    return sorted(attach_logins(staff_list), key=lambda s: (s.first_name.lower(), s.last_name.lower()))


def name_or_email_q(text):
    """A filter for the staff whose name or e-mail contains `text`; these are kept on the login, so the logins are searched first."""
    import uuid
    from django.contrib.auth.models import User
    from django.db.models import Q
    usernames = User.objects.using("default").filter(
        Q(first_name__icontains=text) | Q(last_name__icontains=text) | Q(email__icontains=text)).values_list("username", flat=True)
    return Q(user_id__in=[uuid.UUID(name) for name in usernames])


def set_login_password(staff, raw_password):
    login = login_of(staff)
    login.set_password(raw_password)
    login.save(using="default", update_fields=["password"])


def check_login_password(staff, raw_password):
    return login_of(staff).check_password(raw_password)


def doctor_details(staff):
    return {
        "name": staff.get_full_name(), "specialisation": staff.specialisation, "qualification": staff.qualification,
        "experience_years": staff.experience_years, "consultation_fee": str(staff.consultation_fee) if staff.consultation_fee is not None else None,
        "bio": staff.bio, "languages": staff.languages, "known_for": staff.known_for,
    }


def sync_catalog(staff, hospital_id):
    """Keep the shared sign-in catalog (mobile or email -> hospital -> login) in step with the staff row."""
    from apps.hospital_master.models import GlobalStaffUserIndexCatalog
    from apps.hospital_setup.models import ROLE_DOCTOR
    from apps.hospital_setup.rbac import resolve_acts_as
    login = staff.login
    is_doctor = "doctor" in resolve_acts_as(staff) and staff.get_role() == ROLE_DOCTOR
    GlobalStaffUserIndexCatalog.objects.using("default").update_or_create(
        user_id=login.pk,
        defaults={"mobile": staff.phone, "email": staff.email or None, "hospital_id": hospital_id,
                  "is_doctor": is_doctor, "doctor_details": doctor_details(staff) if is_doctor else {}},
    )


def create_staff(db_name, hospital_id, role, password=None, **fields):
    """A staff member of a hospital in the user group of `role` (doctor, nurse, front_desk, hospital_admin): the login,
    the staff row and the catalog entry. The password is the initial one unless given."""
    from apps.hospital_setup.models import StaffUser
    from apps.hospital_setup.rbac import system_role
    group = fields.pop("user_group", None) or system_role(db_name, role)
    staff = StaffUser(user_group=group, **fields)
    staff.save(using=db_name)
    if password:
        set_login_password(staff, password)
    sync_catalog(staff, hospital_id)
    return staff


def last_logins(staff_list):
    """{staff user_id: last sign-in} for these staff, from the Django users in one query."""
    import uuid
    from django.contrib.auth.models import User
    found = User.objects.using("default").filter(username__in=[str(s.user_id) for s in staff_list]).values_list("username", "last_login")
    return {uuid.UUID(username): last_login for username, last_login in found}
