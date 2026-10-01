"""
apps/records — patient documents (registry database).

    DocumentBatch            one upload; the patient follows its progress by batch id
      └── MedicalDocument    one file, with where it is in the pipeline and its one classification
            └── classification → DocumentClassification   the types Platform Admin configured (+ their keywords)

A document has exactly one classification: the rules' verdict (classification_source="system"), replaced by a
person's if they overwrite it (classification_source="human"). Nothing else is kept.
"""
import os

from django.db import models
from django.db.models import F, Value
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Coalesce


class DocumentClassification(models.Model):
    """A document type and the keywords that recognise it — configured in Platform Admin."""
    code = models.SlugField(max_length=30, unique=True)              # lab_report, prescription, x_ray_report …
    name = models.CharField(max_length=60)
    # Pipe-separated, e.g. "laboratory report^3|glucose|-discharge summary" (^N = weight, - = rules the type out).
    # Blank = the rules never assign this type (a hospital-issued type, or one still being set up).
    keywords = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    # The hospital's own internal notes: never shown in the patient portal.
    is_staff_only = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "document_classification"
        ordering = ["code"]

    def __str__(self):
        return self.code

    @property
    def keyword_list(self):
        """The words that count towards this type (weights and minus-words are handled by records.scoring)."""
        from .scoring import parse_keywords
        return [w for w, _ in parse_keywords(self.keywords)[0]]

    @classmethod
    def for_code(cls, code):
        """The row for `code`, created on first use — a hospital-issued document brings its own type."""
        obj, _ = cls.objects.using("default").get_or_create(
            code=code, defaults={"name": code.replace("_", " ").capitalize(), "is_staff_only": code == "consult_note"})
        return obj

    @classmethod
    def configured(cls):
        """The types the rules and the patient can use: those with keywords, minus staff-only ones."""
        return [c for c in cls.objects.using("default").filter(is_staff_only=False) if c.keyword_list]


class DocumentBatch(models.Model):
    class Status(models.TextChoices):
        PROCESSING = "processing"
        COMPLETED = "completed"
        COMPLETED_WITH_ERRORS = "completed_with_errors"

    awpid = models.ForeignKey("registry.PatientIdentity", to_field="awpid", db_column="awpid",
                              on_delete=models.PROTECT, related_name="+")
    total_files = models.PositiveIntegerField(default=0)
    processed_files = models.PositiveIntegerField(default=0)
    failed_files = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PROCESSING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "document_batch"

    def __str__(self):
        return f"batch {self.id} · {self.awpid_id} · {self.processed_files}+{self.failed_files}/{self.total_files}"

    def refresh(self):
        """Recount from the documents (never drifts) and set the batch status. Rejected duplicates count as done."""
        counts = dict(self.documents.values_list("status").annotate(n=models.Count("id")))
        S = MedicalDocument.Status
        self.processed_files = counts.get(S.COMPLETED, 0) + counts.get(S.REJECTED, 0)
        self.failed_files = counts.get(S.FAILED, 0)
        done = self.processed_files + self.failed_files >= self.total_files
        self.status = (self.Status.PROCESSING if not done else
                       self.Status.COMPLETED_WITH_ERRORS if self.failed_files else self.Status.COMPLETED)
        self.save(update_fields=["processed_files", "failed_files", "status", "updated_at"])


class MedicalDocumentManager(models.Manager):
    """Every query brings the classification along (no N+1 when a list reads the type) and leaves the big
    classification_details JSON (the extracted text) behind until something asks for it."""

    def get_queryset(self):
        return (super().get_queryset().select_related("classification").defer("classification_details")
                .annotate(_best_guess=KeyTextTransform("best_guess", "classification_details"),
                          _duplicate_of=KeyTextTransform("duplicate_of", "classification_details")))


