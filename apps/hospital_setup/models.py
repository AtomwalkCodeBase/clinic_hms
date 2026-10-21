"""Hospital DB models for the hospital's own set-up: organisation (branches, departments, floors, rooms, beds, number"""

from django.contrib.auth.hashers import make_password, check_password
from django.db import models

from apps.hospital_setup.rbac import SYSTEM_ROLE_LABELS


# Organisation: branches, departments, floors, rooms, beds, number sequences

class NextNumber(models.Model):
    """NNTM — Next Number Table Manager."""
    branch      = models.ForeignKey("Branch", on_delete=models.CASCADE, null=True, blank=True, related_name="number_counters")
    entity      = models.CharField(max_length=20)
    prefix      = models.CharField(max_length=10, default="")
    last_number = models.PositiveBigIntegerField(default=0)
    pad_length  = models.PositiveSmallIntegerField(default=6)

    class Meta:
        db_table     = "next_number"
        constraints = [
            models.UniqueConstraint(fields=["branch", "entity"], name="uniq_counter_branch_entity"),
            models.UniqueConstraint(fields=["entity"], condition=models.Q(branch__isnull=True), name="uniq_counter_hospital_wide"),
        ]

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
        db_table  = "branch"

    def __str__(self):
        return self.name

class Department(models.Model):
    branch      = models.ForeignKey(Branch, on_delete=models.CASCADE,
                                    related_name="departments")
    name        = models.CharField(max_length=100)
    is_active   = models.BooleanField(default=True)

    class Meta:
        db_table  = "department"
        constraints = [models.UniqueConstraint(fields=["branch", "name"], name="uniq_department_branch_name")]

    def __str__(self):
        return f"{self.branch.name} / {self.name}"

class Floor(models.Model):
    """A physical floor at a branch — e.g. "Ground", "1st Floor", "Basement"."""
    branch      = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="floors")
    name        = models.CharField(max_length=50)    # e.g. "Ground", "1st Floor"
    level       = models.IntegerField(default=0)      # sort order only
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "floor"
        constraints = [models.UniqueConstraint(fields=["branch", "name"], name="uniq_floor_branch_name")]
        ordering  = ["level", "name"]

    def __str__(self):
        return f"{self.name} ({self.branch.name})"

class Room(models.Model):
    """A physical room at a branch, on a given floor — OPD consultation/"""

    branch      = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="rooms")
    floor_obj   = models.ForeignKey(Floor, on_delete=models.SET_NULL, null=True, blank=True, related_name="rooms")
    # Optional — most OPD rooms don't need one; a bed-based room (ward/ICU/
    department  = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="rooms")
    name        = models.CharField(max_length=100)              # e.g. "Room 204", "OPD-3", "Ward 1", "ICU-A"
    room_type   = models.CharField(max_length=20, default="consultation")
    # Max number of active Beds this room may hold — only meaningful (and
    capacity    = models.PositiveSmallIntegerField(null=True, blank=True)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "room"
        constraints = [models.UniqueConstraint(fields=["branch", "name"], name="uniq_room_branch_name")]
        ordering  = ["floor_obj__level", "name"]

    @property
    def floor(self):
        return self.floor_obj.name if self.floor_obj_id else ""

    def __str__(self):
        return f"{self.name} (Floor {self.floor or '—'}, {self.branch.name})"


class Bed(models.Model):
    """One physical bed within a Room (a bed-based one — general ward/private/"""
    STATUS_AVAILABLE      = "available"
    STATUS_RESERVED       = "reserved"
    STATUS_OCCUPIED       = "occupied"
    STATUS_CLEANING       = "cleaning"
    STATUS_BLOCKED        = "blocked"
    STATUS_OUT_OF_SERVICE = "out_of_service"
    STATUS_CHOICES = [
        (STATUS_AVAILABLE, "Available"),
        (STATUS_RESERVED, "Reserved"),
        (STATUS_OCCUPIED, "Occupied"),
        (STATUS_CLEANING, "Cleaning"),
        (STATUS_BLOCKED, "Blocked"),
        (STATUS_OUT_OF_SERVICE, "Out of Service"),
    ]

    room        = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="beds")
    bed_number  = models.CharField(max_length=20)   # e.g. "3A", "12"
    status      = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_AVAILABLE)
    # Set only while status=RESERVED, by apps.ipd.views.ReserveBedView, and
    reserved_for_admission_id = models.UUIDField(null=True, blank=True, db_index=True)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "bed"
        constraints = [models.UniqueConstraint(fields=["room", "bed_number"], name="uniq_bed_room_number")]
        ordering  = ["room__name", "bed_number"]

    def __str__(self):
        return f"{self.room.name} / Bed {self.bed_number} ({self.status})"


