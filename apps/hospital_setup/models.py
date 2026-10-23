"""Hospital database: the hospital's own set-up (branches, the department list, which branch offers which department, floors, rooms, beds, number counters), its staff, roles and schedules, the audit log, record corrections, consents and notifications.

Seventeen models here and six in apps/opd: this file holds the set-up and people, opd holds the patient and the visit. One-line docstring and __str__ on every model; created_at / updated_at on records that change; UniqueConstraint, never unique_together; every foreign key has on_delete and related_name. Reverse names start with the first letters of the model they point at, as in the shared models: b_ Branch, u_ StaffUser, p_ HospitalPatient, d_ Department, bdp_ BranchDepartment, sbd_ StaffBranchDepartment, f_ Floor, r_ Room, ro_ Role, pm_ Permission, a_ Appointment, e_ OPDEncounter, i_ Invoice. Plural for a foreign key, singular for a one-to-one.

Deliberate exceptions: PROTECT where a record must outlive a delete (StaffUser.group, Room.floor_obj); AuditLog.actor_user_id and patient_id and Bed.reserved_for_admission_id kept as plain values so they survive a delete or avoid a circular import; required choice fields without a default (consent_type, source); ConsentRecord overrides save() and delete() to stay immutable. Two many-to-many fields create their own link tables: Role.permissions (reusing the existing role_permission table) and StaffUser.extra_roles.
"""

from django.contrib.auth.hashers import make_password, check_password
from django.core.exceptions import ValidationError
from django.db import models

# Place: branches, number counters, floors, departments, rooms, beds

class Branch(models.Model):
    """A physical location of the hospital."""
    name       = models.CharField(max_length=200)
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
    """NNTM — Next Number Table Manager."""
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

class Floor(models.Model):
    """A physical floor at a branch — e.g. "Ground", "1st Floor", "Basement"."""
    branch     = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="b_floors")
    name       = models.CharField(max_length=50)    # e.g. "Ground", "1st Floor"
    level      = models.IntegerField(default=0)      # sort order only
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
    """A department of the hospital (Paediatrics, Oncology); each branch offers some of them through BranchDepartment."""
    name       = models.CharField(max_length=100, unique=True)
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "department"
        ordering  = ["name"]

    def __str__(self):
        return self.name

class BranchDepartment(models.Model):
    """A department offered at one branch, on one floor: the place a doctor or other staff member works."""
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
    """A physical room on a floor (its branch is the floor's branch): OPD consultation, ward, ICU, theatre."""
    floor      = models.ForeignKey(Floor, on_delete=models.PROTECT, related_name="f_rooms")
    # Optional: most OPD rooms don't belong to one department. Must be a department of the same branch as the floor.
    branch_department = models.ForeignKey(BranchDepartment, on_delete=models.SET_NULL, null=True, blank=True, related_name="bdp_rooms")
    name       = models.CharField(max_length=100)              # e.g. "Room 204", "OPD-3", "Ward 1", "ICU-A"
    room_type  = models.CharField(max_length=20, default="consultation")
    # Max number of active Beds this room may hold; only meaningful for a bed-based room type
    capacity   = models.PositiveSmallIntegerField(null=True, blank=True)
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "room"
        constraints = [models.UniqueConstraint(fields=["floor", "name"], name="uniq_room_floor_name")]
        ordering  = ["floor__level", "name"]

    def __str__(self):
        return f"{self.name} (Floor {self.floor.name}, {self.branch.name})"

    def clean(self):
        if self.branch_department_id:
            if self.branch_department.branch_id != self.floor.branch_id:
                raise ValidationError({"branch_department": "The department is not offered at this floor's branch."})
            if self.branch_department.floor_id != self.floor_id:
                raise ValidationError({"branch_department": "The department is on a different floor."})

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    @property
    def branch(self):
        return self.floor.branch

    @property
    def branch_id(self):
        return self.floor.branch_id

    @property
    def department(self):
        return self.branch_department.department if self.branch_department_id else None

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

    room                      = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="r_beds")
    bed_number                = models.CharField(max_length=20)   # e.g. "3A", "12"
    status                    = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_AVAILABLE)
    # Set only while status=RESERVED, by apps.ipd.views.ReserveBedView, and
    reserved_for_admission_id = models.UUIDField(null=True, blank=True, db_index=True)
    is_active                 = models.BooleanField(default=True)
    created_at                = models.DateTimeField(auto_now_add=True)
    updated_at                = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "bed"
        constraints = [models.UniqueConstraint(fields=["room", "bed_number"], name="uniq_bed_room_number")]
        ordering  = ["room__name", "bed_number"]

    def __str__(self):
        return f"{self.room.name} / Bed {self.bed_number} ({self.status})"


