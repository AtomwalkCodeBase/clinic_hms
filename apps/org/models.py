"""
apps/org/models.py
------------------
Tenant DB models for organisational structure.

Tables: Branch, Department, StaffUser, DoctorProfile

Notes:
  - StaffUser extends Django's User (stored per-tenant).
  - set_unusable_password() is called on creation — staff set their own passwords
    via the self-service setup-password endpoint.
  - Branch.lat/lng for map display.
"""

from django.contrib.auth.hashers import make_password, check_password
from django.db import models


class NextNumber(models.Model):
    """
    NNTM — Next Number Table Manager.
    One row per (branch, entity) pair. Lives in tenant DB (app_label="org").
    get_next_number() in core/utils/nntm.py uses SELECT FOR UPDATE for uniqueness.

    Entities: uhid, invoice, lab_report, prescription, queue
    """
    branch_id   = models.IntegerField(db_index=True)
    entity      = models.CharField(max_length=20)
    prefix      = models.CharField(max_length=10, default="")
    last_number = models.PositiveBigIntegerField(default=0)
    pad_length  = models.PositiveSmallIntegerField(default=6)

    class Meta:
        app_label    = "org"
        db_table     = "next_number"
        unique_together = [("branch_id", "entity")]

    def __str__(self):
        return f"{self.prefix}{str(self.last_number).zfill(self.pad_length)}"


class Branch(models.Model):
    """A physical location of the hospital."""
    name        = models.CharField(max_length=200)
    address     = models.TextField(blank=True)
    city        = models.CharField(max_length=100, blank=True)
    state       = models.CharField(max_length=100, blank=True)
    pincode     = models.CharField(max_length=10, blank=True)
    phone       = models.CharField(max_length=20, blank=True)
    lat         = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng         = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "org"
        db_table  = "branch"

    def __str__(self):
        return self.name


class Department(models.Model):
    branch      = models.ForeignKey(Branch, on_delete=models.CASCADE,
                                    related_name="departments")
    name        = models.CharField(max_length=100)
    is_active   = models.BooleanField(default=True)

    class Meta:
        app_label = "org"
        db_table  = "department"
        unique_together = [("branch", "name")]

    def __str__(self):
        return f"{self.branch.name} / {self.name}"


class StaffUser(models.Model):
    """
    Per-tenant staff user. Plain Django model (not AUTH_USER_MODEL).
    Passwords are stored as Django-hashed strings but NEVER set by admin —
    staff use the invite + setup-password flow.

    role choices must match JWT role claims and frontend ROLES constants.

    Login identifier is phone (mobile number), not email — see
    registry.StaffMobileIndex. email is kept as an optional field (still
    useful for notifications/records) but is no longer required or used to
    route login.
    """
    ROLE_CHOICES = [
        ("hospital_admin", "Hospital Admin"),
        ("doctor",         "Doctor"),
        ("nurse",          "Nurse"),
        ("front_desk",     "Front Desk"),
        ("lab_tech",       "Lab Technician"),
        ("pharmacist",     "Pharmacist"),
    ]

    # Optional now — phone is the login identifier. null=True (not just
    # blank=True) so multiple staff with no email don't collide under the
    # unique constraint (Postgres allows many NULLs, not many '').
    email       = models.EmailField(unique=True, blank=True, null=True)
    first_name  = models.CharField(max_length=150, blank=True)
    last_name   = models.CharField(max_length=150, blank=True)
    password    = models.CharField(max_length=128, default="!")  # "!" = unusable
    role        = models.CharField(max_length=30, choices=ROLE_CHOICES)
    branch      = models.ForeignKey(Branch, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="staff")
    department  = models.ForeignKey(Department, on_delete=models.SET_NULL,
                                    null=True, blank=True)
    phone               = models.CharField(max_length=20, unique=True)
    # Optional secondary login identifier for hospitals that already run an
    # HR/payroll system with employee IDs (enterprise tier mainly). Unlike
    # phone, this is only unique WITHIN this tenant's own database — two
    # hospitals can both have an "EMP-001" — so logging in with it requires
    # a tenant hint (hospital subdomain) that mobile-based login doesn't
    # need. See StaffLoginView / docs/onboarding_auth_rbac_architecture.md 3.1.2.
    employee_id         = models.CharField(max_length=50, unique=True, null=True, blank=True)
    date_of_birth       = models.DateField(null=True, blank=True)
    is_active           = models.BooleanField(default=True)
    must_change_password = models.BooleanField(default=False)
    date_joined         = models.DateTimeField(auto_now_add=True)
    last_login          = models.DateTimeField(null=True, blank=True)

    # Self-service profile photo — common to every staff role (doctor, nurse,
    # front desk, lab tech, pharmacist, hospital admin). Stored as a base64
    # data URI (no object storage configured yet); uploaded by the staff
    # member themselves via MyStaffProfileView, never set by the admin.
    photo               = models.TextField(blank=True)

    class Meta:
        app_label = "org"
        db_table  = "staff_user"

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.email

    def set_unusable_password(self):
        self.password = "!"

    def set_password(self, raw_password):
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        return check_password(raw_password, self.password)

    def __str__(self):
        return f"{self.get_full_name()} ({self.role})"


