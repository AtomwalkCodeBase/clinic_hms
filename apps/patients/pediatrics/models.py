"""
apps/patients/pediatrics/models.py
----------------------------------
Every pediatric table in one place: birth history, vaccination records, the configurable vaccination / milestone
schedules, and milestone records. They are registered under the apps they always belonged to (app_label), so table
names and migrations are unchanged; apps/registry/models.py and apps/patients/models.py import them from here.
"""
from django.db import models


class SharedBirthHistory(models.Model):
    """
    Birth history shared across hospitals: a copy of BirthHistory written whenever a hospital saves one, so the emergency
    summary and other hospitals can see it. One row per child (an edit overwrites it); source_tenant_id is the hospital
    that last wrote it.
    """
    awpid = models.CharField(max_length=30, unique=True, db_index=True)
    gestational_age_weeks = models.PositiveSmallIntegerField(null=True, blank=True)
    birth_weight_kg = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    delivery_mode = models.CharField(max_length=12, blank=True)
    multiple_birth = models.CharField(max_length=50, blank=True)
    nicu_admission = models.BooleanField(default=False)
    nicu_days = models.PositiveSmallIntegerField(null=True, blank=True)
    birth_complications = models.TextField(blank=True)
    congenital_conditions = models.TextField(blank=True)
    apgar_score_1min = models.PositiveSmallIntegerField(null=True, blank=True)
    apgar_score_5min = models.PositiveSmallIntegerField(null=True, blank=True)
    source_tenant_id = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "registry"
        db_table  = "shared_birth_history"


class SharedVaccination(models.Model):
    """
    One vaccination record, visible at every hospital. `source` says where it came from: "clinic" (given here, trusted),
    "self_reported" (a parent's uploaded certificate, starts "pending_review" until any hospital's doctor or nurse
    verifies or rejects it) or "doctor_ordered" (recommended, not given yet).

    `verification_status` is the whole lifecycle of the record, so ordered and declined are values of it too:
      pending_review -> verified | rejected        a parent's upload being reviewed
      ordered -> verified                          a doctor's order, then a nurse gives it (the same row is updated)
      declined                                     a doctor says this slot isn't needed
    `administered_date` stays empty for ordered and declined rows. `file_data` holds the stored certificate's key.
    """
    SOURCE_CLINIC = "clinic"
    SOURCE_SELF_REPORTED = "self_reported"
    SOURCE_DOCTOR_ORDERED = "doctor_ordered"
    SOURCE_CHOICES = [
        (SOURCE_CLINIC, "Clinic administered"),
        (SOURCE_SELF_REPORTED, "Self reported"),
        (SOURCE_DOCTOR_ORDERED, "Doctor ordered"),
    ]

    STATUS_VERIFIED = "verified"
    STATUS_PENDING  = "pending_review"
    STATUS_REJECTED = "rejected"
    STATUS_ORDERED  = "ordered"
    STATUS_DECLINED = "declined"
    VERIFICATION_CHOICES = [
        (STATUS_VERIFIED, "Verified"),
        (STATUS_PENDING,  "Pending review"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_ORDERED,  "Ordered (not yet administered)"),
        (STATUS_DECLINED, "Declined / not required"),
    ]

    awpid               = models.CharField(max_length=30, db_index=True)
    vaccine_name        = models.CharField(max_length=100)
    scheduled_label     = models.CharField(max_length=50, blank=True)   # the schedule slot it fills, e.g. "18 months"
    administered_date   = models.DateField(null=True, blank=True)
    due_date             = models.DateField(null=True, blank=True)       # an order's target date
    reason               = models.TextField(blank=True)                   # the doctor's reason for an order or a decline
    dose_number          = models.PositiveIntegerField(null=True, blank=True)

    source              = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_CLINIC)
    verification_status = models.CharField(max_length=20, choices=VERIFICATION_CHOICES, default=STATUS_VERIFIED, db_index=True)
    verified_by_name    = models.CharField(max_length=200, blank=True)  # a name, not a link: staff live in hospital databases
    verified_at         = models.DateTimeField(null=True, blank=True)
    review_notes        = models.TextField(blank=True)

    file_name           = models.CharField(max_length=255, blank=True)
    mime_type            = models.CharField(max_length=100, blank=True)
    file_data            = models.TextField(blank=True)

    source_tenant_id    = models.IntegerField(null=True, blank=True)  # the hospital that logged or verified it; empty until reviewed
    recorded_by          = models.CharField(max_length=20, default="patient")  # "patient" or "staff"

    created_at           = models.DateTimeField(auto_now_add=True)
    updated_at           = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "registry"
        db_table  = "shared_vaccination"
        indexes = [models.Index(fields=["awpid", "verification_status"])]
        ordering  = ["administered_date"]

    def __str__(self):
        return f"{self.awpid} — {self.vaccine_name} ({self.verification_status})"


