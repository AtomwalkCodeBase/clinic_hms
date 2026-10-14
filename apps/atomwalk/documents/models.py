"""Documents and what is read from them: batches, medical documents, extraction, classification; the clinical facts of a patient kept for every hospital to read; and the immunization and milestone schedules."""
from django.db import models
from decimal import Decimal
from django.utils import timezone

# ── the types (fixed: the rule engine never creates new ones) ─────────────
NOT_CLASSIFIED = "not_classified"      # no verdict yet, or no type fits well enough
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
# What a person may file a document under. "not_classified" is a state, not a choice.
CHOOSABLE_TYPES = [code for code in DOCUMENT_TYPES if code != NOT_CLASSIFIED]
# ── classification result states (PatientDocumentClassification.status) ──
RULE_CLASSIFIED = "rule_classified"      # the rules found a clear winner
REVIEW_REQUIRED = "review_required"      # weak or ambiguous: a person has to decide
HUMAN_CLASSIFIED = "human_classified"    # a person chose the type (never overwritten by the rules)
ISSUED = "issued"                        # a hospital supplied the type with the document it made
CLASSIFIER_RULES = "rule_engine"
CLASSIFIER_HUMAN = "human"
CLASSIFIER_HOSPITAL = "hospital"

SEVERITY_CHOICES = [("NORMAL", "Normal"), ("MILD", "Mild"), ("ABNORMAL", "Abnormal"), ("CRITICAL", "Critical")]
CATEGORY_CHOICES = [("CHRONIC", "Chronic"), ("ACUTE", "Acute")]
SOURCE_CHOICES = [("HOSPITAL", "Written by a hospital"), ("EXTRACTED", "Read from a document"), ("MANUAL", "Entered by staff")]


class Schedule(models.Model):
    """
    A named, ordered set of rules a hospital's pediatric roadmap is built against. ONE table for both kinds:
    kind="vaccination" (what to give and when) or kind="milestone" (what a child should be doing and when).

    owner_hospital_id is null for a system template (platform admin maintains those) and a Hospital.id for a hospital's own
    editable copy; is_template marks one meant to be cloned. Hospital.active_vaccination_schedule_id /
    active_milestone_schedule_id point at the live one. Plain IntegerField, not an FK, like the rest of the atomwalk.
    """
    KIND_VACCINATION = "vaccination"
    KIND_MILESTONE   = "milestone"
    KIND_CHOICES = [(KIND_VACCINATION, "Vaccination"), (KIND_MILESTONE, "Milestone")]

    kind            = models.CharField(max_length=15, choices=KIND_CHOICES)
    name            = models.CharField(max_length=200)
    description     = models.TextField(blank=True)
    owner_hospital = models.ForeignKey("hospital_master.Hospital", null=True, blank=True, on_delete=models.CASCADE, related_name="schedules")  # empty = a platform template
    is_template     = models.BooleanField(default=False)
    active          = models.BooleanField(default=True)  # soft-disable instead of delete
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "immunization_schedules"

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
        db_table  = "immunization_schedule_rules"
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


class MilestoneSchedule(_KindSaved, Schedule):
    KIND = Schedule.KIND_MILESTONE
    objects = _OfKind(KIND)

    class Meta:
        proxy = True


class VaccinationScheduleRule(ScheduleRule):
    objects = _OfKind(Schedule.KIND_VACCINATION, "schedule__")

    class Meta:
        proxy = True


class MilestoneScheduleRule(ScheduleRule):
    objects = _OfKind(Schedule.KIND_MILESTONE, "schedule__")

    class Meta:
        proxy = True


def records_storage():
    """The private S3 bucket (core.storage) as a Django storage — a callable so migrations stay importable."""
    from core.storage import PrivateS3Storage
    return PrivateS3Storage()


def get_file_path(instance, filename):
    """The S3 path for a new file: documents/<awpid>/<batch_id>/<filename> ("NA" when there is no batch)."""
    return f"documents/{instance.patient.awpid}/{instance.batch_id or 'NA'}/{filename}"


