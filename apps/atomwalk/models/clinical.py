"""
Clinical facts of a patient, kept once for every hospital to read. Every table has a link to the patient (null allowed;
deleting the patient deletes these rows) and, where a fact was read out of an uploaded file, a link to that document.
A hospital's own records are copied here as they are signed, with the id of the hospital they came from.

  clinical_event       diagnoses, admissions, procedures      health_episode / recurrence_flag   built from the events
  growth_measurement   a child's height, weight, head size    vitals                             everyone else's readings
  immunization_record  doses given, ordered or declined       milestone_records                  developmental assessments
  lab_result           lab reports and the values in them     birth_history                      one row per child
  shared_allergy       allergies                              shared_prescription_item           the drugs on a prescription
"""
from django.db import models
from django.utils import timezone

from .schedules import MilestoneScheduleRule

SEVERITY_CHOICES = [("NORMAL", "Normal"), ("MILD", "Mild"), ("ABNORMAL", "Abnormal"), ("CRITICAL", "Critical")]
CATEGORY_CHOICES = [("CHRONIC", "Chronic"), ("ACUTE", "Acute")]
SOURCE_CHOICES = [("HOSPITAL", "Written by a hospital"), ("EXTRACTED", "Read from a document"), ("MANUAL", "Entered by staff")]


def patient_link(related_name):
    """The link every clinical table has to the patient."""
    return models.ForeignKey("atomwalk.Patient", null=True, blank=True, on_delete=models.CASCADE, related_name=related_name)


def document_link(related_name="+"):
    """The uploaded file a fact was read from, when it was."""
    return models.ForeignKey("atomwalk.MedicalDocument", null=True, blank=True, on_delete=models.CASCADE, related_name=related_name)


class HealthEpisode(models.Model):
    """One illness or one long-running condition of a patient, built from their clinical events (episodes.py)."""
    patient = patient_link("episodes")
    key = models.CharField(max_length=80)                    # "ASTHMA" | "URTI:2024-03-01"
    condition_group = models.CharField(max_length=40, db_index=True)
    label = models.CharField(max_length=255)
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)       # empty = still ongoing (chronic)
    last_seen = models.DateField()
    peak_severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default="NORMAL")
    event_count = models.PositiveIntegerField(default=0)
    is_provisional = models.BooleanField(default=False)
    known_group = models.BooleanField(default=True)          # False = the condition is not in the groups list: a person should look
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "atomwalk"
        db_table = "health_episode"
        constraints = [models.UniqueConstraint(fields=["patient", "key"], name="uniq_episode_per_patient_key")]
        indexes = [models.Index(fields=["patient", "start_date"])]


