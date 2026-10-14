"""Clinical facts shared across hospitals: diagnoses, prescriptions, labs, allergies, vitals, birth history, vaccinations, milestones."""

from django.db import models

from .schedules import MilestoneScheduleRule


class SharedDiagnosis(models.Model):
    """
    Sanitized diagnosis copy written from any hospital on encounter close.
    What is shared: clinical content (what + when).
    What is NEVER shared: source_hospital_id, doctor identity, hospital name.
    """
    awpid           = models.CharField(max_length=30, db_index=True)
    icd10_code      = models.CharField(max_length=20, blank=True)
    description     = models.TextField(blank=True)
    clinical_status = models.CharField(max_length=20, default="active")  # FHIR R4
    onset_date      = models.DateField(null=True, blank=True)
    source_hospital_id= models.IntegerField()   # stored internally, NEVER returned to other hospitals
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "atomwalk"
        db_table  = "shared_diagnosis"


class SharedPrescription(models.Model):
    """
    One row per finalized prescription (header). Items are stored in SharedPrescriptionItem.
    """
    awpid            = models.CharField(max_length=30, db_index=True)
    prescribed_on    = models.DateField()
    source_hospital_id = models.IntegerField()
    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "atomwalk"
        db_table  = "shared_prescription"


class SharedPrescriptionItem(models.Model):
    """Drug line item for a SharedPrescription."""
    prescription     = models.ForeignKey(SharedPrescription, on_delete=models.CASCADE,
                                         related_name="items")
    drug_name        = models.CharField(max_length=200)
    dose             = models.CharField(max_length=50, blank=True)
    unit             = models.CharField(max_length=20, blank=True)
    frequency        = models.CharField(max_length=50, blank=True)
    route            = models.CharField(max_length=50, blank=True)
    duration_days    = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        app_label = "atomwalk"
        db_table  = "shared_prescription_item"


class SharedLabResult(models.Model):
    """
    Sanitized lab report copy written when a report is delivered.
    result_summary is free text / structured JSON; file_url is optional.

    file_data/mime_type hold the actual result file as a base64 data URI —
    file_url is a URLField (200-char, URL-validated) so it can't hold one;
    added alongside rather than repurposed, since nothing currently populates
    file_url and there's no reason to risk breaking it.
    """
    awpid            = models.CharField(max_length=30, db_index=True)
    test_name        = models.CharField(max_length=200)
    result_summary   = models.TextField(blank=True)
    file_url         = models.URLField(blank=True)
    file_data        = models.TextField(blank=True)
    mime_type        = models.CharField(max_length=100, blank=True)
    delivered_at     = models.DateTimeField()
    source_hospital_id = models.IntegerField()
    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "atomwalk"
        db_table  = "shared_lab_result"


class SharedAllergy(models.Model):
    """Written when an allergy is recorded or updated."""
    awpid             = models.CharField(max_length=30, db_index=True)
    substance         = models.CharField(max_length=200)
    reaction          = models.TextField(blank=True)
    severity          = models.CharField(max_length=20, blank=True)  # mild/moderate/severe
    is_active         = models.BooleanField(default=True)
    source_hospital_id  = models.IntegerField()
    recorded_at       = models.DateTimeField()
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "atomwalk"
        db_table  = "shared_allergy"


class SharedVital(models.Model):
    """
    Sanitized vital snapshot written on finalization.
    All numeric fields are nullable — only measured fields are populated.
    """
    awpid             = models.CharField(max_length=30, db_index=True)
    recorded_at       = models.DateTimeField()
    source            = models.CharField(max_length=20, default="clinic")  # clinic / home
    bp_systolic       = models.SmallIntegerField(null=True, blank=True)
    bp_diastolic      = models.SmallIntegerField(null=True, blank=True)
    pulse_rate        = models.SmallIntegerField(null=True, blank=True)
    spo2              = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    temperature       = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    weight_kg         = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    height_cm         = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    resp_rate         = models.SmallIntegerField(null=True, blank=True)
    blood_sugar_mgdl  = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    # Pediatric-only measurement, mirrors apps.opd.models.Vitals.head_circumference_cm
    # — only populated when the source Vitals row had it set (i.e. for minors).
    head_circumference_cm = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    source_hospital_id  = models.IntegerField()
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "atomwalk"
        db_table  = "shared_vital"


class SharedBirthHistory(models.Model):
    """
    Birth history shared across hospitals: a copy of BirthHistory written whenever a hospital saves one, so the emergency
    summary and other hospitals can see it. One row per child (an edit overwrites it); source_hospital_id is the hospital
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
    source_hospital_id = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "atomwalk"
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

    source_hospital_id    = models.IntegerField(null=True, blank=True)  # the hospital that logged or verified it; empty until reviewed
    recorded_by          = models.CharField(max_length=20, default="patient")  # "patient" or "staff"

    created_at           = models.DateTimeField(auto_now_add=True)
    updated_at           = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "atomwalk"
        db_table  = "shared_vaccination"
        indexes = [models.Index(fields=["awpid", "verification_status"])]
        ordering  = ["administered_date"]

    def __str__(self):
        return f"{self.awpid} — {self.vaccine_name} ({self.verification_status})"


class MilestoneRecord(models.Model):
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
    source_hospital_id = models.IntegerField(null=True, blank=True)

    created_at       = models.DateTimeField(auto_now_add=True)
    updated_at       = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "atomwalk"
        db_table  = "milestone_records"
        indexes = [models.Index(fields=["awpid", "domain"])]
        ordering  = ["assessed_date"]

    def __str__(self):
        return f"{self.awpid} — {self.milestone} ({self.status})"
