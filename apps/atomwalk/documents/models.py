from django.db import models

from core.storage import document_file_path, documents_storage
from django.utils import timezone
from django.contrib.auth import Users

NOT_CLASSIFIED = "not_classified"
DOCUMENT_TYPES = {
    "prescription": "Prescription",
    "lab_report": "Lab Report",
    "imaging_report": "Imaging Report",
    "discharge_summary": "Discharge Summary",
    "consultation_note": "Consultation Note",
    "medical_bill": "Medical Bill",
    "vaccination_record": "Vaccination Record",
    "referral_letter": "Referral Letter",
    "medical_certificate": "Medical Certificate",
    "other": "Other",
    NOT_CLASSIFIED: "Not Classified",
}
DOCUMENT_TYPE_CHOICES = list(DOCUMENT_TYPES.items())


CHOOSABLE_TYPES = [code for code in DOCUMENT_TYPES if code != NOT_CLASSIFIED]


RULE_CLASSIFIED = "rule_classified"
REVIEW_REQUIRED = "review_required"
HUMAN_CLASSIFIED = "human_classified"
ISSUED = "issued"
CLASSIFIER_RULES = "rule_engine"
CLASSIFIER_HUMAN = "human"
CLASSIFIER_HOSPITAL = "hospital"


SEVERITY_CHOICES = [("NORMAL", "Normal"), ("MILD", "Mild"), ("ABNORMAL", "Abnormal"), ("CRITICAL", "Critical")]
CATEGORY_CHOICES = [("CHRONIC", "Chronic"), ("ACUTE", "Acute")]
SOURCE_CHOICES = [("HOSPITAL", "Written by a hospital"), ("EXTRACTED", "Read from a document"), ("MANUAL", "Entered by staff")]
DOMAIN_CHOICES = [
    ("gross_motor", "Gross Motor"),
    ("fine_motor", "Fine Motor"),
    ("language", "Language / Communication"),
    ("cognitive", "Cognitive"),
    ("social_emotional", "Social / Emotional"),
]


class DocumentBatch(models.Model):
    class Status(models.TextChoices):
        PROCESSING = "processing"
        COMPLETED = "completed"
        COMPLETED_WITH_ERRORS = "completed_with_errors"

    patient = models.ForeignKey("patients.Patient", on_delete=models.CASCADE)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PROCESSING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "document_batch"


class MedicalDocument(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued"
        EXTRACTING = "extracting"
        CLASSIFYING = "classifying"
        COMPLETED = "completed"
        REVIEW_REQUIRED = "review_required"
        FAILED = "failed"

    IN_PROGRESS = (Status.QUEUED, Status.EXTRACTING, Status.CLASSIFYING)

    patient = models.ForeignKey("patients.Patient", on_delete=models.CASCADE)
    batch = models.ForeignKey(DocumentBatch, null=True, blank=True, on_delete=models.SET_NULL, related_name="d_documents")
    file = models.FileField(upload_to=document_file_path, storage=documents_storage, max_length=500)
    file_name = models.CharField(max_length=100, blank=True)
    mime_type = models.CharField(max_length=100, blank=True)
    size = models.PositiveBigIntegerField(null=True, blank=True)
    document_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.QUEUED, db_index=True)
    error_message = models.TextField(blank=True)
    document_type = models.CharField(max_length=30, choices=DOCUMENT_TYPE_CHOICES, default=NOT_CLASSIFIED)

    class Source(models.TextChoices):
        UPLOAD = "upload"
        ENCOUNTER = "encounter"
        ENCOUNTER_HANDWRITTEN_RX = "encounter_handwritten_rx"
        LAB_REQUEST = "lab_request"
        LAB_REPORT = "lab_report"

    source_type = models.CharField(max_length=30, choices=Source.choices, default=Source.UPLOAD, db_index=True)
    source_id = models.CharField(max_length=80, blank=True, db_index=True)
    source_hospital = models.ForeignKey("hospital_master.Hospital", null=True, blank=True, on_delete=models.SET_NULL)
    document_ref = models.CharField(max_length=40, blank=True)
    uploaded_by = models.CharField(max_length=10, default="patient")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "medical_documents"