class ClinicalEvent(models.Model):
    """
    One dated clinical fact: a diagnosis, an admission or a procedure. Written by a hospital when it signs a visit (and
    from a hospital admission), or read out of an uploaded document. A hospital's id is stored but never shown to other
    hospitals.
    """
    TYPES = [("DIAGNOSIS", "Diagnosis"), ("ADMISSION", "Admission"), ("PROCEDURE", "Procedure")]

    patient = patient_link("clinical_events")
    document = document_link("clinical_events")
    source_hospital_id = models.IntegerField(null=True, blank=True)    # stored internally, NEVER returned to other hospitals
    event_date = models.DateField(null=True, blank=True, db_index=True)
    event_type = models.CharField(max_length=12, choices=TYPES, default="DIAGNOSIS")
    condition_text = models.TextField(blank=True)
    icd10 = models.CharField(max_length=20, blank=True)
    clinical_status = models.CharField(max_length=20, default="active")  # FHIR R4
    condition_group = models.CharField(max_length=40, blank=True)
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES, blank=True)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default="NORMAL")
    is_provisional = models.BooleanField(default=False)
    evidence = models.CharField(max_length=255, blank=True)            # the words it was read from
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="EXTRACTED")
    episode = models.ForeignKey(HealthEpisode, null=True, blank=True, on_delete=models.SET_NULL, related_name="events")  # episodes are rebuilt, so they must not take their events with them
    is_verified = models.BooleanField(default=False)
    is_rejected = models.BooleanField(default=False)                   # a clinician said "wrong": left out
    verified_by_id = models.IntegerField(null=True, blank=True)        # a staff id in the hospital's database
    verified_at = models.DateTimeField(null=True, blank=True)
    # an admission also has
    discharged_on = models.DateField(null=True, blank=True)
    ward = models.CharField(max_length=10, blank=True)
    is_critical = models.BooleanField(default=False)
    critical_terms = models.JSONField(default=list, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "atomwalk"
        db_table = "clinical_event"
        indexes = [models.Index(fields=["patient", "event_date"])]


class RecurrenceFlag(models.Model):
    """A condition that keeps coming back (episodes.py), for a clinician to look at."""
    patient = patient_link("recurrence_flags")
    condition_group = models.CharField(max_length=40)
    label = models.CharField(max_length=255)
    triggered_on = models.DateField()
    rule = models.JSONField(default=dict)
    episodes_last_12m = models.PositiveIntegerField(default=0)
    clinical_hint = models.CharField(max_length=255, blank=True)
    acknowledged_by_id = models.IntegerField(null=True, blank=True)    # a staff id in the hospital's database
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "atomwalk"
        db_table = "recurrence_flag"
        constraints = [models.UniqueConstraint(fields=["patient", "condition_group"], name="uniq_recurrence_per_patient_group")]


class SharedPrescriptionItem(models.Model):
    """A drug on a prescription. The prescription itself is the patient's document (source "encounter")."""
    document = models.ForeignKey("atomwalk.MedicalDocument", null=True, blank=True, on_delete=models.CASCADE, related_name="drug_items")
    drug_name = models.CharField(max_length=200)
    dose = models.CharField(max_length=50, blank=True)
    unit = models.CharField(max_length=20, blank=True)
    frequency = models.CharField(max_length=50, blank=True)
    route = models.CharField(max_length=50, blank=True)
    duration_days = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        app_label = "atomwalk"
        db_table = "shared_prescription_item"


class LabResult(models.Model):
    """
    A lab report and the values read from it. A hospital writes one row per report when it delivers it (test name,
    summary, the file); a document read by the system gives one row per value (analyte, value, unit).
    """
    patient = patient_link("lab_results")
    document = document_link("lab_results")
    source_hospital_id = models.IntegerField(null=True, blank=True)
    test_name = models.CharField(max_length=200, blank=True)
    analyte = models.CharField(max_length=40, blank=True, db_index=True)
    value = models.FloatField(null=True, blank=True)
    unit_raw = models.CharField(max_length=30, blank=True)
    result_summary = models.TextField(blank=True)              # free text or structured JSON
    file_url = models.URLField(blank=True)
    file_data = models.TextField(blank=True)                   # the result file as a base64 data URI
    mime_type = models.CharField(max_length=100, blank=True)
    collected_on = models.DateField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    age_band = models.CharField(max_length=12, blank=True)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default="NORMAL")
    direction = models.CharField(max_length=4, blank=True)     # LOW | HIGH
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "atomwalk"
        db_table = "lab_result"


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


class Vitals(models.Model):
    """
    One set of vital signs: blood pressure, pulse, temperature, oxygen, breathing, blood sugar and the nurse's note. A
    child's height, weight and head size go to growth_measurement instead; an adult's height and weight stay here. Written
    when a nurse records them at a visit (appointment_id is that hospital's appointment, a plain id).
    """
    patient = patient_link("vitals")
    appointment_id = models.UUIDField(null=True, blank=True, db_index=True)
    source_hospital_id = models.IntegerField(null=True, blank=True)
    source = models.CharField(max_length=20, default="clinic")          # clinic / home
    recorded_at = models.DateTimeField(default=timezone.now, db_index=True)
    recorded_by_user_id = models.UUIDField(null=True, blank=True)
    systolic_bp = models.IntegerField(null=True, blank=True)            # mmHg
    diastolic_bp = models.IntegerField(null=True, blank=True)           # mmHg
    pulse_rate = models.IntegerField(null=True, blank=True)             # bpm
    temperature = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)  # °F
    spo2 = models.IntegerField(null=True, blank=True)                   # %
    respiratory_rate = models.IntegerField(null=True, blank=True)       # /min
    weight_kg = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    height_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    bmi = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    blood_sugar_rbs = models.IntegerField(null=True, blank=True)        # mg/dL random blood sugar
    nurse_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "atomwalk"
        db_table = "vitals"
        constraints = [models.UniqueConstraint(fields=["appointment_id"], condition=models.Q(appointment_id__isnull=False),
                                               name="uniq_vitals_per_appointment")]

    def save(self, *args, **kwargs):
        if self.weight_kg and self.height_cm and self.height_cm > 0:
            self.bmi = round(float(self.weight_kg) / ((float(self.height_cm) / 100) ** 2), 1)
        super().save(*args, **kwargs)


