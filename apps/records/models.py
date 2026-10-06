"""
apps/records — patient documents (registry database).

    DocumentBatch                     one upload; the patient follows its progress by batch id
      └── MedicalDocument             one file (a Django FileField on the private S3 bucket) and where it is in the pipeline
            ├── text → DocumentText                              the text read out of it
            └── classification → PatientDocumentClassification   the rules' verdict, a person's correction, the final type

The document types, their keywords and the scoring are not tables: they are fixed in code (classification.py).
MedicalDocument.document_type is the document's current type; the classification row holds how it was decided.
"""
from django.db import models

from . import classification as rules


def records_storage():
    """The private S3 bucket (core.storage) as a Django storage — a callable so migrations stay importable."""
    from core.storage import PrivateS3Storage
    return PrivateS3Storage()


class DocumentBatch(models.Model):
    class Status(models.TextChoices):
        PROCESSING = "processing"
        COMPLETED = "completed"
        COMPLETED_WITH_ERRORS = "completed_with_errors"

    patient = models.ForeignKey("registry.PatientIdentity", on_delete=models.CASCADE, related_name="p_batches")
    total_files = models.PositiveIntegerField(default=0)
    processed_files = models.PositiveIntegerField(default=0)
    failed_files = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PROCESSING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "document_batch"

    def __str__(self):
        return f"batch {self.id} · {self.patient_id} · {self.processed_files}+{self.failed_files}/{self.total_files}"

    def refresh(self):
        """Recount from the documents (never drifts) and set the batch status. A document waiting for a person to
        classify it has finished its processing, so it counts as processed."""
        counts = dict(self.documents.values_list("status").annotate(n=models.Count("id")))
        S = MedicalDocument.Status
        self.processed_files = counts.get(S.COMPLETED, 0) + counts.get(S.REVIEW_REQUIRED, 0)
        self.failed_files = counts.get(S.FAILED, 0)
        done = self.processed_files + self.failed_files >= self.total_files
        self.status = (self.Status.PROCESSING if not done else
                       self.Status.COMPLETED_WITH_ERRORS if self.failed_files else self.Status.COMPLETED)
        self.save(update_fields=["processed_files", "failed_files", "status", "updated_at"])


def get_file_path(instance, filename):
    """The S3 path for a new file: documents/<awpid>/<batch_id>/<filename> ("NA" when there is no batch)."""
    return f"documents/{instance.patient.awpid}/{instance.batch_id or 'NA'}/{filename}"


class MedicalDocument(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued"
        EXTRACTING = "extracting"
        CLASSIFYING = "classifying"
        COMPLETED = "completed"
        REVIEW_REQUIRED = "review_required"   # read, but the rules could not tell what it is: a person decides
        FAILED = "failed"

    IN_PROGRESS = (Status.QUEUED, Status.EXTRACTING, Status.CLASSIFYING)

    patient = models.ForeignKey("registry.PatientIdentity", on_delete=models.CASCADE, related_name="p_documents")
    batch = models.ForeignKey(DocumentBatch, null=True, blank=True, on_delete=models.SET_NULL, related_name="documents")
    file = models.FileField(upload_to=get_file_path, storage=records_storage, max_length=500)  # the S3 path is documents/<awpid>/…
    file_name = models.CharField(max_length=100, blank=True)
    mime_type = models.CharField(max_length=100, blank=True)         # the real type, set once the content is checked
    size = models.PositiveBigIntegerField(null=True, blank=True)     # bytes
    document_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.QUEUED, db_index=True)
    error_message = models.TextField(blank=True)                     # why it failed
    document_type = models.CharField(max_length=30, choices=rules.DOCUMENT_TYPE_CHOICES, default=rules.NOT_CLASSIFIED)
    # Hospital-issued documents: which hospital made it, what from, and what is printed on it.
    source_tenant_id = models.CharField(max_length=30, null=True, blank=True)
    source_ref = models.CharField(max_length=120, blank=True)        # "encounter:<id>", "labreq:<db>:<id>"
    document_ref = models.CharField(max_length=40, blank=True)
    uploaded_by = models.CharField(max_length=10, default="patient")   # patient | staff
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "medical_document"

    def __str__(self):
        return f"{self.patient.awpid} — {self.file_name}"

    # ── read-only names the portal / sharing / admin code and the API use ──

    @property
    def processing_status(self):
        return self.status


class DocumentText(models.Model):
    """The text read out of a document (PDF text layer or OCR)."""
    document = models.OneToOneField(MedicalDocument, on_delete=models.CASCADE, related_name="text")
    extracted_text = models.TextField(blank=True)
    engine = models.CharField(max_length=30, blank=True)             # what read it: "pdf_text" or "ocr"
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "document_text"

    def __str__(self):
        return f"text of document {self.document_id}"


class PatientDocumentClassification(models.Model):
    """One document's classification result: the rule engine's verdict with its scores, a person's correction if
    there is one, and the type that finally counts (also copied to MedicalDocument.document_type)."""
    document = models.OneToOneField(MedicalDocument, on_delete=models.CASCADE, related_name="classification")
    ai_document_type = models.CharField(max_length=50, null=True, blank=True)    # the best type the classifier found
    classifier = models.CharField(max_length=30, default=rules.CLASSIFIER_RULES)
    rule_score = models.FloatField(null=True, blank=True)
    second_best_score = models.FloatField(null=True, blank=True)
    score_margin = models.FloatField(null=True, blank=True)          # rule_score minus second_best_score
    rule_matches = models.JSONField(null=True, blank=True)           # the keywords that matched
    human_document_type = models.CharField(max_length=50, null=True, blank=True)
    final_document_type = models.CharField(max_length=50, null=True, blank=True)
    status = models.CharField(max_length=30, default=rules.RULE_CLASSIFIED)

    class Meta:
        db_table = "patient_document_classification"

    def __str__(self):
        return f"document {self.document_id} → {self.final_document_type or 'unclassified'}"
