"""
apps/ai_pipeline/models.py
--------------------------
Tables: VoiceRecording, AIJob, SuggestionAudit

feat_ai_voice gate enforced at API view level.
All AI suggestions are non-binding — every suggestion must be
reviewed and explicitly accepted by the doctor (SuggestionAudit tracks this).
"""

from django.db import models
from apps.org.models import StaffUser
from apps.patients.models import Patient
from apps.clinical.models import Encounter


class VoiceRecording(models.Model):
    """
    Audio recording of a doctor-patient consultation.
    Uploaded to file storage; AI pipeline processes it asynchronously.
    """
    STATUS_CHOICES = [
        ("uploaded",    "Uploaded"),
        ("queued",      "Queued for Processing"),
        ("processing",  "Processing"),
        ("done",        "Done"),
        ("failed",      "Failed"),
    ]

    encounter       = models.ForeignKey(Encounter, on_delete=models.CASCADE,
                                        related_name="voice_recordings")
    uploaded_by     = models.ForeignKey(StaffUser, on_delete=models.SET_NULL, null=True)
    file_url        = models.TextField()      # S3 key or local path
    duration_seconds= models.PositiveIntegerField(null=True, blank=True)
    language        = models.CharField(max_length=10, default="en")
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default="uploaded", db_index=True)
    uploaded_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "ai_pipeline"
        db_table  = "voice_recording"

    def __str__(self):
        return f"Recording #{self.id} — Encounter {self.encounter_id} ({self.status})"


class AIJob(models.Model):
    """
    Async AI processing job. One job per voice recording.
    Output is a JSON blob with extracted SOAP notes, diagnoses, prescriptions.
    """
    JOB_TYPE_CHOICES = [
        ("transcription", "Transcription"),
        ("soap_notes",    "SOAP Note Extraction"),
        ("diagnosis_suggest", "Diagnosis Suggestion"),
        ("rx_suggest",    "Prescription Suggestion"),
    ]

    STATUS_CHOICES = [
        ("pending",    "Pending"),
        ("running",    "Running"),
        ("completed",  "Completed"),
        ("failed",     "Failed"),
    ]

    recording       = models.ForeignKey(VoiceRecording, on_delete=models.CASCADE,
                                        related_name="jobs")
    encounter       = models.ForeignKey(Encounter, on_delete=models.CASCADE,
                                        related_name="ai_jobs")
    job_type        = models.CharField(max_length=30, choices=JOB_TYPE_CHOICES)
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending", db_index=True)
    output          = models.JSONField(null=True, blank=True)   # structured AI output
    error_message   = models.TextField(blank=True)
    started_at      = models.DateTimeField(null=True, blank=True)
    completed_at    = models.DateTimeField(null=True, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "ai_pipeline"
        db_table  = "ai_job"

    def __str__(self):
        return f"AIJob #{self.id} [{self.job_type}] ({self.status})"


class SuggestionAudit(models.Model):
    """
    Tracks every AI suggestion and whether the doctor accepted or rejected it.
    Required for compliance and model improvement.
    """
    ACTION_CHOICES = [
        ("accepted", "Accepted"),
        ("rejected", "Rejected"),
        ("modified", "Modified and Accepted"),
    ]

    job             = models.ForeignKey(AIJob, on_delete=models.CASCADE,
                                        related_name="suggestion_audits")
    encounter       = models.ForeignKey(Encounter, on_delete=models.CASCADE,
                                        related_name="suggestion_audits")
    doctor          = models.ForeignKey(StaffUser, on_delete=models.PROTECT,
                                        limit_choices_to={"role": "doctor"})
    suggestion_type = models.CharField(max_length=50)   # "diagnosis", "prescription", etc.
    suggested_value = models.JSONField()                 # what AI suggested
    final_value     = models.JSONField(null=True, blank=True)  # what doctor used (if modified)
    action          = models.CharField(max_length=20, choices=ACTION_CHOICES)
    reviewed_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "ai_pipeline"
        db_table  = "suggestion_audit"
