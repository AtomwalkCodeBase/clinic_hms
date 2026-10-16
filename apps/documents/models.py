from django.db import models
from django.utils import timezone
from apps.patients.models import Patient
from apps.hospital_master.models import Hospital
from django.contrib.auth.models import User

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
CLASSIFIER_CHOICES = [(CLASSIFIER_RULES, "Rule engine"), (CLASSIFIER_HUMAN, "Human"), (CLASSIFIER_HOSPITAL, "Hospital")]
CLASSIFICATION_STATUS_CHOICES = [
    (RULE_CLASSIFIED, "Classified by the rules"), (REVIEW_REQUIRED, "Review required"),
    (HUMAN_CLASSIFIED, "Classified by a person"), (ISSUED, "Issued by a hospital"),
]


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

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="d_batches")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PROCESSING)
    total_files = models.PositiveIntegerField(default=0)
    processed_files = models.PositiveIntegerField(default=0)
    failed_files = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "document_batch"

    def __str__(self):
        return f"Batch {self.id} for Patient {self.patient.awpid} - Status: {self.status}"
    
    def refresh(self):
        """
        Refresh the batch's status and counts based on the associated documents.
        """
        self.total_files = self.b_documents.count()
        self.processed_files = self.b_documents.exclude(status__in=MedicalDocument.IN_PROGRESS).count()
        self.failed_files = self.b_documents.filter(status=MedicalDocument.Status.FAILED).count()

        if self.failed_files > 0:
            self.status = self.Status.COMPLETED_WITH_ERRORS
        elif self.processed_files == self.total_files:
            self.status = self.Status.COMPLETED
        else:
            self.status = self.Status.PROCESSING

        self.save()
         

def get_patient_file_path(instance, filename):
    return f"patients/{instance.patient.awpid}/documents/{filename}"


class MedicalDocument(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued"
        EXTRACTING = "extracting"
        CLASSIFYING = "classifying"
        COMPLETED = "completed"
        REVIEW_REQUIRED = "review_required"
        FAILED = "failed"

    class Source(models.TextChoices):
            UPLOAD = "upload"
            ENCOUNTER = "encounter"
            ENCOUNTER_HANDWRITTEN_RX = "encounter_handwritten_rx"
            LAB_REQUEST = "lab_request"
            LAB_REPORT = "lab_report"
    
    IN_PROGRESS = (Status.QUEUED, Status.EXTRACTING, Status.CLASSIFYING)
    CREATED_BY_CHOICES = [("P", "Patient"), ("H", "Hospital")]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="p_documents")
    batch = models.ForeignKey(DocumentBatch, null=True, blank=True, on_delete=models.SET_NULL, related_name="b_documents")
    file_name = models.FileField(upload_to=get_patient_file_path, blank=True, null=True)
    document_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED, db_index=True)
    error_message = models.CharField(max_length=200, blank=True)
    doc_classification = models.CharField(max_length=30, choices=DOCUMENT_TYPE_CHOICES, default=NOT_CLASSIFIED)
    source_type = models.CharField(max_length=30, choices=Source.choices, default=Source.UPLOAD)
    source_id = models.UUIDField(null=True, blank=True)
    source_hospital = models.ForeignKey(Hospital, null=True, blank=True, on_delete=models.SET_NULL, related_name="h_documents")
    document_ref_name = models.CharField(max_length=50, blank=True)
    created_by_type = models.CharField(max_length=1, choices=CREATED_BY_CHOICES, default="P")
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="u_documents")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = "medical_documents"

    def __str__(self):
        return f"Document {self.id} for Patient {self.patient.awpid} - Status: {self.status}"
    
    @property
    def processing_status(self):
        if self.status in self.IN_PROGRESS:
            return "in_progress"
        elif self.status == self.Status.COMPLETED:
            return "completed"
        elif self.status == self.Status.REVIEW_REQUIRED:
            return "review_required"
        elif self.status == self.Status.FAILED:
            return "failed"
        else:
            return "unknown"