class StaffBranchMapping(models.Model):
    """
    Which branches a staff member works at — a doctor commonly works more
    than one (e.g. Tue/Thu at the city branch, Sat at the suburb branch).
    Everyone else (nurse/front_desk/lab_tech/pharmacist/hospital_admin)
    realistically stays single-branch in practice, but nothing here
    prevents assigning them more than one if a hospital wants to.

    `StaffUser.branch` (the legacy single FK) is kept in sync as the
    "primary" branch — it's still what JWT payloads carry as the
    `branch_id` claim, and what every branch-scoped read that hasn't been
    updated to consult this table falls back to. Adding a branch here
    doesn't change default scoping for anyone; it only makes the *extra*
    branches selectable (e.g. via an explicit ?branch_id= a doctor is
    validated as actually being assigned to — see apps/opd/views.py).
    """
    staff       = models.ForeignKey(StaffUser, on_delete=models.CASCADE,
                                    related_name="branch_mappings")
    branch      = models.ForeignKey(Branch, on_delete=models.CASCADE,
                                    related_name="staff_mappings")
    is_primary  = models.BooleanField(default=False)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "org"
        db_table  = "staff_branch_mapping"
        constraints = [
            models.UniqueConstraint(fields=["staff", "branch"], name="uniq_staff_branch"),
            # At most one primary branch per staff member (Postgres partial
            # unique index — a staff row with zero mappings, or several
            # non-primary ones, is fine; two primaries is not).
            models.UniqueConstraint(
                fields=["staff"], condition=models.Q(is_primary=True),
                name="uniq_staff_primary_branch",
            ),
        ]

    def __str__(self):
        return f"{self.staff.get_full_name()} @ {self.branch.name}{' (primary)' if self.is_primary else ''}"


class Permission(models.Model):
    """
    Fixed catalog of grantable actions — see apps.org.rbac.PERMISSION_CATALOG
    for the canonical list of codes and apps.org.rbac.SYSTEM_ROLE_PERMISSIONS
    for which system role grants which codes by default. Seeded into every
    tenant DB by the 0013 migration; not editable via the API (the catalog
    itself is a deploy-time constant — what a hospital CAN configure is which
    permissions a custom Role grants, not the existence of a permission).
    """
    code        = models.CharField(max_length=100, unique=True)   # e.g. "patient.view"
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        app_label = "org"
        db_table  = "permission"
        ordering  = ["code"]

    def __str__(self):
        return self.code