# Staff: users, roles, permissions, schedules, audit log

class StaffUser(models.Model):
    """Per-hospital staff user. Plain Django model (not AUTH_USER_MODEL)."""
    ROLE_CHOICES = [*SYSTEM_ROLE_LABELS.items(), ("custom", "Custom Role")]

    # Optional now — phone is the login identifier. null=True (not just
    email       = models.EmailField(unique=True, blank=True, null=True)
    first_name  = models.CharField(max_length=150, blank=True)
    last_name   = models.CharField(max_length=150, blank=True)
    password    = models.CharField(max_length=128, default="!")  # "!" = unusable
    role        = models.CharField(max_length=30, choices=ROLE_CHOICES)
    # Only set when role="custom" — which hospital-defined Role this staff
    custom_role = models.ForeignKey("Role", on_delete=models.PROTECT,
                                    null=True, blank=True, related_name="primary_staff")
    branch      = models.ForeignKey(Branch, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="staff")
    department  = models.ForeignKey(Department, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="staff")
    phone               = models.CharField(max_length=20, unique=True)
    # Optional secondary login identifier for hospitals that already run an
    employee_id         = models.CharField(max_length=50, unique=True, null=True, blank=True)
    date_of_birth       = models.DateField(null=True, blank=True)
    is_active           = models.BooleanField(default=True)
    must_change_password = models.BooleanField(default=False)
    date_joined         = models.DateTimeField(auto_now_add=True)
    last_login          = models.DateTimeField(null=True, blank=True)

    # Self-service profile photo — common to every staff role (doctor, nurse,
    photo               = models.CharField(max_length=255, blank=True)

    class Meta:
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
    """Which branches a staff member works at — a doctor commonly works more"""
    staff       = models.ForeignKey(StaffUser, on_delete=models.CASCADE,
                                    related_name="branch_mappings")
    branch      = models.ForeignKey(Branch, on_delete=models.CASCADE,
                                    related_name="staff_mappings")
    is_primary  = models.BooleanField(default=False)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "staff_branch_mapping"
        constraints = [
            models.UniqueConstraint(fields=["staff", "branch"], name="uniq_staff_branch"),
            # At most one primary branch per staff member (Postgres partial
            models.UniqueConstraint(
                fields=["staff"], condition=models.Q(is_primary=True),
                name="uniq_staff_primary_branch",
            ),
        ]

    def __str__(self):
        return f"{self.staff.get_full_name()} @ {self.branch.name}{' (primary)' if self.is_primary else ''}"

class NurseDoctorAssignment(models.Model):
    """Which doctor(s) a nurse supports — set by the hospital admin (Staff page,"""
    nurse       = models.ForeignKey(StaffUser, on_delete=models.CASCADE,
                                    related_name="assigned_doctor_links",
                                    limit_choices_to={"role": "nurse"})
    doctor      = models.ForeignKey(StaffUser, on_delete=models.CASCADE,
                                    related_name="assigned_nurse_links",
                                    limit_choices_to={"role": "doctor"})
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "nurse_doctor_assignment"
        constraints = [
            models.UniqueConstraint(fields=["nurse", "doctor"], name="uniq_nurse_doctor"),
        ]

    def __str__(self):
        return f"{self.nurse.get_full_name()} → Dr. {self.doctor.get_full_name()}"

class Permission(models.Model):
    """Fixed catalog of grantable actions — see apps.hospital_setup.rbac.PERMISSION_CATALOG"""
    code        = models.CharField(max_length=100, unique=True)   # e.g. "patient.view"
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table  = "permission"
        ordering  = ["code"]

    def __str__(self):
        return self.code

class Role(models.Model):
    """A named bundle of permissions. Every hospital DB is seeded with the 6"""
    name          = models.CharField(max_length=100, unique=True)
    description   = models.CharField(max_length=255, blank=True)
    is_system_role = models.BooleanField(default=False)
    # For a system role, matches a StaffUser.ROLE_CHOICES value so
    system_role_key = models.CharField(max_length=30, blank=True)
    permissions   = models.ManyToManyField(Permission, through="RolePermission", related_name="roles")
    # Which of the 6 system roles this custom role should be treated AS
    acts_as       = models.JSONField(default=list, blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "role"
        ordering  = ["-is_system_role", "name"]

    def __str__(self):
        return f"{self.name}{' (system)' if self.is_system_role else ''}"

class RolePermission(models.Model):
    role       = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="grants")
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name="grants")

    class Meta:
        db_table  = "role_permission"
        constraints = [models.UniqueConstraint(fields=["role", "permission"], name="uniq_role_permission")]