class Schedule(models.Model):
    """
    A named, ordered set of rules a hospital's pediatric roadmap is built against. ONE table for both kinds:
    kind="vaccination" (what to give and when) or kind="milestone" (what a child should be doing and when).

    owner_tenant_id is null for a system template (platform admin maintains those) and a Tenant.id for a hospital's own
    editable copy; is_template marks one meant to be cloned. Tenant.active_vaccination_schedule_id /
    active_milestone_schedule_id point at the live one. Plain IntegerField, not an FK, like the rest of the registry.
    """
    KIND_VACCINATION = "vaccination"
    KIND_MILESTONE   = "milestone"
    KIND_CHOICES = [(KIND_VACCINATION, "Vaccination"), (KIND_MILESTONE, "Milestone")]

    kind            = models.CharField(max_length=15, choices=KIND_CHOICES)
    name            = models.CharField(max_length=200)
    description     = models.TextField(blank=True)
    owner_tenant_id = models.IntegerField(null=True, blank=True)  # null = system-level template
    is_template     = models.BooleanField(default=False)
    active          = models.BooleanField(default=True)  # soft-disable instead of delete
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "registry"
        db_table  = "vaccination_schedule"

    def __str__(self):
        return self.name


class ScheduleRule(models.Model):
    """
    One slot in a Schedule: a vaccine dose ("BCG", dose 1, "Birth") or a milestone ("Sits without support", domain
    gross_motor, "6 months"). `item` is the vaccine or milestone name; vaccine_name / milestone read and write it, so
    callers keep their own word for it. dose_number only matters for vaccines, domain only for milestones.

    min_age_days / max_age_days only drive the informational "upcoming / due now" timing on a slot with no record; they
    never produce an "overdue" verdict (see vaccine_schedule.py).
    """
    DOMAIN_GROSS_MOTOR = "gross_motor"
    DOMAIN_FINE_MOTOR  = "fine_motor"
    DOMAIN_LANGUAGE    = "language"
    DOMAIN_COGNITIVE   = "cognitive"
    DOMAIN_SOCIAL      = "social_emotional"
    DOMAIN_CHOICES = [
        (DOMAIN_GROSS_MOTOR, "Gross Motor"),
        (DOMAIN_FINE_MOTOR,  "Fine Motor"),
        (DOMAIN_LANGUAGE,    "Language / Communication"),
        (DOMAIN_COGNITIVE,   "Cognitive"),
        (DOMAIN_SOCIAL,      "Social / Emotional"),
    ]

    schedule         = models.ForeignKey(Schedule, on_delete=models.CASCADE, related_name="rules")
    item             = models.CharField(max_length=200)
    dose_number      = models.PositiveIntegerField(default=1)
    domain           = models.CharField(max_length=20, blank=True, choices=DOMAIN_CHOICES)
    scheduled_label  = models.CharField(max_length=50)   # human age-window label, e.g. "Birth", "6 weeks", "9 months"
    min_age_days     = models.PositiveIntegerField()
    max_age_days     = models.PositiveIntegerField(null=True, blank=True)
    mandatory        = models.BooleanField(default=True)  # false = "nice to note", not a red flag if missed
    sort_order       = models.PositiveIntegerField(default=0)

    class Meta:
        app_label = "registry"
        db_table  = "vaccination_schedule_rule"
        ordering  = ["sort_order"]

    # the two names callers already use for `item`
    @property
    def vaccine_name(self):
        return self.item

    @vaccine_name.setter
    def vaccine_name(self, value):
        self.item = value

    milestone = vaccine_name

    def save(self, *args, update_fields=None, **kwargs):
        if update_fields is not None:
            update_fields = ["item" if f in ("vaccine_name", "milestone") else f for f in update_fields]
        super().save(*args, update_fields=update_fields, **kwargs)

    def __str__(self):
        return f"{self.schedule.name} — {self.item} ({self.scheduled_label})"


class _OfKind(models.Manager):
    """Rows of one kind only, for the four classes below."""
    def __init__(self, kind, through=""):
        super().__init__()
        self.kind, self.through = kind, through

    def get_queryset(self):
        return super().get_queryset().filter(**{self.through + "kind": self.kind})


class _KindSaved:
    """Mixin for the schedule wrappers: stamps the kind on save."""
    def save(self, *args, **kwargs):
        self.kind = self.KIND
        super().save(*args, **kwargs)


# The names the rest of the code uses; each is the one table, narrowed to its kind.
class VaccinationSchedule(_KindSaved, Schedule):
    KIND = Schedule.KIND_VACCINATION
    objects = _OfKind(KIND)

    class Meta:
        proxy = True
        app_label = "registry"


