# Contents, in the order they appear:
#   1. Constants           roles, modules, the initial password
#   2. Facility            Branch, NextNumber, Floor, Department, BranchDepartment, Room
#   3. Staff and access    UserGroup, StaffUser, StaffBranchAssignment, UserPermission
#   4. Option lists        OptionList
#   5. Compliance          RecordAmendment, AuditLog, NotificationLog
# The hospital's patients, their events and their documents are in apps/hospital_patients.

import uuid

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models, transaction
from django.utils.functional import cached_property

# ────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# The roles a user group can have, the modules a group can be given access to, and the password every new login starts with.
# ────────────────────────────────────────────────────────────────────────────

# Roles: one letter each, stored in UserGroup.role
ROLE_DOCTOR, ROLE_NURSE, ROLE_FRONT_DESK, ROLE_ADMIN, ROLE_ALL = ("d", "n", "f", "a", "l")
ROLE_CHOICES = [
    (ROLE_DOCTOR, "Doctor"),
    (ROLE_NURSE, "Nurse"),
    (ROLE_FRONT_DESK, "Front Desk"),
    (ROLE_ADMIN, "Admin (hospital admin)"),
    (ROLE_ALL, "All (single user, every permission)"),
]

# Modules: key -> (what it covers, the roles that always have it). UserPermission.modules stores the keys themselves,
# so adding or reordering modules here never changes what a group was already given.
MODULE_HEADERS = {
    "patients":   ("Patients: registration, search, history", (ROLE_DOCTOR, ROLE_NURSE, ROLE_FRONT_DESK)),
    "opd":        ("OPD: appointments, queue, vitals, consultation, prescriptions", (ROLE_DOCTOR, ROLE_NURSE, ROLE_FRONT_DESK)),
    "billing":    ("Billing: invoices, payments, price lists", (ROLE_FRONT_DESK,)),
    "facility":   ("Facility: branches, departments, floors, rooms", ()),
    "staff":      ("Staff: users, user groups, permissions, schedules", ()),
    "compliance": ("Compliance: record corrections, audit log", (ROLE_FRONT_DESK,)),
    "reports":    ("Reports: counts and summaries", (ROLE_DOCTOR, ROLE_FRONT_DESK)),
}
MODULES = tuple(MODULE_HEADERS)


def hospital_folder(instance_or_alias):
    """This hospital's folder in the bucket: hospital/<its database name>. Everything a hospital stores goes under it. Give it a row of the hospital or
    the alias of its database."""
    from django.db import connections
    from core.db_router import get_hospital_db
    alias = instance_or_alias if isinstance(instance_or_alias, str) else (instance_or_alias._state.db or get_hospital_db())
    return f"hospital/{connections[alias].settings_dict['NAME']}"


def staff_file_path(instance, filename):
    return f"{hospital_folder(instance)}/staff/{instance.user_id}/{filename}"

def new_temp_password(length=12):
    """A one-time password for a new or reset login (shown once to the admin and emailed); the staff member must change it at first sign-in."""
    import secrets
    import string
    chars = string.ascii_letters + string.digits + "!@#$"
    return "".join(secrets.choice(chars) for _ in range(length))


# ────────────────────────────────────────────────────────────────────────────
# FACILITY
# Where care happens: branches, floors, departments and rooms, and the number counters of each branch.
# ────────────────────────────────────────────────────────────────────────────

class Branch(models.Model):
    name       = models.CharField(max_length=200)
    branch_code = models.CharField(max_length=10, unique=True, null=True, blank=True)
    address    = models.TextField(blank=True)
    city       = models.CharField(max_length=100, blank=True)
    state      = models.CharField(max_length=100, blank=True)
    pincode    = models.CharField(max_length=10, blank=True)
    phone      = models.CharField(max_length=20, blank=True)
    lat        = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng        = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "branch"

    def __str__(self):
        return self.name