class DocumentExtraction(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        DONE = "done"
        FAILED = "failed"
        SKIPPED = "skipped"

    class Engine(models.TextChoices):
        PDF_TEXT = "pdf_text"
        OCR = "ocr"

    document = models.OneToOneField(MedicalDocument, on_delete=models.CASCADE, related_name="d_extraction")
    extracted_text = models.TextField(blank=True)
    engine = models.CharField(max_length=10, choices=Engine.choices, default=Engine.PDF_TEXT)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    normalised = models.JSONField(default=dict, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
        
    class Meta:
        db_table = "document_extraction"

    def __str__(self):
        return f"Extraction for Document {self.document.id} - Status: {self.status}"


class DocumentClassification(models.Model):
    document = models.OneToOneField(MedicalDocument, on_delete=models.CASCADE, related_name="d_classification")
    ai_classification = models.CharField(max_length=30, choices=DOCUMENT_TYPE_CHOICES, default=NOT_CLASSIFIED)
    classifier = models.CharField(max_length=30, choices=CLASSIFIER_CHOICES, default=CLASSIFIER_RULES)
    rule_score = models.FloatField(null=True, blank=True)
    second_best_score = models.FloatField(null=True, blank=True)
    rule_matches = models.JSONField(default=list, blank=True)
    human_classification = models.CharField(max_length=30, choices=DOCUMENT_TYPE_CHOICES, default=NOT_CLASSIFIED)
    status = models.CharField(max_length=30, choices=CLASSIFICATION_STATUS_CHOICES, default=RULE_CLASSIFIED)

    class Meta:
        db_table = "document_classification"

    def __str__(self):
        return f"Classification for Document {self.document.id} - Status: {self.status}"


class BirthHistory(models.Model):
    DELIVERY_NORMAL = "normal"
    DELIVERY_C_SECTION = "c_section"
    DELIVERY_ASSISTED = "assisted"
    DELIVERY_UNKNOWN = "unknown"
    MULTIPLE_BIRTH_CHOICES = [("single", "Single"), ("twins", "Twins"), ("triplets", "Triplets"), ("higher", "Four or more")]
    DELIVERY_MODE_CHOICES = [
        (DELIVERY_NORMAL, "Normal Vaginal Delivery"),
        (DELIVERY_C_SECTION, "C-Section"),
        (DELIVERY_ASSISTED, "Assisted (Forceps/Vacuum)"),
        (DELIVERY_UNKNOWN, "Unknown"),
    ]

    patient = models.OneToOneField(Patient, on_delete=models.CASCADE, related_name="p_birth_history")
    document = models.ForeignKey(MedicalDocument, null=True, blank=True, on_delete=models.SET_NULL, 
                                 related_name="d_birth_history")
    source_hospital = models.ForeignKey(Hospital, null=True, blank=True, on_delete=models.SET_NULL, 
                                            related_name="h_birth_history")
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="MANUAL")
    gestational_age_weeks = models.PositiveSmallIntegerField(null=True, blank=True)
    birth_weight_kg = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True)
    delivery_mode = models.CharField(max_length=12, choices=DELIVERY_MODE_CHOICES, blank=True)
    multiple_birth = models.CharField(max_length=10, choices=MULTIPLE_BIRTH_CHOICES, blank=True)
    nicu_admission = models.BooleanField(default=False)
    nicu_days = models.PositiveSmallIntegerField(null=True, blank=True)
    birth_complications = models.TextField(blank=True)
    congenital_conditions = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
   
    class Meta:
        db_table = "birth_history"

    def __str__(self):
        return f"Birth History for Patient {self.patient.awpid}"


class HealthEpisode(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="p_health_episodes")
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
        indexes = [models.Index(fields=["patient", "start_date"])]

    def __str__(self):
        return f"{self.label} ({self.start_date}) for patient {self.patient_id}"