class Role(models.Model):
    """
    A named bundle of permissions. Every tenant DB is seeded with the 6
    system roles (is_system_role=True) matching StaffUser.ROLE_CHOICES —
    these back the existing hardcoded Is* permission classes and can't be
    edited or deleted via the API. Hospitals on the enterprise tier
    (feat_custom_roles) can additionally define their own roles.

    Deliberately NOT a replacement for StaffUser.role: that field stays the
    fast-path primary role used for JWT claims and the existing Is* DRF
    permission checks (see docs/onboarding_auth_rbac_architecture.md 4.3).
    Role/Permission/UserRole is an additive layer for hospitals that need
    finer-grained or custom grants beyond the 6 defaults — most tenants will
    never touch this beyond viewing it.
    """
    name          = models.CharField(max_length=100)
    description   = models.CharField(max_length=255, blank=True)
    is_system_role = models.BooleanField(default=False)
    # For a system role, matches a StaffUser.ROLE_CHOICES value so
    # get_effective_permissions() can resolve "this staff member's primary
    # role" to its default permission set without a join through UserRole.
    system_role_key = models.CharField(max_length=30, blank=True)
    permissions   = models.ManyToManyField(Permission, through="RolePermission", related_name="roles")
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "org"
        db_table  = "role"
        unique_together = [("name",)]
        ordering  = ["-is_system_role", "name"]

    def __str__(self):
        return f"{self.name}{' (system)' if self.is_system_role else ''}"


class RolePermission(models.Model):
    role       = models.ForeignKey(Role, on_delete=models.CASCADE)
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE)

    class Meta:
        app_label = "org"
        db_table  = "role_permission"
        unique_together = [("role", "permission")]


class UserRole(models.Model):
    """
    Extra roles a staff member holds beyond their primary StaffUser.role —
    e.g. a doctor who's also the hospital admin at a small clinic. The
    primary role always keeps working via the fast-path Is* checks; this
    table only matters for tenants using custom RBAC (get_effective_permissions
    unions the primary role's system-role permissions with anything granted
    here).
    """
    staff      = models.ForeignKey(StaffUser, on_delete=models.CASCADE, related_name="extra_roles")
    role       = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="assigned_users")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "org"
        db_table  = "user_role"
        unique_together = [("staff", "role")]


class DoctorProfile(models.Model):
    """Extended profile for staff with role='doctor'."""
    GENDER_CHOICES = [("M", "Male"), ("F", "Female"), ("O", "Other")]

    staff           = models.OneToOneField(StaffUser, on_delete=models.CASCADE,
                                           related_name="doctor_profile")
    registration_no = models.CharField(max_length=50, blank=True)  # MCI/NMC registration
    specialisation  = models.CharField(max_length=100, blank=True)
    qualification   = models.CharField(max_length=200, blank=True)
    gender          = models.CharField(max_length=1, choices=GENDER_CHOICES, blank=True)
    experience_years= models.PositiveSmallIntegerField(null=True, blank=True)
    consultation_fee= models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    # Charged instead of consultation_fee when the appointment_type is
    # "followup" (see apps/opd/views.py::_resolve_doctor_consultation_fee).
    # Left null by default — falls back to consultation_fee, so doctors who
    # don't set this keep charging the same flat fee for every visit type,
    # same as before this field existed.
    followup_fee    = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    digital_signature = models.TextField(blank=True)  # base64 or file path

    # ── Self-service fields — filled by the doctor themselves after login,
    #    not by the admin at creation time. See MyDoctorProfileView. ──────────
    bio         = models.TextField(blank=True)          # short professional bio / about
    photo_url   = models.URLField(max_length=500, blank=True)
    languages   = models.CharField(max_length=200, blank=True)  # comma-separated, e.g. "English, Hindi, Kannada"
    # Comma-separated conditions/procedures this doctor is known for, e.g.
    # "Diabetes, Thyroid disorders, Hypertension" — shown on the patient
    # portal's doctor cards and fed into cross-hospital specialty search
    # (a patient typing "diabetes doctor" can match on this even though
    # "specialisation" just says "Endocrinologist").
    known_for   = models.CharField(max_length=300, blank=True)

    class Meta:
        app_label = "org"
        db_table  = "doctor_profile"

    def __str__(self):
        return f"Dr. {self.staff.get_full_name()}"


