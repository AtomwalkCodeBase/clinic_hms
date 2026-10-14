"""Patient documents: one upload (batch), each file in it (medical_documents), the text read from it, and how it was classified."""

from django.db import models

from apps.records import classification as rules


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

    patient = models.ForeignKey("atomwalk.Patient", on_delete=models.CASCADE, related_name="p_batches")
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

    patient = models.ForeignKey("atomwalk.Patient", on_delete=models.CASCADE, related_name="p_documents")
    batch = models.ForeignKey(DocumentBatch, null=True, blank=True, on_delete=models.SET_NULL, related_name="documents")
    file = models.FileField(upload_to=get_file_path, storage=records_storage, max_length=500)  # the S3 path is documents/<awpid>/…
    file_name = models.CharField(max_length=100, blank=True)
    mime_type = models.CharField(max_length=100, blank=True)         # the real type, set once the content is checked
    size = models.PositiveBigIntegerField(null=True, blank=True)     # bytes
    document_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.QUEUED, db_index=True)
    error_message = models.TextField(blank=True)                     # why it failed
    document_type = models.CharField(max_length=30, choices=rules.DOCUMENT_TYPE_CHOICES, default=rules.NOT_CLASSIFIED)
    # Where it came from: an upload, or something a hospital issued (which hospital, what it was made from, what is printed on it).
    class Source(models.TextChoices):
        UPLOAD = "upload"                                     # a file a patient or staff member uploaded
        ENCOUNTER = "encounter"                               # a hospital's typeset prescription; source_id is the encounter id
        ENCOUNTER_HANDWRITTEN_RX = "encounter_handwritten_rx"  # the consult pad's handwritten prescription; the encounter id
        LAB_REQUEST = "lab_request"                           # a file attached to a lab request; "<hospital db>:<request id>"
        LAB_REPORT = "lab_report"                             # a hospital's lab report; the report id

    source_type = models.CharField(max_length=30, choices=Source.choices, default=Source.UPLOAD, db_index=True)
    source_id = models.CharField(max_length=80, blank=True, db_index=True)
    source_hospital = models.ForeignKey("hospitals.Hospital", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
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
    classifier = models.CharField(max_length=30, default=rules.CLASSIFIER_RULES)
    rule_score = models.FloatField(null=True, blank=True)
    second_best_score = models.FloatField(null=True, blank=True)
    score_margin = models.FloatField(null=True, blank=True)          # rule_score minus second_best_score
    rule_matches = models.JSONField(null=True, blank=True)           # the keywords that matched
    human_document_type = models.CharField(max_length=50, null=True, blank=True)
    status = models.CharField(max_length=30, default=rules.RULE_CLASSIFIED)

    class Meta:
        db_table = "patient_document_classification"

    def __str__(self):
        return f"document {self.document_id} → {self.document.document_type}"