class MedicalDocument(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued"
        EXTRACTING = "extracting"
        CLASSIFYING = "classifying"
        COMPLETED = "completed"
        FAILED = "failed"
        REJECTED = "rejected"        # a duplicate of another document of the same patient

    class Source(models.TextChoices):
        SYSTEM = "system"            # the keyword rules
        HUMAN = "human"              # a person (a correction, or the hospital that issued the document)

    IN_PROGRESS = (Status.QUEUED, Status.EXTRACTING, Status.CLASSIFYING)

    awpid = models.ForeignKey("registry.PatientIdentity", to_field="awpid", db_column="awpid",
                              on_delete=models.PROTECT, related_name="+")
    batch = models.ForeignKey(DocumentBatch, null=True, blank=True, on_delete=models.SET_NULL, related_name="documents")
    title = models.CharField(max_length=200, blank=True)
    original_file_name = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=100, blank=True)         # the real type, set once the content is checked
    file_path = models.CharField(max_length=500)                     # relative path in the bucket
    size = models.PositiveBigIntegerField(null=True, blank=True)     # bytes
    content_hash = models.CharField(max_length=64, blank=True)       # SHA-256, set by the extraction job
    uploaded_by = models.CharField(max_length=10, default="patient")   # patient | staff

    # Hospital-issued documents: which hospital made it, what from, and what is printed on it.
    source_tenant_id = models.IntegerField(null=True, blank=True)
    source_ref = models.CharField(max_length=120, blank=True, db_index=True)   # "encounter:<id>", "labreq:<db>:<id>" …
    public_document_id = models.CharField(max_length=40, blank=True, db_index=True)   # Rx / report number (the QR code)
    hospital_label = models.CharField(max_length=120, blank=True)
    doctor_label = models.CharField(max_length=120, blank=True)
    document_date = models.DateField(null=True, blank=True)

    # Where it is in the pipeline, and its one classification (null until classified, or if nothing fits).
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.COMPLETED, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    claimed_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)
    classification = models.ForeignKey(DocumentClassification, null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="documents")
    classification_source = models.CharField(max_length=6, choices=Source.choices, null=True, blank=True)
    score = models.FloatField(null=True, blank=True)                 # confidence 0–100
    # {"extracted_text": …, "method": "rule", "best_guess": …, "matched": […], "note": …, "duplicate_of": <id>}
    classification_details = models.JSONField(default=dict, blank=True)

    hidden_at = models.DateTimeField(null=True, blank=True)          # the patient removed a hospital-issued report
    deleted_at = models.DateTimeField(null=True, blank=True)         # the patient deleted a report they uploaded
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = MedicalDocumentManager()

    class Meta:
        db_table = "medical_document"
        indexes = [models.Index(fields=["status", "created_at"], name="meddoc_status_created_idx"),
                   models.Index(fields=["awpid", "created_at"], name="meddoc_awpid_created_idx"),
                   models.Index(fields=["awpid", "content_hash"], name="meddoc_awpid_hash_idx")]

    def __str__(self):
        return f"{self.awpid_id} — {self.title}"

    # ── read-only names the portal / sharing / admin code and the API use ──
    @property
    def file_name(self):
        return self.original_file_name

    @property
    def doc_type(self):
        return self.classification.code if self.classification_id else ""        # "" = not classified

    @property
    def is_staff_only(self):
        return bool(self.classification_id and self.classification.is_staff_only)

    @property
    def processing_status(self):
        return self.status

    @property
    def method(self):
        return {"human": "staff", "system": "rule"}.get(self.classification_source, "")

    @property
    def best_guess(self):
        """For a document no configured type fit: the type the rules came closest to (else "")."""
        return getattr(self, "_best_guess", None) or ""

    @property
    def duplicate_of(self):
        """For a rejected duplicate: the id of the document it is the same as."""
        value = getattr(self, "_duplicate_of", None)
        return int(value) if value else None

    @property
    def extracted_text(self):
        return (self.classification_details or {}).get("extracted_text", "")

    @staticmethod
    def title_from(file_name):
        return os.path.splitext(file_name or "")[0][:200]


# For .values(): the document's type code, "" while it has none (not classified yet, or unable to classify).
DOC_TYPE_EXPR = Coalesce(F("classification__code"), Value(""))


class SweepConfig(models.Model):
    """Singleton (pk=1) — the one Platform Admin-editable source for the periodic-sweep and scoring settings
    (apps/records/views.py, tasks.py). No restart for any of them: saving this row also creates/updates the
    django_celery_beat PeriodicTask that actually runs recover_stuck_documents, so its own interval is
    DB-backed too (CELERY_BEAT_SCHEDULER = DatabaseScheduler)."""
    TASK_NAME = "records: recover_stuck_documents"

    instant_max_files = models.PositiveIntegerField(default=50)
    sweep_dispatch_limit = models.PositiveIntegerField(default=10)
    sweep_interval_seconds = models.PositiveIntegerField(default=30)
    # How a verdict is judged (records.scoring): the confidence a type needs to be filed, and how many weighted
    # keyword hits count as "plenty of evidence" (the scale of the evidence curve).
    min_confidence = models.PositiveSmallIntegerField(default=50)
    evidence_scale = models.PositiveSmallIntegerField(default=10)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "records_sweep_config"

    @classmethod
    def current(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        from django_celery_beat.models import IntervalSchedule, PeriodicTask

        schedule, _ = IntervalSchedule.objects.get_or_create(
            every=self.sweep_interval_seconds, period=IntervalSchedule.SECONDS)
        PeriodicTask.objects.update_or_create(
            name=self.TASK_NAME,
            defaults={"task": "apps.records.tasks.recover_stuck_documents", "interval": schedule, "enabled": True},
        )