class ClinicalEvent(models.Model):
    TYPES = [("DIAGNOSIS", "Diagnosis"), ("ADMISSION", "Admission"), ("PROCEDURE", "Procedure")]
    STATUS_CHOICES = [("active", "Active"), ("resolved", "Resolved")]
    VERIFICATION_PENDING, VERIFICATION_VERIFIED, VERIFICATION_REJECTED = "pending", "verified", "rejected"
    VERIFICATION_CHOICES = [(VERIFICATION_PENDING, "Pending"), (VERIFICATION_VERIFIED, "Verified"), (VERIFICATION_REJECTED, "Rejected")]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="p_clinical_events")
    document = models.ForeignKey(MedicalDocument, null=True, blank=True, on_delete=models.SET_NULL, related_name="d_clinical_events")
    source_hospital = models.ForeignKey(Hospital, null=True, blank=True, on_delete=models.SET_NULL, related_name="h_clinical_events")
    event_date = models.DateField(null=True, blank=True)
    event_type = models.CharField(max_length=12, choices=TYPES, default="DIAGNOSIS")
    condition_text = models.TextField(blank=True)
    icd10 = models.CharField(max_length=20, blank=True)
    clinical_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    condition_group = models.CharField(max_length=40, blank=True)
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES, blank=True)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default="NORMAL")
    is_provisional = models.BooleanField(default=False)
    evidence = models.CharField(max_length=255, blank=True)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="EXTRACTED")
    episode = models.ForeignKey(HealthEpisode, null=True, blank=True, on_delete=models.SET_NULL, related_name="e_clinical_events")
    remarks = models.CharField(max_length=255, blank=True)
    verification_status = models.CharField(max_length=10, choices=VERIFICATION_CHOICES, default=VERIFICATION_PENDING)
    verified_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="u_verified_events")
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "clinical_event"
        indexes = [models.Index(fields=["patient", "event_date"])]

    def __str__(self):
        return f"Clinical Event {self.id} for patient {self.patient_id} - Type: {self.event_type}"

    @property
    def is_verified(self):
        return self.verification_status == self.VERIFICATION_VERIFIED

    @property
    def is_rejected(self):
        return self.verification_status == self.VERIFICATION_REJECTED


class GrowthMeasurement(models.Model):
    SOURCE_GROWTH_CHOICES = [("clinic", "Clinic"), ("extracted", "Read from a document"), ("manual", "Entered by staff")]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="p_growth_measurements")
    document = models.ForeignKey(MedicalDocument, null=True, blank=True, on_delete=models.CASCADE, related_name="d_growth_measurements")
    source_hospital = models.ForeignKey(Hospital, null=True, blank=True, on_delete=models.SET_NULL, related_name="h_growth_measurements")
    source = models.CharField(max_length=10, choices=SOURCE_GROWTH_CHOICES, default="clinic")
    source_id = models.UUIDField(null=True, blank=True)
    measured_on = models.DateField(db_index=True)
    age_months = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
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
    reference_source = models.CharField(max_length=5, choices=[("who", "WHO"), ("iap", "IAP")], blank=True)
    is_rejected = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
            
    class Meta:
        db_table = "growth_measurement"
    
    def __str__(self):
        return f"Growth Measurement {self.id} for Patient {self.patient.awpid} - Measured on: {self.measured_on}"


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

    patient             = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="p_immunization_records")
    document            = models.ForeignKey(MedicalDocument, null=True, blank=True, on_delete=models.SET_NULL, related_name="d_immunization_records")
    source_hospital     = models.ForeignKey(Hospital, null=True, blank=True, on_delete=models.SET_NULL, related_name="h_immunization_records") 
    scheduled_label     = models.CharField(max_length=50, blank=True)
        
    vaccine_name        = models.CharField(max_length=100)
    vaccines            = models.JSONField(default=list, blank=True)
    due_date            = models.DateField(null=True, blank=True)
    administered_date   = models.DateField(null=True, blank=True)
    remarks             = models.CharField(max_length=200, blank=True)
    dose_number         = models.PositiveIntegerField(null=True, blank=True)
    source              = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_CLINIC)
    verification_status = models.CharField(max_length=20, choices=VERIFICATION_CHOICES, default=STATUS_VERIFIED)
    created_at           = models.DateTimeField(auto_now_add=True)
    updated_at           = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "immunization_record"
        ordering  = ["administered_date"]

    def __str__(self):
        return f"Immunization Record {self.id} for Patient {self.patient.awpid} - Vaccine: {self.vaccine_name}"