# Access: permissions and roles

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
    name            = models.CharField(max_length=100, unique=True)
    description     = models.CharField(max_length=255, blank=True)
    is_system_role  = models.BooleanField(default=False)
    # For a system role, one of the keys in rbac.SYSTEM_ROLE_LABELS so
    system_role_key = models.CharField(max_length=30, blank=True)
    permissions     = models.ManyToManyField(Permission, blank=True, related_name="roles", db_table="role_permission")
    # Which of the 6 system roles this custom role should be treated AS
    acts_as         = models.JSONField(default=list, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "role"
        ordering  = ["-is_system_role", "name"]

    def __str__(self):
        return f"{self.name}{' (system)' if self.is_system_role else ''}"

# People: staff, their places of work, profiles and schedules

class StaffUser(models.Model):
    """Per-hospital staff user. Plain Django model (not AUTH_USER_MODEL)."""
    GENDER_CHOICES = [("M", "Male"), ("F", "Female"), ("O", "Other")]

    # Optional now — phone is the login identifier. null=True (not just
    email                = models.EmailField(unique=True, blank=True, null=True)
    first_name           = models.CharField(max_length=150, blank=True)
    last_name            = models.CharField(max_length=150, blank=True)
    password             = models.CharField(max_length=128, default="!")  # "!" = unusable
    # The user group: one of the system roles (doctor, nurse...) or a role the hospital defined. It decides permissions and what the user acts as.
    group                = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="ro_staff")
    phone                = models.CharField(max_length=15, unique=True)
    # Optional secondary login identifier for hospitals that already run an
    employee_id          = models.CharField(max_length=50, unique=True, null=True, blank=True)
    date_of_birth        = models.DateField(null=True, blank=True)
    is_active            = models.BooleanField(default=True)
    must_change_password = models.BooleanField(default=False)
    date_joined          = models.DateTimeField(auto_now_add=True)
    last_login           = models.DateTimeField(null=True, blank=True)

    # Self-service profile photo — common to every staff role (doctor, nurse,
    photo                = models.CharField(max_length=255, blank=True)

    # Roles held besides `group`
    extra_roles          = models.ManyToManyField(Role, blank=True, related_name="ro_extra_staff")

    # Professional details: registration and qualification for everyone, fees, signature and specialisation for doctors
    registration_no      = models.CharField(max_length=50, blank=True)
    council_name         = models.CharField(max_length=150, blank=True)
    registration_expiry  = models.DateField(null=True, blank=True)
    qualification        = models.CharField(max_length=200, blank=True)
    experience_years     = models.PositiveSmallIntegerField(null=True, blank=True)
    specialisation       = models.CharField(max_length=100, blank=True)
    consultation_fee     = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    followup_fee         = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    digital_signature    = models.CharField(max_length=255, blank=True)
    known_for            = models.CharField(max_length=300, blank=True)
    gender               = models.CharField(max_length=1, choices=GENDER_CHOICES, blank=True)
    bio                  = models.TextField(blank=True)
    languages            = models.CharField(max_length=200, blank=True)
    extra                = models.JSONField(default=dict, blank=True)

    # A doctor's saved prescription templates: {template name: [medicine dicts as in Prescription.items]}
    prescription_favourites = models.JSONField(default=dict, blank=True)
    updated_at           = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "staff_user"

    def __str__(self):
        return f"{self.get_full_name()} ({self.role})"

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.email

    @property
    def role(self):
        """The system role key (doctor, nurse...), or "custom" for a role the hospital defined."""
        return self.group.system_role_key if self.group.is_system_role else "custom"

    @property
    def custom_role(self):
        return None if self.group.is_system_role else self.group

    def set_unusable_password(self):
        self.password = "!"

    def set_password(self, raw_password):
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        return check_password(raw_password, self.password)