class DocumentExtraction(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        DONE = "done"
        FAILED = "failed"
        SKIPPED = "skipped"

    document = models.OneToOneField(MedicalDocument, on_delete=models.CASCADE, related_name="d_extraction")
    extracted_text = models.TextField(blank=True)
    engine = models.CharField(max_length=30, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    normalised = models.JSONField(default=dict, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "document_extraction"


class PatientDocumentClassification(models.Model):
    document = models.OneToOneField(MedicalDocument, on_delete=models.CASCADE, related_name="d_classification")
    ai_document_type = models.CharField(max_length=50, null=True, blank=True)
    classifier = models.CharField(max_length=30, default=CLASSIFIER_RULES)
    rule_score = models.FloatField(null=True, blank=True)
    second_best_score = models.FloatField(null=True, blank=True)
    score_margin = models.FloatField(null=True, blank=True)
    rule_matches = models.JSONField(null=True, blank=True)
    human_document_type = models.CharField(max_length=50, null=True, blank=True)
    status = models.CharField(max_length=30, default=RULE_CLASSIFIED)

    class Meta:
        db_table = "patient_document_classification"


class BirthHistory(models.Model):
    DELIVERY_NORMAL = "normal"
    DELIVERY_C_SECTION = "c_section"
    DELIVERY_ASSISTED = "assisted"
    DELIVERY_UNKNOWN = "unknown"
    DELIVERY_MODE_CHOICES = [
        (DELIVERY_NORMAL, "Normal Vaginal Delivery"),
        (DELIVERY_C_SECTION, "C-Section"),
        (DELIVERY_ASSISTED, "Assisted (Forceps/Vacuum)"),
        (DELIVERY_UNKNOWN, "Unknown"),
    ]

    patient = models.OneToOneField("patients.Patient", on_delete=models.CASCADE, related_name="p_birth_history")
    document = models.ForeignKey(MedicalDocument, null=True, blank=True, on_delete=models.SET_NULL, 
                                 related_name="d_birth_history")
    source_hospital = models.ForeignKey("hospital_master.Hospital", null=True, blank=True, on_delete=models.SET_NULL, 
                                            related_name="h_birth_history")
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="MANUAL")
    gestational_age_weeks = models.PositiveSmallIntegerField(null=True, blank=True)
    birth_weight_kg = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True)
    delivery_mode = models.CharField(max_length=12, choices=DELIVERY_MODE_CHOICES, blank=True)
    multiple_birth = models.CharField(max_length=50, blank=True)
    nicu_admission = models.BooleanField(default=False)
    nicu_days = models.PositiveSmallIntegerField(null=True, blank=True)
    birth_complications = models.TextField(blank=True)
    congenital_conditions = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="u_birth_history")
    recorded_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="u_birth_history_updated")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "birth_history"


class ClinicalEvent(models.Model):
    TYPES = [("DIAGNOSIS", "Diagnosis"), ("ADMISSION", "Admission"), ("PROCEDURE", "Procedure")]

    patient = models.ForeignKey("patients.Patient", null=True, blank=True, on_delete=models.CASCADE, related_name="p_clinical_events")
    document = models.ForeignKey("documents.MedicalDocument", null=True, blank=True, on_delete=models.s)
    source_hospital = models.ForeignKey("hospital_master.Hospital", null=True, blank=True, on_delete=models.SET_NULL)
    event_date = models.DateField(null=True, blank=True, db_index=True)
    event_type = models.CharField(max_length=12, choices=TYPES, default="DIAGNOSIS")
    condition_text = models.TextField(blank=True)
    icd10 = models.CharField(max_length=20, blank=True)
    clinical_status = models.CharField(max_length=20, default="active")
    condition_group = models.CharField(max_length=40, blank=True)
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES, blank=True)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default="NORMAL")
    is_provisional = models.BooleanField(default=False)
    evidence = models.CharField(max_length=255, blank=True)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="EXTRACTED")
    episode = models.ForeignKey("documents.HealthEpisode", null=True, blank=True, on_delete=models.SET_NULL, related_name="events")
    is_verified = models.BooleanField(default=False)
    is_rejected = models.BooleanField(default=False)
    verified_by_id = models.IntegerField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    discharged_on = models.DateField(null=True, blank=True)
    ward = models.CharField(max_length=10, blank=True)
    is_critical = models.BooleanField(default=False)
    critical_terms = models.JSONField(default=list, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "clinical_event"
        indexes = [models.Index(fields=["patient", "event_date"])]


class GrowthMeasurement(models.Model):
    patient = models.ForeignKey("patients.Patient", null=True, blank=True, on_delete=models.CASCADE)
    document = models.ForeignKey("documents.MedicalDocument", null=True, blank=True, on_delete=models.CASCADE)
    appointment_id = models.UUIDField(null=True, blank=True, db_index=True)
    source_hospital = models.ForeignKey("hospital_master.Hospital", null=True, blank=True, on_delete=models.SET_NULL)
    source = models.CharField(max_length=10, default="clinic")
    recorded_by_user_id = models.UUIDField(null=True, blank=True)
    measured_on = models.DateField(db_index=True)
    weight_kg = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    height_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    head_circumference_cm = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    weight_z = models.FloatField(null=True, blank=True)
    height_z = models.FloatField(null=True, blank=True)
    head_circ_z = models.FloatField(null=True, blank=True)
    weight_pct = models.FloatField(null=True, blank=True)
    height_pct = models.FloatField(null=True, blank=True)
    head_circ_pct = models.FloatField(null=True, blank=True)
    flags = models.JSONField(default=dict, blank=True)
    reference_source = models.CharField(max_length=5, blank=True)
    is_rejected = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "growth_measurement"
        constraints = [models.UniqueConstraint(fields=["appointment_id"], condition=models.Q(appointment_id__isnull=False),
                                               name="uniq_growth_per_appointment")]


class HealthEpisode(models.Model):
    patient = models.ForeignKey("patients.Patient", null=True, blank=True, on_delete=models.CASCADE)
    key = models.CharField(max_length=80)
    condition_group = models.CharField(max_length=40, db_index=True)
    label = models.CharField(max_length=255)
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    last_seen = models.DateField()
    peak_severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default="NORMAL")
    event_count = models.PositiveIntegerField(default=0)
    is_provisional = models.BooleanField(default=False)
    known_group = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "health_episode"
        constraints = [models.UniqueConstraint(fields=["patient", "key"], name="uniq_episode_per_patient_key")]
        indexes = [models.Index(fields=["patient", "start_date"])]