class NextNumber(models.Model):
    branch      = models.ForeignKey(Branch, on_delete=models.CASCADE, null=True, blank=True, related_name="b_number_counters")
    entity      = models.CharField(max_length=20)
    prefix      = models.CharField(max_length=10, default="")
    last_number = models.PositiveBigIntegerField(default=0)
    pad_length  = models.PositiveSmallIntegerField(default=6)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        db_table     = "next_number"
        constraints = [
            models.UniqueConstraint(fields=["branch", "entity"], name="uniq_counter_branch_entity"),
            models.UniqueConstraint(fields=["entity"], condition=models.Q(branch__isnull=True), name="uniq_counter_hospital_wide"),
        ]

    def __str__(self):
        return f"{self.prefix}{str(self.last_number).zfill(self.pad_length)}"

    # prefix and zero-padding a counter starts with; the hospital can change them on its row afterwards
    DEFAULTS = {"uhid": ("UHID-", 6), "invoice": ("INV-", 6), "prescription": ("RX-", 6), "queue": ("Q-", 4), "employee_id": ("EMP-", 6)}

    @classmethod
    def next(cls, branch_id, entity, using):
        """Atomically take the next number of a branch's counter: (formatted number, plain number). Counters are created on first use.
        A branch other than the hospital's first one adds its id to the text (UHID-B2-000001), so numbers stay unique hospital-wide."""
        if entity not in cls.DEFAULTS:
            raise ValueError(f"Unknown entity '{entity}'. Must be one of: {sorted(cls.DEFAULTS)}")
        prefix, pad = cls.DEFAULTS[entity]
        cls.objects.using(using).get_or_create(branch_id=branch_id, entity=entity, defaults={"prefix": prefix, "pad_length": pad, "last_number": 0})
        with transaction.atomic(using=using):
            counter = cls.objects.using(using).select_for_update().get(branch_id=branch_id, entity=entity)
            counter.last_number += 1
            counter.save(using=using, update_fields=["last_number"])
            infix = ""
            if branch_id:
                first = Branch.objects.using(using).order_by("pk").values_list("pk", flat=True).first()
                if first is not None and branch_id != first:
                    infix = f"B{branch_id}-"
            return f"{counter.prefix}{infix}{str(counter.last_number).zfill(counter.pad_length)}", counter.last_number


class Floor(models.Model):
    branch     = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="b_floors")
    name       = models.CharField(max_length=50)
    level      = models.IntegerField(default=0)
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "floor"
        constraints = [models.UniqueConstraint(fields=["branch", "name"], name="uniq_floor_branch_name")]
        ordering  = ["level", "name"]

    def __str__(self):
        return f"{self.name} ({self.branch.name})"

class Department(models.Model):
    name       = models.CharField(max_length=100)
    department_code = models.CharField(max_length=10, unique=True, null=True, blank=True)
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "department"
        ordering  = ["name"]

    def __str__(self):
        return self.name

class BranchDepartment(models.Model):
    branch     = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="b_departments")
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="d_branches")
    floor      = models.ForeignKey(Floor, on_delete=models.PROTECT, related_name="f_departments")
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "branch_department"
        constraints = [models.UniqueConstraint(fields=["branch", "department"], name="uniq_branch_department")]
        ordering  = ["branch__name", "department__name"]

    def __str__(self):
        return f"{self.branch.name} / {self.department.name}"

    def clean(self):
        if self.floor.branch_id != self.branch_id:
            raise ValidationError({"floor": "The floor belongs to a different branch."})

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

class Room(models.Model):
    floor      = models.ForeignKey(Floor, on_delete=models.PROTECT, related_name="f_rooms")
    branch_department = models.ForeignKey(BranchDepartment, on_delete=models.SET_NULL, null=True, blank=True, related_name="bdp_rooms")
    name       = models.CharField(max_length=100)
    room_type  = models.CharField(max_length=20, default="consultation")
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "room"
        constraints = [models.UniqueConstraint(fields=["floor", "name"], name="uniq_room_floor_name")]
        ordering  = ["floor__level", "name"]

    def __str__(self):
        return f"{self.name} ({self.floor.name}, {self.floor.branch.name})"


# ────────────────────────────────────────────────────────────────────────────
# STAFF AND ACCESS
# Who works here: user groups with their modules, and staff with their branches (each branch assignment also holds a doctor's weekly hours).
# ────────────────────────────────────────────────────────────────────────────