class DocumentBatch(models.Model):
    class Status(models.TextChoices):
        PROCESSING = "processing"
        COMPLETED = "completed"
        COMPLETED_WITH_ERRORS = "completed_with_errors"

    patient = models.ForeignKey("patients.Patient", on_delete=models.CASCADE, related_name="p_batches")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "document_batch"

    def __str__(self):
        return f"batch {self.id} · {self.patient_id}"

    # The counts and the status are worked out from the batch's documents each time, so they can never be wrong.
    def _counts(self):
        return dict(self.documents.values_list("status").annotate(n=models.Count("id")))

    @property
    def total_files(self):
        return sum(self._counts().values())

    @property
    def processed_files(self):
        """A document waiting for a person to classify it has finished its processing, so it counts as processed."""
        counts = self._counts()
        return counts.get(MedicalDocument.Status.COMPLETED, 0) + counts.get(MedicalDocument.Status.REVIEW_REQUIRED, 0)

    @property
    def failed_files(self):
        return self._counts().get(MedicalDocument.Status.FAILED, 0)

    @property
    def status(self):
        counts = self._counts()
        processed = counts.get(MedicalDocument.Status.COMPLETED, 0) + counts.get(MedicalDocument.Status.REVIEW_REQUIRED, 0)
        failed = counts.get(MedicalDocument.Status.FAILED, 0)
        if processed + failed < sum(counts.values()):
            return self.Status.PROCESSING
        return self.Status.COMPLETED_WITH_ERRORS if failed else self.Status.COMPLETED


class MedicalDocument(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued"
        EXTRACTING = "extracting"
        CLASSIFYING = "classifying"
        COMPLETED = "completed"
        REVIEW_REQUIRED = "review_required"   # read, but the rules could not tell what it is: a person decides
        FAILED = "failed"

    IN_PROGRESS = (Status.QUEUED, Status.EXTRACTING, Status.CLASSIFYING)

    patient = models.ForeignKey("patients.Patient", on_delete=models.CASCADE, related_name="p_documents")
    batch = models.ForeignKey(DocumentBatch, null=True, blank=True, on_delete=models.SET_NULL, related_name="documents")
    file = models.FileField(upload_to=get_file_path, storage=records_storage, max_length=500)  # the S3 path is documents/<awpid>/…
    file_name = models.CharField(max_length=100, blank=True)
    mime_type = models.CharField(max_length=100, blank=True)         # the real type, set once the content is checked
    size = models.PositiveBigIntegerField(null=True, blank=True)     # bytes
    document_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.QUEUED, db_index=True)
    error_message = models.TextField(blank=True)                     # why it failed
    document_type = models.CharField(max_length=30, choices=DOCUMENT_TYPE_CHOICES, default=NOT_CLASSIFIED)
    # Where it came from: an upload, or something a hospital issued (which hospital, what it was made from, what is printed on it).
    class Source(models.TextChoices):
        UPLOAD = "upload"                                     # a file a patient or staff member uploaded
        ENCOUNTER = "encounter"                               # a hospital's typeset prescription; source_id is the encounter id
        ENCOUNTER_HANDWRITTEN_RX = "encounter_handwritten_rx"  # the consult pad's handwritten prescription; the encounter id
        LAB_REQUEST = "lab_request"                           # a file attached to a lab request; "<hospital db>:<request id>"
        LAB_REPORT = "lab_report"                             # a hospital's lab report; the report id

    source_type = models.CharField(max_length=30, choices=Source.choices, default=Source.UPLOAD, db_index=True)
    source_id = models.CharField(max_length=80, blank=True, db_index=True)
    source_hospital = models.ForeignKey("hospital_master.Hospital", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    document_ref = models.CharField(max_length=40, blank=True)
    uploaded_by = models.CharField(max_length=10, default="patient")   # patient | staff
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "medical_documents"

    def __str__(self):
        return f"{self.patient.awpid} — {self.file_name}"

    # ── read-only names the portal / sharing / admin code and the API use ──

    @property
    def processing_status(self):
        return self.status

    @property
    def source_ref(self):
        """The source as one text, for API output: "encounter:<id>", "lab_request:<db>:<id>" ... (empty for an upload)."""
        return f"{self.source_type}:{self.source_id}" if self.source_id else ""


class DocumentExtraction(models.Model):
    """What was read out of a document, one row per document: its text (PDF text layer or OCR) and what was found in the
    text (the dated conditions, symptoms and medications of the timeline)."""
    class Status(models.TextChoices):
        PENDING = "pending"
        DONE = "done"
        FAILED = "failed"
        SKIPPED = "skipped"

    document = models.OneToOneField(MedicalDocument, on_delete=models.CASCADE, related_name="extraction")
    extracted_text = models.TextField(blank=True)
    engine = models.CharField(max_length=30, blank=True)             # what read it: "pdf_text" or "ocr"
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)   # of the findings, not the text
    extractor_version = models.CharField(max_length=30, blank=True)
    normalised = models.JSONField(default=dict, blank=True)         # the findings, as the timeline reads them (timeline_insights/extract.py)
    warnings = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "document_extraction"

    def __str__(self):
        return f"extraction of document {self.document_id}"