class ImmunizationRecord(models.Model):
    SOURCE_CLINIC = "clinic"
    SOURCE_SELF_REPORTED = "self_reported"
    SOURCE_DOCTOR_ORDERED = "doctor_ordered"
    SOURCE_EXTRACTED = "extracted"
    SOURCE_MANUAL = "manual"
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

    patient             = models.ForeignKey("patients.Patient", null=True, blank=True, on_delete=models.CASCADE)
    document            = models.ForeignKey("documents.MedicalDocument", null=True, blank=True, on_delete=models.CASCADE)
    vaccine_name        = models.CharField(max_length=100)
    vaccines            = models.JSONField(default=list, blank=True)
    scheduled_label     = models.CharField(max_length=50, blank=True)
    administered_date   = models.DateField(null=True, blank=True)
    due_date             = models.DateField(null=True, blank=True)
    reason               = models.TextField(blank=True)
    dose_number          = models.PositiveIntegerField(null=True, blank=True)

    source              = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_CLINIC)
    verification_status = models.CharField(max_length=20, choices=VERIFICATION_CHOICES, default=STATUS_VERIFIED, db_index=True)
    verified_by_name    = models.CharField(max_length=200, blank=True)
    verified_at         = models.DateTimeField(null=True, blank=True)
    review_notes        = models.TextField(blank=True)

    file_name           = models.CharField(max_length=255, blank=True)
    mime_type            = models.CharField(max_length=100, blank=True)
    file_data            = models.TextField(blank=True)

    source_hospital      = models.ForeignKey("hospital_master.Hospital", null=True, blank=True, on_delete=models.SET_NULL)

    created_at           = models.DateTimeField(auto_now_add=True)
    updated_at           = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "immunization_record"
        indexes = [models.Index(fields=["patient", "verification_status"])]
        ordering  = ["administered_date"]


class LabResult(models.Model):
    patient = models.ForeignKey("patients.Patient", null=True, blank=True, on_delete=models.CASCADE)
    document = models.ForeignKey("documents.MedicalDocument", null=True, blank=True, on_delete=models.CASCADE)
    source_hospital = models.ForeignKey("hospital_master.Hospital", null=True, blank=True, on_delete=models.SET_NULL)
    test_name = models.CharField(max_length=200, blank=True)
    analyte = models.CharField(max_length=40, blank=True, db_index=True)
    value = models.FloatField(null=True, blank=True)
    unit_raw = models.CharField(max_length=30, blank=True)
    result_summary = models.TextField(blank=True)
    collected_on = models.DateField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    age_band = models.CharField(max_length=12, blank=True)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default="NORMAL")
    direction = models.CharField(max_length=4, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "lab_result"


class MilestoneRecord(models.Model):
    STATUS_ACHIEVED = "achieved"
    STATUS_NOT_YET  = "not_yet"
    STATUS_CONCERN  = "concern"
    STATUS_CHOICES = [
        (STATUS_ACHIEVED, "Achieved"),
        (STATUS_NOT_YET,  "Not Yet"),
        (STATUS_CONCERN,  "Concern Flagged"),
    ]

    patient          = models.ForeignKey("patients.Patient", null=True, blank=True, on_delete=models.CASCADE)
    domain           = models.CharField(max_length=20, choices=DOMAIN_CHOICES)
    milestone        = models.CharField(max_length=200)
    scheduled_label  = models.CharField(max_length=50, blank=True)
    status           = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_ACHIEVED)
    achieved_date    = models.DateField(null=True, blank=True)
    assessed_date    = models.DateField(null=True, blank=True)
    notes            = models.TextField(blank=True)

    recorded_by_name = models.CharField(max_length=200, blank=True)
    source_hospital = models.ForeignKey("hospital_master.Hospital", null=True, blank=True, on_delete=models.SET_NULL)

    created_at       = models.DateTimeField(auto_now_add=True)
    updated_at       = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "milestone_records"
        indexes = [models.Index(fields=["patient", "domain"])]
        ordering  = ["assessed_date"]