class UserGroup(models.Model):
    name      = models.CharField(max_length=50, unique=True)
    role      = models.CharField(max_length=1, choices=ROLE_CHOICES)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "user_group"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_role_display()})"

class StaffUser(models.Model):
    GENDER_CHOICES = [("M", "Male"), ("F", "Female"), ("O", "Other")]

    user_id              = models.UUIDField(unique=True, editable=False)
    user_group           = models.ForeignKey(UserGroup, on_delete=models.PROTECT, related_name="ug_staff")
    department           = models.ForeignKey(Department, on_delete=models.PROTECT, null=True, blank=True, related_name="d_staff")
    phone              = models.CharField(max_length=15, unique=True)
    employee_id          = models.CharField(max_length=50, unique=True, null=True, blank=True)
    date_of_birth        = models.DateField(null=True, blank=True)
    gender               = models.CharField(max_length=1, choices=GENDER_CHOICES, blank=True)
    photo                = models.FileField(upload_to=staff_file_path, blank=True)
    is_active            = models.BooleanField(default=True)
    must_change_password = models.BooleanField(default=True)
    date_joined          = models.DateTimeField(auto_now_add=True)

    registration_no      = models.CharField(max_length=50, blank=True)
    council_name         = models.CharField(max_length=150, blank=True)
    registration_expiry  = models.DateField(null=True, blank=True)
    qualification        = models.CharField(max_length=200, blank=True)
    experience_years     = models.PositiveSmallIntegerField(null=True, blank=True)
    bio                  = models.TextField(blank=True)
    languages            = models.CharField(max_length=200, blank=True)

    specialisation       = models.CharField(max_length=100, blank=True)
    consultation_fee     = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    followup_fee         = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    digital_signature    = models.FileField(upload_to=staff_file_path, blank=True)
    known_for            = models.CharField(max_length=300, blank=True)
    prescription_favourites = models.JSONField(default=dict, blank=True)
    updated_at           = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "staff_user"

    def __str__(self):
        return f"{self.get_full_name()} ({self.get_role()})"

    # The name and e-mail are kept once, on the login (the Django User in the shared database, found by user_id), and read from there.
    # first_name, last_name and email can be set like fields; they are written to the login when the staff member is saved.
    @cached_property
    def login(self):
        return User.objects.using("default").get(username=str(self.user_id))

    def _login_get(self, attr):
        if self.user_id is None:
            return self.__dict__.get("_new_login", {}).get(attr, "")
        return getattr(self.login, attr)

    def _login_set(self, attr, value):
        if self.user_id is None:
            self.__dict__.setdefault("_new_login", {})[attr] = value
        else:
            setattr(self.login, attr, value)
            self.__dict__["_login_changed"] = True

    first_name = property(lambda self: self._login_get("first_name"), lambda self, value: self._login_set("first_name", value))
    last_name  = property(lambda self: self._login_get("last_name"),  lambda self, value: self._login_set("last_name", value))
    email      = property(lambda self: self._login_get("email"),      lambda self, value: self._login_set("email", value))

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.email or self.phone

    def get_role(self):
        return self.user_group.role

    def save(self, *args, **kwargs):
        login = None
        pending = self.__dict__.get("_new_login", {})
        if self.user_id is None:
            self.user_id = uuid.uuid4()
            login = User.objects.db_manager("default").create_user(
                username=str(self.user_id), email=pending.get("email") or "", password=new_temp_password(),
                first_name=pending.get("first_name", ""), last_name=pending.get("last_name", ""))
            self.__dict__["login"] = login
            self.__dict__.pop("_new_login", None)
        try:
            super().save(*args, **kwargs)
        except Exception:
            if login is not None:
                login.delete()
                self.user_id = None
                self.__dict__.pop("login", None)
                self.__dict__["_new_login"] = pending
            raise
        if self.__dict__.pop("_login_changed", False):
            self.login.save(using="default")