class PatientDocumentClassification(models.Model):
    """One document's classification result: the rule engine's verdict with its scores, a person's correction if
    there is one, and the type that finally counts (also copied to MedicalDocument.document_type)."""
    document = models.OneToOneField(MedicalDocument, on_delete=models.CASCADE, related_name="classification")
    ai_document_type = models.CharField(max_length=50, null=True, blank=True)    # the best type the classifier found
    classifier = models.CharField(max_length=30, default=CLASSIFIER_RULES)
    rule_score = models.FloatField(null=True, blank=True)
    second_best_score = models.FloatField(null=True, blank=True)
    score_margin = models.FloatField(null=True, blank=True)          # rule_score minus second_best_score
    rule_matches = models.JSONField(null=True, blank=True)           # the keywords that matched
    human_document_type = models.CharField(max_length=50, null=True, blank=True)
    status = models.CharField(max_length=30, default=RULE_CLASSIFIED)

    class Meta:
        db_table = "patient_document_classification"

    def __str__(self):
        return f"document {self.document_id} → {self.document.document_type}"


def patient_link(related_name):
    """The link every clinical table has to the patient."""
    return models.ForeignKey("patients.Patient", null=True, blank=True, on_delete=models.CASCADE, related_name=related_name)


def hospital_link():
    """The hospital a fact came from: kept when the hospital is removed (the fact stays, its source is then unknown)."""
    return models.ForeignKey("hospital_master.Hospital", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")


def document_link(related_name="+"):
    """The uploaded file a fact was read from, when it was."""
    return models.ForeignKey("documents.MedicalDocument", null=True, blank=True, on_delete=models.CASCADE, related_name=related_name)


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
    source_hospital = hospital_link()                      # stored internally, NEVER returned to other hospitals
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
        db_table = "recurrence_flag"
        constraints = [models.UniqueConstraint(fields=["patient", "condition_group"], name="uniq_recurrence_per_patient_group")]


class SharedPrescriptionItem(models.Model):
    """A drug on a prescription. The prescription itself is the patient's document (source "encounter")."""
    document = models.ForeignKey("documents.MedicalDocument", null=True, blank=True, on_delete=models.CASCADE, related_name="drug_items")
    drug_name = models.CharField(max_length=200)
    dose = models.CharField(max_length=50, blank=True)
    unit = models.CharField(max_length=20, blank=True)
    frequency = models.CharField(max_length=50, blank=True)
    route = models.CharField(max_length=50, blank=True)
    duration_days = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        db_table = "shared_prescription_item"


class LabResult(models.Model):
    """
    A lab report and the values read from it. A hospital writes one row per report when it delivers it (test name,
    summary, the file); a document read by the system gives one row per value (analyte, value, unit).
    """
    patient = patient_link("lab_results")
    document = document_link("lab_results")
    source_hospital = hospital_link()
    test_name = models.CharField(max_length=200, blank=True)
    analyte = models.CharField(max_length=40, blank=True, db_index=True)
    value = models.FloatField(null=True, blank=True)
    unit_raw = models.CharField(max_length=30, blank=True)
    result_summary = models.TextField(blank=True)              # free text or structured JSON; the report's file is the document
    collected_on = models.DateField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    age_band = models.CharField(max_length=12, blank=True)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default="NORMAL")
    direction = models.CharField(max_length=4, blank=True)     # LOW | HIGH
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "lab_result"


