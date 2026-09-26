"""
apps/records — patient documents.

    Patient (awpid)
      └── UploadBatch            one upload request
            └── SharedDocument   one file (also written by OPD sign / lab delivery, without a batch)

    ClassificationRule           the keyword lists, edited in Platform Admin → Classification rules
"""
from django.db import models


class UploadBatch(models.Model):
    awpid = models.CharField(max_length=30, db_index=True)
    total_files = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "upload_batch"

    def __str__(self):
        return f"batch {self.id} · {self.awpid} · {self.total_files} file(s)"


class SharedDocument(models.Model):
    DOC_TYPE_CHOICES = [
        ("lab_report", "Lab Report"),
        ("prescription", "Prescription"),
        ("scan", "Scan / Imaging"),
        ("discharge_summary", "Discharge Summary"),
        ("consult_note", "Consultation Note"),
        ("other", "Other"),
    ]
    # The hospital's own internal notes: shown to clinicians, never in the patient portal.
    STAFF_ONLY_DOC_TYPES = ("consult_note",)
    # queued → ocr → classifying → completed | failed
    IN_PROGRESS = ("queued", "ocr", "classifying")

    awpid = models.CharField(max_length=30, db_index=True)
    batch = models.ForeignKey(UploadBatch, null=True, blank=True, on_delete=models.CASCADE, related_name="documents")
    title = models.CharField(max_length=200)
    doc_type = models.CharField(max_length=30, default="other")          # any active ClassificationRule.doc_type
    file_name = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=100, blank=True)
    s3_key = models.CharField(max_length=500)
    uploaded_by = models.CharField(max_length=10, default="patient")      # patient | staff
    # Hospital-created documents: which hospital, and what made them
    # ("encounter:<id>", "labreport:<id>", "labreq:<db>:<id>").
    source_tenant_id = models.IntegerField(null=True, blank=True)
    source_ref = models.CharField(max_length=120, blank=True, db_index=True)
    public_document_id = models.CharField(max_length=40, blank=True, db_index=True)   # Rx / report number (QR)
    hospital_label = models.CharField(max_length=120, blank=True)
    doctor_label = models.CharField(max_length=120, blank=True)
    document_date = models.DateField(null=True, blank=True)

    # Upload pipeline (tasks.process_document_task)
    processing_status = models.CharField(max_length=12, default="completed", db_index=True)
    extracted_text = models.TextField(blank=True)
    score = models.FloatField(null=True, blank=True)                      # 0–100
    method = models.CharField(max_length=10, blank=True)                  # rule | llm | staff
    error = models.TextField(blank=True)

    hidden_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "shared_document"
        indexes = [models.Index(fields=["awpid", "doc_type"], name="shared_doc_awpid_type_idx")]

    def __str__(self):
        return f"{self.awpid} — {self.title}"


class ClassificationRule(models.Model):
    doc_type = models.CharField(max_length=30, unique=True)
    keywords = models.TextField(help_text="Pipe-separated, e.g. laboratory|hemoglobin|glucose|reference range")
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "classification_rule"
        ordering = ["doc_type"]

    def __str__(self):
        return self.doc_type

    @property
    def keyword_list(self):
        return [k.strip().lower() for k in self.keywords.split("|") if k.strip()]


class SweepConfig(models.Model):
    """Singleton (pk=1) — the one Platform Admin-editable source for all three periodic-sweep
    settings (apps/records/views.py, tasks.py). No restart for any of them: saving this row also
    creates/updates the django_celery_beat PeriodicTask that actually runs recover_stuck_documents,
    so its own interval is DB-backed too (CELERY_BEAT_SCHEDULER = DatabaseScheduler)."""
    TASK_NAME = "records: recover_stuck_documents"

    instant_max_files = models.PositiveIntegerField(default=5)
    sweep_dispatch_limit = models.PositiveIntegerField(default=10)
    sweep_interval_seconds = models.PositiveIntegerField(default=30)
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