class StaffProfile(models.Model):
    """
    Extended profile for every non-doctor staff role — nurse, front desk,
    lab tech, pharmacist, hospital admin. Doctors use DoctorProfile instead
    (different fields: specialisation, consultation fee, signature).

    Same split as DoctorProfile: registration_no / council_name /
    registration_expiry / qualification / experience_years are set by the
    hospital admin at onboarding (mandatory-by-law for nurse and pharmacist
    per the Nursing Council / Pharmacy Act 1948 — optional for the rest).
    gender / bio / languages are filled in by the staff member themselves
    via MyStaffProfileDetailsView. Role-specific detail that doesn't fit a
    fixed column (ward assignment, test proficiencies, equipment trained on,
    billing permissions, admin access scope — see the registration-fields
    reference doc) lives in `extra` for now rather than five separate
    per-role tables; promote a key out of `extra` into its own column if it
    ends up needing to be queried or validated directly.
    """
    GENDER_CHOICES = DoctorProfile.GENDER_CHOICES

    staff              = models.OneToOneField(StaffUser, on_delete=models.CASCADE,
                                               related_name="staff_profile")
    registration_no    = models.CharField(max_length=50, blank=True)   # e.g. nursing/pharmacy council reg. no.
    council_name       = models.CharField(max_length=150, blank=True)  # e.g. "Karnataka State Nursing Council"
    registration_expiry = models.DateField(null=True, blank=True)
    qualification      = models.CharField(max_length=200, blank=True)
    experience_years   = models.PositiveSmallIntegerField(null=True, blank=True)

    # Self-service — filled by the staff member, not the admin.
    gender      = models.CharField(max_length=1, choices=GENDER_CHOICES, blank=True)
    bio         = models.TextField(blank=True)
    languages   = models.CharField(max_length=200, blank=True)

    # Role-specific extras that don't warrant a dedicated column yet.
    extra       = models.JSONField(default=dict, blank=True)

    class Meta:
        app_label = "org"
        db_table  = "staff_profile"

    def __str__(self):
        return f"{self.staff.get_full_name()} ({self.staff.role})"