class MilestoneSchedule(_KindSaved, Schedule):
    KIND = Schedule.KIND_MILESTONE
    objects = _OfKind(KIND)

    class Meta:
        proxy = True
        app_label = "registry"


class VaccinationScheduleRule(ScheduleRule):
    objects = _OfKind(Schedule.KIND_VACCINATION, "schedule__")

    class Meta:
        proxy = True
        app_label = "registry"


class MilestoneScheduleRule(ScheduleRule):
    objects = _OfKind(Schedule.KIND_MILESTONE, "schedule__")

    class Meta:
        proxy = True
        app_label = "registry"


class SharedMilestoneRecord(models.Model):
    """
    One developmental-milestone assessment, visible at every hospital. status: "achieved" (achieved_date is set),
    "not_yet" (assessed, not reached) or "concern" (flagged by the pediatrician for follow-up). A schedule slot with no
    record is "unassessed" in the roadmap; that is worked out, not stored.
    """
    STATUS_ACHIEVED = "achieved"
    STATUS_NOT_YET  = "not_yet"
    STATUS_CONCERN  = "concern"
    STATUS_CHOICES = [
        (STATUS_ACHIEVED, "Achieved"),
        (STATUS_NOT_YET,  "Not Yet"),
        (STATUS_CONCERN,  "Concern Flagged"),
    ]

    awpid            = models.CharField(max_length=30, db_index=True)
    domain           = models.CharField(max_length=20, choices=MilestoneScheduleRule.DOMAIN_CHOICES)
    milestone        = models.CharField(max_length=200)
    scheduled_label  = models.CharField(max_length=50, blank=True)   # the schedule slot it fills, e.g. "6 months"
    status           = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_ACHIEVED)
    achieved_date    = models.DateField(null=True, blank=True)
    assessed_date    = models.DateField(null=True, blank=True)  # when this observation was made, regardless of status
    notes            = models.TextField(blank=True)

    recorded_by_name = models.CharField(max_length=200, blank=True)  # a name, not a link: staff live in hospital databases
    source_tenant_id = models.IntegerField(null=True, blank=True)

    created_at       = models.DateTimeField(auto_now_add=True)
    updated_at       = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "registry"
        db_table  = "shared_milestone_record"
        indexes = [models.Index(fields=["awpid", "domain"])]
        ordering  = ["assessed_date"]

    def __str__(self):
        return f"{self.awpid} — {self.milestone} ({self.status})"


class BirthHistory(models.Model):
    """
    A child's birth history, one row per patient. Front desk can capture it at registration and the pediatrician can add
    or correct it later. recorded_by / updated_by are StaffUser ids (plain numbers, not links).
    """
    DELIVERY_NORMAL   = "normal"
    DELIVERY_C_SECTION = "c_section"
    DELIVERY_ASSISTED  = "assisted"      # forceps / vacuum
    DELIVERY_UNKNOWN   = "unknown"
    DELIVERY_MODE_CHOICES = [
        (DELIVERY_NORMAL,    "Normal Vaginal Delivery"),
        (DELIVERY_C_SECTION, "C-Section"),
        (DELIVERY_ASSISTED,  "Assisted (Forceps/Vacuum)"),
        (DELIVERY_UNKNOWN,   "Unknown"),
    ]

    patient = models.OneToOneField("patients.Patient", on_delete=models.CASCADE,
                                   related_name="birth_history")

    gestational_age_weeks = models.PositiveSmallIntegerField(null=True, blank=True)
    birth_weight_kg        = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    delivery_mode           = models.CharField(max_length=12, choices=DELIVERY_MODE_CHOICES, blank=True)
    multiple_birth          = models.CharField(max_length=50, blank=True)   # free text: "twin", "triplet A of 3"

    nicu_admission = models.BooleanField(default=False)
    nicu_days       = models.PositiveSmallIntegerField(null=True, blank=True)
    birth_complications = models.TextField(blank=True)  # e.g. jaundice, birth asphyxia
    congenital_conditions = models.TextField(blank=True)

    apgar_score_1min  = models.PositiveSmallIntegerField(null=True, blank=True)
    apgar_score_5min  = models.PositiveSmallIntegerField(null=True, blank=True)

    notes = models.TextField(blank=True)

    recorded_by = models.IntegerField(null=True, blank=True)  # StaffUser.id — who first captured this
    recorded_at = models.DateTimeField(auto_now_add=True)
    updated_by  = models.IntegerField(null=True, blank=True)  # StaffUser.id — who last edited this
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "patients"
        db_table  = "birth_history"

    def __str__(self):
        return f"{self.patient.uhid} — birth history"
