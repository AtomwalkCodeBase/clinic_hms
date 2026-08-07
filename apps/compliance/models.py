"""
apps/compliance/models.py
--------------------------
Tables: AccessLog, RecordAmendment

AccessLog — audit trail for every PHI (Protected Health Information) access.
            High volume; partition by month in production (PostgreSQL range partitioning).
RecordAmendment — DPDP Act correction request and resolution log.

Data is NEVER deleted regardless of account status (legal requirement).
"""

from django.db import models
from apps.org.models import StaffUser
from apps.patients.models import Patient


class AccessLog(models.Model):
    """
    Immutable audit record written every time patient PHI is read or modified.
    action: view, create, update (no delete — records are never deleted).
    resource_type + resource_id identify the affected record.
    ip_address and user_agent for forensic trails.

    Production note: partition this table by year/month using PostgreSQL
    declarative partitioning (partition key: accessed_at).
    """
    ACTION_CHOICES = [
        ("view",   "Viewed"),
        ("create", "Created"),
        ("update", "Updated"),
        ("export", "Exported"),
    ]

    staff           = models.ForeignKey(StaffUser, on_delete=models.SET_NULL,
                                        null=True, blank=True)
    patient         = models.ForeignKey(Patient, on_delete=models.SET_NULL,
                                        null=True, blank=True, related_name="access_logs")
    action          = models.CharField(max_length=20, choices=ACTION_CHOICES)
    resource_type   = models.CharField(max_length=50)   # e.g. "Encounter", "LabReport"
    resource_id     = models.IntegerField(null=True, blank=True)
    ip_address      = models.GenericIPAddressField(null=True, blank=True)
    user_agent      = models.TextField(blank=True)
    accessed_at     = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        app_label = "compliance"
        db_table  = "access_log"
        # Do not add indexes on all columns — accessed_at is enough for partition pruning
        ordering  = ["-accessed_at"]

    def __str__(self):
        return f"{self.action} {self.resource_type}#{self.resource_id} by staff#{self.staff_id}"


class RecordAmendment(models.Model):
    """
    DPDP Act Article 13 — patient right to correction.
    Patient raises a request to correct inaccurate personal data.
    Platform records the request, resolution, and whether it was applied.
    """
    STATUS_CHOICES = [
        ("pending",  "Pending Review"),
        ("approved", "Approved and Applied"),
        ("rejected", "Rejected with Reason"),
    ]

    patient         = models.ForeignKey(Patient, on_delete=models.PROTECT,
                                        related_name="amendments")
    resource_type   = models.CharField(max_length=50)   # which table/field
    resource_id     = models.IntegerField()
    field_name      = models.CharField(max_length=100)
    current_value   = models.TextField(blank=True)
    requested_value = models.TextField()
    reason          = models.TextField(blank=True)
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending", db_index=True)
    reviewed_by     = models.ForeignKey(StaffUser, on_delete=models.SET_NULL,
                                        null=True, blank=True)
    review_notes    = models.TextField(blank=True)
    requested_at    = models.DateTimeField(auto_now_add=True)
    resolved_at     = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "compliance"
        db_table  = "record_amendment"
        ordering  = ["-requested_at"]

    def __str__(self):
        return f"Amendment #{self.id} — {self.resource_type} ({self.status})"