class AuditLog(models.Model):
    """
    Who did what to which patient record, when. Lives per-tenant since
    patient records are per-tenant; use core.audit.log_action() to write
    entries rather than creating rows directly.

    Deliberately append-only from the application layer — no update/delete
    API is exposed for this model.
    """
    # StaffUser's PK is a plain BigAutoField (see StaffUser above), not a
    # UUID — this was a UUIDField until 2026-08-17, which meant every
    # log_action() call for an authenticated staff actor was silently
    # failing at INSERT time (log_action() swallows all exceptions by
    # design), so actor_user_id was never actually being recorded. Fixed to
    # match the real PK type; see apps/compliance/views.py::AuditLogListView
    # for where this table is actually read.
    actor_user_id   = models.BigIntegerField(null=True, blank=True, db_index=True)
    actor_email     = models.CharField(max_length=255, blank=True)
    actor_role      = models.CharField(max_length=30, blank=True)
    action          = models.CharField(max_length=50, db_index=True)   # e.g. "encounter.sign", "patient.view"
    resource_type   = models.CharField(max_length=50, blank=True)
    resource_id     = models.CharField(max_length=64, blank=True)
    patient_id      = models.UUIDField(null=True, blank=True, db_index=True)
    ip_address      = models.GenericIPAddressField(null=True, blank=True)
    metadata        = models.JSONField(default=dict, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        app_label = "org"
        db_table  = "audit_log"
        ordering  = ["-created_at"]

    def __str__(self):
        return f"{self.action} by {self.actor_email or self.actor_user_id} @ {self.created_at}"


class DoctorSchedule(models.Model):
    """
    Working-hours configuration for one doctor — determines which time slots
    are offered to patients in the booking flow.

    One row per doctor (OneToOne).  Per-day availability is stored in the
    related DoctorAvailabilitySlot rows.  slot_duration_minutes controls
    how the booking engine carves the [start_time, end_time) window into
    individual appointment slots (e.g. 15-minute or 30-minute slots).
    """
    doctor                = models.OneToOneField(
        StaffUser, on_delete=models.CASCADE, related_name="schedule"
    )
    slot_duration_minutes = models.PositiveSmallIntegerField(default=15)
    created_at            = models.DateTimeField(auto_now_add=True)
    updated_at            = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "org"
        db_table  = "doctor_schedule"

    def __str__(self):
        return f"Schedule for {self.doctor.get_full_name()} ({self.slot_duration_minutes} min slots)"


class DoctorAvailabilitySlot(models.Model):
    """
    One row per day-of-week per doctor.  day_of_week follows Python's
    weekday() convention: 0 = Monday … 6 = Sunday.

    is_available=False marks a day off (start_time / end_time are ignored
    on those rows but retained so toggling a day back on restores the last
    configured window without the admin having to re-enter it).

    A doctor can have a break mid-day by adding two rows for the same day
    in the future (currently one row per day is enforced by unique_together
    for simplicity — extend if split-shift support is needed).
    """
    DAY_CHOICES = [
        (0, "Monday"), (1, "Tuesday"), (2, "Wednesday"),
        (3, "Thursday"), (4, "Friday"), (5, "Saturday"), (6, "Sunday"),
    ]

    schedule     = models.ForeignKey(
        DoctorSchedule, on_delete=models.CASCADE, related_name="days"
    )
    day_of_week  = models.SmallIntegerField(choices=DAY_CHOICES)
    is_available = models.BooleanField(default=True)
    start_time   = models.TimeField()
    end_time     = models.TimeField()

    class Meta:
        app_label     = "org"
        db_table      = "doctor_availability_slot"
        unique_together = [("schedule", "day_of_week")]
        ordering      = ["day_of_week"]

    def __str__(self):
        day = dict(self.DAY_CHOICES).get(self.day_of_week, self.day_of_week)
        if not self.is_available:
            return f"{day}: off"
        return f"{day}: {self.start_time}–{self.end_time}"


class Room(models.Model):
    """
    A physical consultation/procedure room at a branch, on a given floor.
    Doctors are NOT assigned here directly — a room can be shared by several
    doctors across the week (see RoomAssignment). This table is just the
    room's own identity (which floor, what it's called, what kind of room).
    """
    ROOM_TYPE_CHOICES = [
        ("consultation", "Consultation"),
        ("procedure",    "Procedure"),
        ("other",        "Other"),
    ]

    branch      = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="rooms")
    floor       = models.CharField(max_length=30, blank=True)   # e.g. "1", "Ground", "2nd Floor" — free text, no dedicated Floor table
    name        = models.CharField(max_length=100)              # e.g. "Room 204", "OPD-3"
    room_type   = models.CharField(max_length=20, choices=ROOM_TYPE_CHOICES, default="consultation")
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "org"
        db_table  = "room"
        unique_together = [("branch", "name")]
        ordering  = ["floor", "name"]

    def __str__(self):
        return f"{self.name} (Floor {self.floor or '—'}, {self.branch.name})"


class RoomAssignment(models.Model):
    """
    A recurring weekly time slice: which doctor sits in which room, on which
    day of the week, during which window. Several rows can share the same
    room (different doctors, non-overlapping times) — that's the whole
    point of this table. Overlap for the same room+day is rejected at the
    API layer (see RoomAssignmentListCreateView.post) before a row is ever
    written, the same way appointment double-booking is prevented.

    day_of_week uses the same convention as DoctorAvailabilitySlot above
    (Python's weekday(): 0=Monday … 6=Sunday) so both can be reasoned about
    the same way when resolving "where is this doctor right now".
    """
    DAY_CHOICES = DoctorAvailabilitySlot.DAY_CHOICES

    room        = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="assignments")
    doctor      = models.ForeignKey(StaffUser, on_delete=models.CASCADE,
                                    related_name="room_assignments",
                                    limit_choices_to={"role": "doctor"})
    day_of_week = models.SmallIntegerField(choices=DAY_CHOICES)
    start_time  = models.TimeField()
    end_time    = models.TimeField()
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "org"
        db_table  = "room_assignment"
        ordering  = ["day_of_week", "start_time"]

    def __str__(self):
        day = dict(self.DAY_CHOICES).get(self.day_of_week, self.day_of_week)
        return f"{self.room.name} — {self.doctor.get_full_name()} ({day} {self.start_time}–{self.end_time})"