class RecurrenceFlag(models.Model):
    patient = models.ForeignKey("patients.Patient", null=True, blank=True, on_delete=models.CASCADE)
    condition_group = models.CharField(max_length=40)
    label = models.CharField(max_length=255)
    triggered_on = models.DateField()
    rule = models.JSONField(default=dict)
    episodes_last_12m = models.PositiveIntegerField(default=0)
    clinical_hint = models.CharField(max_length=255, blank=True)
    acknowledged_by_id = models.IntegerField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "recurrence_flag"
        constraints = [models.UniqueConstraint(fields=["patient", "condition_group"], name="uniq_recurrence_per_patient_group")]


class SharedAllergy(models.Model):
    patient           = models.ForeignKey("patients.Patient", null=True, blank=True, on_delete=models.CASCADE)
    substance         = models.CharField(max_length=200)
    reaction          = models.TextField(blank=True)
    severity          = models.CharField(max_length=20, blank=True)
    is_active         = models.BooleanField(default=True)
    source_hospital  = models.ForeignKey("hospital_master.Hospital", null=True, blank=True, on_delete=models.SET_NULL)
    recorded_at       = models.DateTimeField()
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "shared_allergy"


class SharedPrescriptionItem(models.Model):
    document = models.ForeignKey("documents.MedicalDocument", null=True, blank=True, on_delete=models.CASCADE, related_name="d_drug_items")
    drug_name = models.CharField(max_length=200)
    dose = models.CharField(max_length=50, blank=True)
    unit = models.CharField(max_length=20, blank=True)
    frequency = models.CharField(max_length=50, blank=True)
    route = models.CharField(max_length=50, blank=True)
    duration_days = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        db_table = "shared_prescription_item"


class Vitals(models.Model):
    patient = models.ForeignKey("patients.Patient", null=True, blank=True, on_delete=models.CASCADE)
    appointment_id = models.UUIDField(null=True, blank=True, db_index=True)
    source_hospital = models.ForeignKey("hospital_master.Hospital", null=True, blank=True, on_delete=models.SET_NULL)
    source = models.CharField(max_length=20, default="clinic")
    recorded_at = models.DateTimeField(default=timezone.now, db_index=True)
    recorded_by_user_id = models.UUIDField(null=True, blank=True)
    systolic_bp = models.IntegerField(null=True, blank=True)
    diastolic_bp = models.IntegerField(null=True, blank=True)
    pulse_rate = models.IntegerField(null=True, blank=True)
    temperature = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    spo2 = models.IntegerField(null=True, blank=True)
    respiratory_rate = models.IntegerField(null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    height_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    blood_sugar_rbs = models.IntegerField(null=True, blank=True)
    nurse_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "vitals"
        constraints = [models.UniqueConstraint(fields=["appointment_id"], condition=models.Q(appointment_id__isnull=False),
                                               name="uniq_vitals_per_appointment")]


class ScheduleRule(models.Model):

    schedule         = models.ForeignKey("documents.Schedule", on_delete=models.CASCADE, related_name="rules")
    item             = models.CharField(max_length=200)
    dose_number      = models.PositiveIntegerField(default=1)
    domain           = models.CharField(max_length=20, blank=True, choices=DOMAIN_CHOICES)
    scheduled_label  = models.CharField(max_length=50)
    min_age_days     = models.PositiveIntegerField()
    max_age_days     = models.PositiveIntegerField(null=True, blank=True)
    mandatory        = models.BooleanField(default=True)
    sort_order       = models.PositiveIntegerField(default=0)

    class Meta:
        db_table  = "immunization_schedule_rules"
        ordering  = ["sort_order"]


class Schedule(models.Model):
    KIND_VACCINATION = "vaccination"
    KIND_MILESTONE   = "milestone"
    KIND_CHOICES = [(KIND_VACCINATION, "Vaccination"), (KIND_MILESTONE, "Milestone")]

    kind            = models.CharField(max_length=15, choices=KIND_CHOICES)
    name            = models.CharField(max_length=200)
    description     = models.TextField(blank=True)
    owner_hospital = models.ForeignKey("hospital_master.Hospital", null=True, blank=True, on_delete=models.CASCADE)
    is_template     = models.BooleanField(default=False)
    active          = models.BooleanField(default=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "immunization_schedules"