class SharedAllergy(models.Model):
    """Written when an allergy is recorded or updated."""
    patient           = patient_link("allergies")
    substance         = models.CharField(max_length=200)
    reaction          = models.TextField(blank=True)
    severity          = models.CharField(max_length=20, blank=True)  # mild/moderate/severe
    is_active         = models.BooleanField(default=True)
    source_hospital  = hospital_link()
    recorded_at       = models.DateTimeField()
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "shared_allergy"


class Vitals(models.Model):
    """
    One set of vital signs: blood pressure, pulse, temperature, oxygen, breathing, blood sugar and the nurse's note. A
    child's height, weight and head size go to growth_measurement instead; an adult's height and weight stay here. Written
    when a nurse records them at a visit (appointment_id is that hospital's appointment, a plain id).
    """
    patient = patient_link("vitals")
    appointment_id = models.UUIDField(null=True, blank=True, db_index=True)
    source_hospital = hospital_link()
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
    blood_sugar_rbs = models.IntegerField(null=True, blank=True)        # mg/dL random blood sugar
    nurse_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "vitals"
        constraints = [models.UniqueConstraint(fields=["appointment_id"], condition=models.Q(appointment_id__isnull=False),
                                               name="uniq_vitals_per_appointment")]

    @property
    def bmi(self):
        """Worked out from the height and weight, not stored."""
        if self.weight_kg and self.height_cm and self.height_cm > 0:
            return Decimal(f"{float(self.weight_kg) / ((float(self.height_cm) / 100) ** 2):.1f}")
        return None


class GrowthMeasurement(models.Model):
    """A child's height, weight and head size on a day, with where it came from. One row per visit or per document."""
    patient = patient_link("growth")
    document = document_link("growth_measurements")
    appointment_id = models.UUIDField(null=True, blank=True, db_index=True)
    source_hospital = hospital_link()
    source = models.CharField(max_length=10, default="clinic")          # clinic / home / extracted / manual
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
    flags = models.JSONField(default=dict, blank=True)                  # {"weight_kg": "LOW", ...}
    reference_source = models.CharField(max_length=5, blank=True)       # who | iap
    is_rejected = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "growth_measurement"
        constraints = [models.UniqueConstraint(fields=["appointment_id"], condition=models.Q(appointment_id__isnull=False),
                                               name="uniq_growth_per_appointment")]

    @property
    def bmi(self):
        """Worked out from the height and weight, not stored."""
        if self.weight_kg and self.height_cm and self.height_cm > 0:
            return Decimal(f"{float(self.weight_kg) / ((float(self.height_cm) / 100) ** 2):.1f}")
        return None


class BirthHistory(models.Model):
    """
    A child's birth history, one row per child, kept for every hospital (and the emergency summary) to read. The front desk
    can capture it at registration and the pediatrician can add or correct it later; an edit overwrites it, and
    source_hospital is the hospital that last wrote it. recorded_by / updated_by are staff ids (plain numbers).
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

    patient = models.OneToOneField("patients.Patient", null=True, blank=True, on_delete=models.CASCADE, related_name="birth_history")
    document = document_link("birth_histories")
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="MANUAL")
    source_hospital = hospital_link()
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

    source_hospital      = hospital_link()  # the hospital that logged or verified it; empty until reviewed

    created_at           = models.DateTimeField(auto_now_add=True)
    updated_at           = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "immunization_record"
        indexes = [models.Index(fields=["patient", "verification_status"])]
        ordering  = ["administered_date"]

    @property
    def recorded_by(self):
        """"patient" for a parent's own report, otherwise "staff"."""
        return "patient" if self.source == self.SOURCE_SELF_REPORTED else "staff"

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
    source_hospital = hospital_link()

    created_at       = models.DateTimeField(auto_now_add=True)
    updated_at       = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "milestone_records"
        indexes = [models.Index(fields=["patient", "domain"])]
        ordering  = ["assessed_date"]

    def __str__(self):
        return f"{self.patient_id} — {self.milestone} ({self.status})"