class StaffBranchDepartment(models.Model):
    """Every place a staff member works: a department at a branch. Exactly one is the primary place; a hospital-wide user such as an admin has none."""
    staff             = models.ForeignKey(StaffUser, on_delete=models.CASCADE, related_name="u_branch_departments")
    branch_department = models.ForeignKey(BranchDepartment, on_delete=models.PROTECT, related_name="bdp_staff_links")
    is_primary        = models.BooleanField(default=False)
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "staff_branch_department"
        constraints = [
            models.UniqueConstraint(fields=["staff", "branch_department"], name="uniq_staff_branch_department"),
            models.UniqueConstraint(fields=["staff"], condition=models.Q(is_primary=True), name="uniq_staff_primary_branch_department"),
        ]

    def __str__(self):
        return f"{self.staff.get_full_name()} @ {self.branch_department}"

class NurseDoctorAssignment(models.Model):
    """Which doctor(s) a nurse supports — set by the hospital admin (Staff page,"""
    nurse      = models.ForeignKey(StaffUser, on_delete=models.CASCADE,
                                    related_name="u_assigned_doctor_links", limit_choices_to={"group__system_role_key": "nurse"})
    doctor     = models.ForeignKey(StaffUser, on_delete=models.CASCADE,
                                    related_name="u_assigned_nurse_links", limit_choices_to={"group__system_role_key": "doctor"})
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "nurse_doctor_assignment"
        constraints = [
            models.UniqueConstraint(fields=["nurse", "doctor"], name="uniq_nurse_doctor"),
        ]

    def __str__(self):
        return f"{self.nurse.get_full_name()} → Dr. {self.doctor.get_full_name()}"

class DoctorSchedule(models.Model):
    """Working-hours configuration for one doctor at one location — determines which time slots"""
    DAY_CHOICES = [
        (0, "Monday"), (1, "Tuesday"), (2, "Wednesday"),
        (3, "Thursday"), (4, "Friday"), (5, "Saturday"), (6, "Sunday"),
    ]

    staff_branch_department = models.OneToOneField(
        StaffBranchDepartment, on_delete=models.CASCADE, related_name="sbd_schedule",
        limit_choices_to={"staff__group__system_role_key": "doctor"},
    )
    slot_duration_minutes = models.PositiveSmallIntegerField(default=15)
    # The week's working windows at this location, one dict each: day_of_week (0 = Monday), start_time and end_time ("HH:MM"), room_id (optional,
    # a Room at the same branch), is_active. A day with no window is a day off; several windows on a day are split shifts or different rooms.
    weekly_hours          = models.JSONField(default=list, blank=True)
    created_at            = models.DateTimeField(auto_now_add=True)
    updated_at            = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "doctor_schedule"
        constraints = [models.CheckConstraint(check=models.Q(slot_duration_minutes__gt=0), name="slot_duration_positive")]

    def __str__(self):
        return f"Schedule for {self.staff_branch_department} ({self.slot_duration_minutes} min slots)"

    def clean(self):
        days = dict(self.DAY_CHOICES)
        for window in self.weekly_hours:
            if window.get("day_of_week") not in days:
                raise ValidationError({"weekly_hours": f"Unknown day: {window.get('day_of_week')}."})
            start, end = window.get("start_time"), window.get("end_time")
            if not (start and end and start < end):
                raise ValidationError({"weekly_hours": f"{days[window['day_of_week']]}: the end must be after the start."})
        room_ids = {w["room_id"] for w in self.weekly_hours if w.get("room_id")}
        if room_ids:
            branch_id = self.staff_branch_department.branch_department.branch_id
            found = Room.objects.using(self._state.db).filter(pk__in=room_ids, floor__branch_id=branch_id).count()
            if found != len(room_ids):
                raise ValidationError({"weekly_hours": "A room is missing or belongs to a different branch."})