class LabResult(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="p_lab_results")
    document = models.ForeignKey(MedicalDocument, null=True, blank=True, on_delete=models.SET_NULL, related_name="d_lab_results")
    source_hospital = models.ForeignKey(Hospital, null=True, blank=True, on_delete=models.SET_NULL, related_name="h_lab_results")
    test_name = models.CharField(max_length=200, blank=True)
    analyte = models.CharField(max_length=40, blank=True, db_index=True)
    value = models.FloatField(null=True, blank=True)
    unit_raw = models.CharField(max_length=30, blank=True)
    collected_on = models.DateField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    age_band = models.CharField(max_length=12, blank=True)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default="NORMAL")
    direction = models.CharField(max_length=4, choices=[("LOW", "Low"), ("HIGH", "High")], blank=True)
    result_summary = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "lab_result"

    def __str__(self):
        return f"Lab Result {self.id} for Patient {self.patient.awpid} - Test: {self.test_name}"


class Admission(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="p_admissions")
    document = models.ForeignKey(MedicalDocument, null=True, blank=True, on_delete=models.SET_NULL, related_name="d_admissions")
    admitted_on = models.DateField()
    discharged_on = models.DateField(null=True, blank=True)
    ward = models.CharField(max_length=10, default="WARD")
    is_critical = models.BooleanField(default=False)
    critical_terms = models.JSONField(default=list, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "patient_admission"

    def __str__(self):
        return f"Admission {self.id} for patient {self.patient_id} on {self.admitted_on}"


# Not Reviewed
class MilestoneRecord(models.Model):
    STATUS_ACHIEVED = "achieved"
    STATUS_NOT_YET  = "not_yet"
    STATUS_CONCERN  = "concern"
    STATUS_CHOICES = [
        (STATUS_ACHIEVED, "Achieved"),
        (STATUS_NOT_YET,  "Not Yet"),
        (STATUS_CONCERN,  "Concern Flagged"),
    ]

    patient          = models.ForeignKey("patients.Patient", on_delete=models.CASCADE, related_name="p_milestone_records")
    domain           = models.CharField(max_length=20, choices=DOMAIN_CHOICES)
    milestone        = models.CharField(max_length=200)
    scheduled_label  = models.CharField(max_length=50, blank=True)
    status           = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_ACHIEVED)
    achieved_date    = models.DateField(null=True, blank=True)
    assessed_date    = models.DateField(null=True, blank=True)
    notes            = models.TextField(blank=True)

    recorded_by_name = models.CharField(max_length=200, blank=True)
    source_hospital = models.ForeignKey("hospital_master.Hospital", null=True, blank=True, on_delete=models.SET_NULL, related_name="h_milestone_records")

    created_at       = models.DateTimeField(auto_now_add=True)
    updated_at       = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "milestone_records"
        indexes = [models.Index(fields=["patient", "domain"])]
        ordering  = ["assessed_date"]

# Not Reviewed
class SharedAllergy(models.Model):
    patient           = models.ForeignKey("patients.Patient", on_delete=models.CASCADE, related_name="p_shared_allergies")
    substance         = models.CharField(max_length=200)
    reaction          = models.TextField(blank=True)
    severity          = models.CharField(max_length=20, choices=[("mild", "Mild"), ("moderate", "Moderate"), ("severe", "Severe")], blank=True)
    is_active         = models.BooleanField(default=True)
    source_hospital  = models.ForeignKey("hospital_master.Hospital", null=True, blank=True, on_delete=models.SET_NULL, related_name="h_shared_allergies")
    recorded_at       = models.DateTimeField()
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "shared_allergy"

    def __str__(self):
        return f"{self.substance} for patient {self.patient_id}"