class StaffBranchAssignment(models.Model):
    DAY_CHOICES = [
        (0, "Monday"), (1, "Tuesday"), (2, "Wednesday"),
        (3, "Thursday"), (4, "Friday"), (5, "Saturday"), (6, "Sunday"),
    ]

    staff      = models.ForeignKey(StaffUser, on_delete=models.CASCADE, related_name="u_branch_assignments")
    branch     = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="b_staff_assignments")
    # The department worked in at this branch. A staff member who works in two departments has one assignment for each; StaffUser.department
    # stays the primary one. Empty (older rows) means the staff member's primary department.
    department = models.ForeignKey(Department, on_delete=models.PROTECT, null=True, blank=True, related_name="d_staff_assignments")
    is_primary = models.BooleanField(default=False)
    slot_duration_minutes = models.PositiveSmallIntegerField(default=15)
    weekly_hours          = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "staff_branch_assignment"
        constraints = [
            models.UniqueConstraint(fields=["staff", "branch", "department"], name="uniq_staff_branch_department"),
            models.UniqueConstraint(fields=["staff", "branch"], condition=models.Q(department__isnull=True), name="uniq_staff_branch_no_department"),
            models.UniqueConstraint(fields=["staff"], condition=models.Q(is_primary=True), name="uniq_staff_primary_branch"),
            models.CheckConstraint(check=models.Q(slot_duration_minutes__gt=0), name="slot_duration_positive"),
        ]

    def __str__(self):
        return f"{self.staff.get_full_name()} @ {self.branch.name}"

def _valid_module_keys(value):
    unknown = [m for m in (value or []) if m not in MODULES]
    if not isinstance(value, list) or unknown:
        raise ValidationError(f"Unknown module(s): {unknown or value}. Allowed: {list(MODULES)}.")


class UserPermission(models.Model):
    """What a user group may use at one branch and department: the keys of the modules switched on (see MODULES); no row, or an empty list,
    means no access."""
    user_group        = models.ForeignKey(UserGroup, on_delete=models.CASCADE, related_name="ug_permissions")
    branch_department = models.ForeignKey(BranchDepartment, on_delete=models.CASCADE, related_name="bdp_permissions")
    modules           = models.JSONField(default=list, blank=True, validators=[_valid_module_keys])

    class Meta:
        db_table = "user_permission"
        constraints = [models.UniqueConstraint(fields=["user_group", "branch_department"], name="uniq_group_place")]

    def __str__(self):
        return f"{self.user_group.name}: {', '.join(self.modules) or 'no modules'} at {self.branch_department}"

    @staticmethod
    def pack(modules):
        """The stored value for some module keys: pack(["billing", "opd"]) is ["opd", "billing"] (in the order of MODULES, unknown keys dropped)."""
        return [module for module in MODULES if module in modules]

    def allowed(self):
        """The module keys this row gives access to."""
        return [module for module in MODULES if module in (self.modules or [])]

    def allows(self, module):
        return module in self.allowed()


# ────────────────────────────────────────────────────────────────────────────
# OPTION LISTS
# Dropdown lists a hospital can edit: service categories, payment modes, invoice statuses, room types and appointment types.
# ────────────────────────────────────────────────────────────────────────────
# not reviewed
class OptionList(models.Model):
    LIST_SERVICE_CATEGORY = "service_category"
    LIST_PAYMENT_MODE     = "payment_mode"
    LIST_INVOICE_STATUS   = "invoice_status"
    LIST_ROOM_TYPE        = "room_type"
    LIST_APPOINTMENT_TYPE = "appointment_type"
    LIST_TYPE_CHOICES = [
        (LIST_SERVICE_CATEGORY, "Service Category"),
        (LIST_PAYMENT_MODE, "Payment Mode"),
        (LIST_INVOICE_STATUS, "Invoice Status"),
        (LIST_ROOM_TYPE, "Room Type"),
        (LIST_APPOINTMENT_TYPE, "Appointment Type"),
    ]

    list_type    = models.CharField(max_length=20, choices=LIST_TYPE_CHOICES)
    value        = models.CharField(max_length=20)
    label        = models.CharField(max_length=50)
    is_active    = models.BooleanField(default=True)
    is_system    = models.BooleanField(default=False)
    sort_order   = models.PositiveSmallIntegerField(default=0)
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "option_list"
        ordering  = ["list_type", "sort_order", "label"]
        constraints = [
            models.UniqueConstraint(fields=["list_type", "value"], name="uniq_option_list_type_value"),
        ]

    def __str__(self):
        return f"{self.list_type}:{self.label}"