class GrowthMeasurement(models.Model):
    """A child's height, weight and head size on a day, with where it came from. One row per visit or per document."""
    patient = patient_link("growth")
    document = document_link("growth_measurements")
    appointment_id = models.UUIDField(null=True, blank=True, db_index=True)
    source_hospital_id = models.IntegerField(null=True, blank=True)
    source = models.CharField(max_length=10, default="clinic")          # clinic / home / extracted / manual
    recorded_by_user_id = models.UUIDField(null=True, blank=True)
    measured_on = models.DateField(db_index=True)
    age_months = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    height_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    head_circumference_cm = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    bmi = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    weight_z = models.FloatField(null=True, blank=True)
    height_z = models.FloatField(null=True, blank=True)
    head_circ_z = models.FloatField(null=True, blank=True)
    weight_pct = models.FloatField(null=True, blank=True)
    height_pct = models.FloatField(null=True, blank=True)
    head_circ_pct = models.FloatField(null=True, blank=True)
    flags = models.JSONField(default=dict, blank=True)                  # {"weight_kg": "LOW", ...}
    reference_source = models.CharField(max_length=5, blank=True)       # who | iap
    is_rejected = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "atomwalk"
        db_table = "growth_measurement"
        constraints = [models.UniqueConstraint(fields=["appointment_id"], condition=models.Q(appointment_id__isnull=False),
                                               name="uniq_growth_per_appointment")]

    def save(self, *args, **kwargs):
        if self.weight_kg and self.height_cm and self.height_cm > 0:
            self.bmi = round(float(self.weight_kg) / ((float(self.height_cm) / 100) ** 2), 1)
        super().save(*args, **kwargs)


class BirthHistory(models.Model):
    """
    A child's birth history, one row per child, kept for every hospital (and the emergency summary) to read. The front desk
    can capture it at registration and the pediatrician can add or correct it later; an edit overwrites it, and
    source_hospital_id is the hospital that last wrote it. recorded_by / updated_by are staff ids (plain numbers).
    """
    DELIVERY_NORMAL = "normal"
    DELIVERY_C_SECTION = "c_section"
    DELIVERY_ASSISTED = "assisted"      # forceps / vacuum
    DELIVERY_UNKNOWN = "unknown"
    DELIVERY_MODE_CHOICES = [
        (DELIVERY_NORMAL, "Normal Vaginal Delivery"),
        (DELIVERY_C_SECTION, "C-Section"),
        (DELIVERY_ASSISTED, "Assisted (Forceps/Vacuum)"),
        (DELIVERY_UNKNOWN, "Unknown"),
    ]

    patient = models.OneToOneField("atomwalk.Patient", null=True, blank=True, on_delete=models.CASCADE, related_name="birth_history")
    document = document_link("birth_histories")
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="MANUAL")
    source_hospital_id = models.IntegerField(null=True, blank=True)
    gestational_age_weeks = models.PositiveSmallIntegerField(null=True, blank=True)
    birth_weight_kg = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True)
    delivery_mode = models.CharField(max_length=12, choices=DELIVERY_MODE_CHOICES, blank=True)
    multiple_birth = models.CharField(max_length=50, blank=True)       # free text: "twin", "triplet A of 3"
    nicu_admission = models.BooleanField(default=False)
    nicu_days = models.PositiveSmallIntegerField(null=True, blank=True)
    birth_complications = models.TextField(blank=True)                 # e.g. jaundice, birth asphyxia
    congenital_conditions = models.TextField(blank=True)
    apgar_score_1min = models.PositiveSmallIntegerField(null=True, blank=True)
    apgar_score_5min = models.PositiveSmallIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    recorded_by = models.IntegerField(null=True, blank=True)           # staff id: who first captured this
    recorded_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.IntegerField(null=True, blank=True)            # staff id: who last edited this
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "atomwalk"
        db_table = "birth_history"

    def __str__(self):
        return f"{self.patient_id} — birth history"

    @property
    def is_preterm(self):
        return self.gestational_age_weeks is not None and self.gestational_age_weeks < 37

    @property
    def is_low_birth_weight(self):
        return self.birth_weight_kg is not None and self.birth_weight_kg < 2.5


class ImmunizationRecord(models.Model):
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
    SOURCE_EXTRACTED = "extracted"       # read out of an uploaded document
    SOURCE_MANUAL = "manual"             # entered by staff
    SOURCE_CHOICES = [
        (SOURCE_CLINIC, "Clinic administered"),
        (SOURCE_SELF_REPORTED, "Self reported"),
        (SOURCE_DOCTOR_ORDERED, "Doctor ordered"),
        (SOURCE_EXTRACTED, "Read from a document"),
        (SOURCE_MANUAL, "Entered by staff"),
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

    patient             = patient_link("immunizations")
    document            = document_link("immunizations")
    vaccine_name        = models.CharField(max_length=100)               # as written: "Hexaxim 2"
    vaccines            = models.JSONField(default=list, blank=True)     # what a combined shot is made of: ["DTwP", "Hib", ...]
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
        db_table  = "immunization_record"
        indexes = [models.Index(fields=["patient", "verification_status"])]
        ordering  = ["administered_date"]

    def __str__(self):
        return f"{self.patient_id} — {self.vaccine_name} ({self.verification_status})"


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

    patient          = patient_link("milestones")
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
        indexes = [models.Index(fields=["patient", "domain"])]
        ordering  = ["assessed_date"]

    def __str__(self):
        return f"{self.patient_id} — {self.milestone} ({self.status})"