# Not Reviewed
class SharedPrescriptionItem(models.Model):
    document = models.ForeignKey("documents.MedicalDocument", on_delete=models.CASCADE, related_name="d_drug_items")
    drug_name = models.CharField(max_length=200)
    dose = models.CharField(max_length=50, blank=True)
    unit = models.CharField(max_length=20, blank=True)
    frequency = models.CharField(max_length=50, blank=True)
    route = models.CharField(max_length=50, blank=True)
    duration_days = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        db_table = "shared_prescription_item"

# Not Reviewed
class Vitals(models.Model):
    patient = models.ForeignKey("patients.Patient", on_delete=models.CASCADE, related_name="p_vitals")
    appointment_id = models.UUIDField(null=True, blank=True)
    source_hospital = models.ForeignKey("hospital_master.Hospital", null=True, blank=True, on_delete=models.SET_NULL, related_name="h_vitals")
    source = models.CharField(max_length=20, choices=[("clinic", "Clinic"), ("self_reported", "Self reported"), ("manual", "Entered by staff")], default="clinic")
    recorded_at = models.DateTimeField(default=timezone.now, db_index=True)
    recorded_by_user_id = models.UUIDField(null=True, blank=True)
    systolic_bp = models.PositiveSmallIntegerField(null=True, blank=True)
    diastolic_bp = models.PositiveSmallIntegerField(null=True, blank=True)
    pulse_rate = models.PositiveSmallIntegerField(null=True, blank=True)
    temperature = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    spo2 = models.PositiveSmallIntegerField(null=True, blank=True)
    respiratory_rate = models.PositiveSmallIntegerField(null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    height_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    blood_sugar_rbs = models.PositiveSmallIntegerField(null=True, blank=True)
    nurse_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "vitals"
        constraints = [models.UniqueConstraint(fields=["appointment_id"], condition=models.Q(appointment_id__isnull=False),
                                               name="uniq_vitals_per_appointment")]

    def __str__(self):
        return f"Vitals {self.id} for patient {self.patient_id} at {self.recorded_at:%Y-%m-%d %H:%M}"

# Not Reviewed
class ScheduleRule(models.Model):

    schedule         = models.ForeignKey("documents.Schedule", on_delete=models.CASCADE, related_name="s_rules")
    item             = models.CharField(max_length=200)
    dose_number      = models.PositiveSmallIntegerField(default=1)
    domain           = models.CharField(max_length=20, blank=True, choices=DOMAIN_CHOICES)
    scheduled_label  = models.CharField(max_length=50)
    min_age_days     = models.PositiveIntegerField()
    max_age_days     = models.PositiveIntegerField(null=True, blank=True)
    mandatory        = models.BooleanField(default=True)
    sort_order       = models.PositiveIntegerField(default=0)

    class Meta:
        db_table  = "immunization_schedule_rules"
        ordering  = ["sort_order"]

# Not Reviewed
class Schedule(models.Model):
    KIND_VACCINATION = "vaccination"
    KIND_MILESTONE   = "milestone"
    KIND_CHOICES = [(KIND_VACCINATION, "Vaccination"), (KIND_MILESTONE, "Milestone")]

    kind            = models.CharField(max_length=15, choices=KIND_CHOICES)
    name            = models.CharField(max_length=200)
    description     = models.TextField(blank=True)
    owner_hospital = models.ForeignKey("hospital_master.Hospital", null=True, blank=True, on_delete=models.CASCADE, related_name="h_schedules")
    is_template     = models.BooleanField(default=False)
    active          = models.BooleanField(default=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "immunization_schedules"

    def __str__(self):
        return f"{self.name} ({self.kind})"