# ────────────────────────────────────────────────────────────────────────────
# COMPLIANCE
# Records that must be kept as they were: record corrections, the audit trail and notifications.
# ────────────────────────────────────────────────────────────────────────────
# not reviewed
class RecordAmendment(models.Model):
    STATUS_CHOICES = [
        ("pending",  "Pending Review"),
        ("approved", "Approved and Applied"),
        ("rejected", "Rejected with Reason"),
    ]

    patient         = models.ForeignKey("hospital_patients.HospitalPatient", on_delete=models.PROTECT,
                                        related_name="p_amendments")
    resource_type   = models.CharField(max_length=50)
    resource_id     = models.CharField(max_length=64)
    field_name      = models.CharField(max_length=100)
    current_value   = models.TextField(blank=True)
    requested_value = models.TextField()
    reason          = models.TextField(blank=True)
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    reviewed_by     = models.ForeignKey(StaffUser, on_delete=models.SET_NULL,
                                        null=True, blank=True, related_name="u_reviewed_amendments")
    review_notes    = models.TextField(blank=True)
    requested_at    = models.DateTimeField(auto_now_add=True)
    resolved_at     = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table  = "record_amendment"
        ordering  = ["-requested_at"]

    def __str__(self):
        return f"Amendment #{self.id} — {self.resource_type} ({self.status})"


# not reviewed
class AuditLogQuerySet(models.QuerySet):
    """An audit entry is never edited or deleted, not even in bulk (the database refuses it too: see migration 0003)."""
    def update(self, **kwargs):
        raise ValueError("An audit entry is never edited.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValueError("An audit entry is never edited.")

    def delete(self):
        raise ValueError("An audit entry is never deleted.")


class AuditLog(models.Model):
    actor_user_id = models.BigIntegerField(null=True, blank=True)       # the id of the Django login (auth User), not StaffUser.user_id (a UUID)
    actor_email   = models.CharField(max_length=255, blank=True)
    actor_role    = models.CharField(max_length=30, blank=True)
    action        = models.CharField(max_length=50)
    resource_type = models.CharField(max_length=50, blank=True)
    resource_id   = models.CharField(max_length=64, blank=True)
    patient       = models.ForeignKey("hospital_patients.HospitalPatient", on_delete=models.SET_NULL, null=True, blank=True, related_name="p_audit_logs")
    ip_address    = models.GenericIPAddressField(null=True, blank=True)
    metadata      = models.JSONField(default=dict, blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)

    objects = AuditLogQuerySet.as_manager()

    class Meta:
        db_table  = "audit_log"
        ordering  = ["-created_at"]

    def __str__(self):
        return f"{self.action} by {self.actor_email or self.actor_user_id} @ {self.created_at}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("An audit entry is never edited.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("An audit entry is never deleted.")


# not reviewed
class NotificationLog(models.Model):
    STATUS_CHOICES = [
        ("queued",    "Queued"),
        ("sent",      "Sent"),
        ("delivered", "Delivered"),
        ("failed",    "Failed"),
    ]

    CHANNEL_CHOICES = [("in_app", "In-app"), ("sms", "SMS"), ("email", "Email"), ("whatsapp", "WhatsApp")]

    patient      = models.ForeignKey("hospital_patients.HospitalPatient", on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="p_notifications")

    recipient    = models.CharField(max_length=200)
    channel      = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    body         = models.TextField()
    status       = models.CharField(max_length=20, choices=STATUS_CHOICES, default="queued")
    error        = models.TextField(blank=True)
    sent_at      = models.DateTimeField(null=True, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    reference    = models.CharField(max_length=100, blank=True)
    read_at      = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table  = "notification_log"
        ordering  = ["-created_at"]

    def __str__(self):
        return f"{self.channel} to {self.recipient} ({self.status})"