# Records: the audit log, record corrections, consents and notifications

class AuditLog(models.Model):
    """Who did what to which patient record, when. Lives per-hospital since each hospital keeps its own trail."""
    actor_user_id = models.BigIntegerField(null=True, blank=True)
    actor_email   = models.CharField(max_length=255, blank=True)
    actor_role    = models.CharField(max_length=30, blank=True)
    action        = models.CharField(max_length=50)   # e.g. "encounter.sign", "patient.view"
    resource_type = models.CharField(max_length=50, blank=True)
    resource_id   = models.CharField(max_length=64, blank=True)
    patient_id    = models.CharField(max_length=20, null=True, blank=True)
    ip_address    = models.GenericIPAddressField(null=True, blank=True)
    metadata      = models.JSONField(default=dict, blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)

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

class RecordAmendment(models.Model):
    """DPDP Act Article 13 — patient right to correction."""
    STATUS_CHOICES = [
        ("pending",  "Pending Review"),
        ("approved", "Approved and Applied"),
        ("rejected", "Rejected with Reason"),
    ]

    patient         = models.ForeignKey("opd.HospitalPatient", on_delete=models.PROTECT,
                                        related_name="p_amendments")
    resource_type   = models.CharField(max_length=50)   # which table/field
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

    patient        = models.ForeignKey("opd.HospitalPatient", on_delete=models.PROTECT,
                                        related_name="p_consent_records")
    consent_type   = models.CharField(max_length=30, choices=CONSENT_TYPE_CHOICES)
    granted        = models.BooleanField(default=True)
    source         = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    # Who captured it — set for front-desk-attested consent (staff confirms
    recorded_by    = models.ForeignKey(StaffUser, on_delete=models.SET_NULL,
                                        null=True, blank=True, related_name="u_recorded_consents")
    ip_address     = models.GenericIPAddressField(null=True, blank=True)
    user_agent     = models.TextField(blank=True)
    # Free-text tag for whichever version of the consent/policy language was
    policy_version = models.CharField(max_length=20, default="v1")
    notes          = models.TextField(blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "consent_record"
        ordering  = ["-created_at"]
        indexes   = [models.Index(fields=["patient", "consent_type", "-created_at"], name="consent_patient_type_time")]

    def __str__(self):
        return f"{self.get_consent_type_display()} — {'granted' if self.granted else 'revoked'} ({self.source})"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("A consent record is never edited; record a new one instead.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("A consent record is never deleted.")

class NotificationLog(models.Model):
    """Delivery log for every notification attempt."""
    STATUS_CHOICES = [
        ("queued",    "Queued"),
        ("sent",      "Sent"),
        ("delivered", "Delivered"),
        ("failed",    "Failed"),
    ]

    patient      = models.ForeignKey("opd.HospitalPatient", on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="p_notifications")
    CHANNEL_CHOICES = [("in_app", "In-app"), ("sms", "SMS"), ("email", "Email"), ("whatsapp", "WhatsApp")]

    recipient    = models.CharField(max_length=200)  # phone or email
    channel      = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    body         = models.TextField()                 # rendered body (after variable substitution)
    status       = models.CharField(max_length=20, choices=STATUS_CHOICES, default="queued")
    provider_ref = models.CharField(max_length=200, blank=True)  # external message ID
    error        = models.TextField(blank=True)
    sent_at      = models.DateTimeField(null=True, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    # Idempotency key for generated reminders (e.g. "appt_reminder:<uuid>",
    reference    = models.CharField(max_length=100, blank=True, db_index=True)
    # When the patient viewed this in their in-app notification list. Only
    read_at      = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table  = "notification_log"
        ordering  = ["-created_at"]

    def __str__(self):
        return f"{self.channel} to {self.recipient} ({self.status})"