class UserRole(models.Model):
    """Extra roles a staff member holds beyond their primary StaffUser.role —"""
    staff      = models.ForeignKey(StaffUser, on_delete=models.CASCADE, related_name="extra_roles")
    role       = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="assigned_users")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "user_role"
        constraints = [models.UniqueConstraint(fields=["staff", "role"], name="uniq_user_role")]

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
    followup_fee    = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    digital_signature = models.CharField(max_length=255, blank=True)

    # ── Self-service fields — filled by the doctor themselves after login,
    bio         = models.TextField(blank=True)          # short professional bio / about
    languages   = models.CharField(max_length=200, blank=True)  # comma-separated, e.g. "English, Hindi, Kannada"
    # Comma-separated conditions/procedures this doctor is known for, e.g.
    known_for   = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table  = "doctor_profile"

    def __str__(self):
        return f"Dr. {self.staff.get_full_name()}"

class StaffProfile(models.Model):
    """Extended profile for every non-doctor staff role — nurse, front desk,"""
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
        db_table  = "staff_profile"

    def __str__(self):
        return f"{self.staff.get_full_name()} ({self.staff.role})"

class AuditLog(models.Model):
    """Who did what to which patient record, when. Lives per-hospital since"""
    # StaffUser's PK is a plain BigAutoField (see StaffUser above), not a
    actor_user_id   = models.BigIntegerField(null=True, blank=True)
    actor_email     = models.CharField(max_length=255, blank=True)
    actor_role      = models.CharField(max_length=30, blank=True)
    action          = models.CharField(max_length=50)   # e.g. "encounter.sign", "patient.view"
    resource_type   = models.CharField(max_length=50, blank=True)
    resource_id     = models.CharField(max_length=64, blank=True)
    patient_id      = models.UUIDField(null=True, blank=True)
    ip_address      = models.GenericIPAddressField(null=True, blank=True)
    metadata        = models.JSONField(default=dict, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "audit_log"
        ordering  = ["-created_at"]
        indexes   = [
            models.Index(fields=["patient_id", "-created_at"], name="audit_patient_time"),
            models.Index(fields=["actor_user_id", "-created_at"], name="audit_actor_time"),
            models.Index(fields=["-created_at"], name="audit_time"),
        ]

    def __str__(self):
        return f"{self.action} by {self.actor_email or self.actor_user_id} @ {self.created_at}"

class DoctorSchedule(models.Model):
    """Working-hours configuration for one doctor — determines which time slots"""
    doctor                = models.OneToOneField(
        StaffUser, on_delete=models.CASCADE, related_name="schedule"
    )
    slot_duration_minutes = models.PositiveSmallIntegerField(default=15)
    created_at            = models.DateTimeField(auto_now_add=True)
    updated_at            = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "doctor_schedule"

    def __str__(self):
        return f"Schedule for {self.doctor.get_full_name()} ({self.slot_duration_minutes} min slots)"

class DoctorAvailabilitySlot(models.Model):
    """One row per day-of-week per doctor.  day_of_week follows Python's"""
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
        db_table      = "doctor_availability_slot"
        constraints   = [models.UniqueConstraint(fields=["schedule", "day_of_week"], name="uniq_slot_schedule_day")]
        ordering      = ["day_of_week"]

    def __str__(self):
        day = dict(self.DAY_CHOICES).get(self.day_of_week, self.day_of_week)
        if not self.is_available:
            return f"{day}: off"
        return f"{day}: {self.start_time}–{self.end_time}"


class RoomAssignment(models.Model):
    """A recurring weekly time slice: which doctor sits in which room, on which"""
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
        db_table  = "room_assignment"
        ordering  = ["day_of_week", "start_time"]

    def __str__(self):
        day = dict(self.DAY_CHOICES).get(self.day_of_week, self.day_of_week)
        return f"{self.room.name} — {self.doctor.get_full_name()} ({day} {self.start_time}–{self.end_time})"


# Compliance: record amendments and consents

class RecordAmendment(models.Model):
    """DPDP Act Article 13 — patient right to correction."""
    STATUS_CHOICES = [
        ("pending",  "Pending Review"),
        ("approved", "Approved and Applied"),
        ("rejected", "Rejected with Reason"),
    ]

    patient         = models.ForeignKey("opd.HospitalPatient", on_delete=models.PROTECT,
                                        related_name="amendments")
    resource_type   = models.CharField(max_length=50)   # which table/field
    resource_id     = models.CharField(max_length=64)
    field_name      = models.CharField(max_length=100)
    current_value   = models.TextField(blank=True)
    requested_value = models.TextField()
    reason          = models.TextField(blank=True)
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    reviewed_by     = models.ForeignKey(StaffUser, on_delete=models.SET_NULL,
                                        null=True, blank=True, related_name="reviewed_amendments")
    review_notes    = models.TextField(blank=True)
    requested_at    = models.DateTimeField(auto_now_add=True)
    resolved_at     = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table  = "record_amendment"
        ordering  = ["-requested_at"]

    def __str__(self):
        return f"Amendment #{self.id} — {self.resource_type} ({self.status})"


class ConsentRecord(models.Model):
    """Immutable proof-of-consent trail (DPDP Act 2023)."""
    CONSENT_DPDP_PROCESSING = "dpdp_data_processing"
    CONSENT_HIE_SHARING     = "hie_data_sharing"
    # Added for apps.ipd (Phase 1 admission intake) — recorded the same way
    CONSENT_ADMISSION_TREATMENT = "admission_treatment"
    CONSENT_TYPE_CHOICES = [
        (CONSENT_DPDP_PROCESSING, "DPDP — Personal Data Processing"),
        (CONSENT_HIE_SHARING,     "HIE — Cross-Hospital Data Sharing"),
        (CONSENT_ADMISSION_TREATMENT, "Admission — Consent to Inpatient Treatment"),
    ]

    SOURCE_FRONT_DESK = "front_desk"
    SOURCE_PORTAL     = "patient_portal"
    SOURCE_CHOICES = [
        (SOURCE_FRONT_DESK, "Front Desk Registration"),
        (SOURCE_PORTAL,     "Patient Portal"),
    ]

    patient         = models.ForeignKey("opd.HospitalPatient", on_delete=models.PROTECT,
                                        related_name="consent_records")
    consent_type    = models.CharField(max_length=30, choices=CONSENT_TYPE_CHOICES)
    granted         = models.BooleanField(default=True)
    source          = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    # Who captured it — set for front-desk-attested consent (staff confirms
    recorded_by     = models.ForeignKey(StaffUser, on_delete=models.SET_NULL,
                                        null=True, blank=True, related_name="recorded_consents")
    ip_address      = models.GenericIPAddressField(null=True, blank=True)
    user_agent      = models.TextField(blank=True)
    # Free-text tag for whichever version of the consent/policy language was
    policy_version  = models.CharField(max_length=20, default="v1")
    notes           = models.TextField(blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "consent_record"
        ordering  = ["-created_at"]
        indexes   = [models.Index(fields=["patient", "consent_type", "-created_at"], name="consent_patient_type_time")]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("A consent record is never edited; record a new one instead.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("A consent record is never deleted.")

    def __str__(self):
        return f"{self.get_consent_type_display()} — {'granted' if self.granted else 'revoked'} ({self.source})"


# Notifications

class NotificationLog(models.Model):
    """Delivery log for every notification attempt."""
    STATUS_CHOICES = [
        ("queued",    "Queued"),
        ("sent",      "Sent"),
        ("delivered", "Delivered"),
        ("failed",    "Failed"),
    ]

    patient     = models.ForeignKey("opd.HospitalPatient", on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="notifications")
    CHANNEL_CHOICES = [("in_app", "In-app"), ("sms", "SMS"), ("email", "Email"), ("whatsapp", "WhatsApp")]

    recipient   = models.CharField(max_length=200)  # phone or email
    channel     = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    body        = models.TextField()                 # rendered body (after variable substitution)
    status      = models.CharField(max_length=20, choices=STATUS_CHOICES, default="queued")
    provider_ref= models.CharField(max_length=200, blank=True)  # external message ID
    error       = models.TextField(blank=True)
    sent_at     = models.DateTimeField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    # Idempotency key for generated reminders (e.g. "appt_reminder:<uuid>",
    reference   = models.CharField(max_length=100, blank=True, db_index=True)
    # When the patient viewed this in their in-app notification list. Only
    read_at     = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table  = "notification_log"
        ordering  = ["-created_at"]
