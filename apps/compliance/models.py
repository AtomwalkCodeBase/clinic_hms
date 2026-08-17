"""
apps/compliance/models.py
--------------------------
Tables: RecordAmendment, ConsentRecord

RecordAmendment — DPDP Act Article 13 correction-request and resolution log.
ConsentRecord   — immutable proof-of-consent trail (DPDP data-processing
                  consent + HIE cross-hospital data-sharing consent).

AccessLog (PHI access audit trail) was removed here (2026-08-17) — it was
never wired to anything and duplicated a system that already exists and is
already live: apps.org.AuditLog, written via core.audit.log_action() from
apps/opd/views.py and apps/patients/views.py. See apps/compliance/views.py's
AuditLogListView, which reads from apps.org.AuditLog rather than this app —
there is only one PHI access-log table in this codebase, not two.

Data is NEVER deleted regardless of account status (legal requirement).
"""

from django.db import models
from apps.org.models import StaffUser
from apps.patients.models import Patient


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


class ConsentRecord(models.Model):
    """
    Immutable proof-of-consent trail (DPDP Act 2023).

    Patient.dpdp_consent_captured/dpdp_consent_at and
    Patient.hie_consent_given/hie_consent_at (apps.patients.models) are the
    fast "is this patient currently consented" flags checked at request time
    — see PatientHistoryView and PortalBookView. Those fields are mutable
    columns on a row that's updated for other reasons too, so they're not
    durable proof on their own: nothing stops them from being silently
    overwritten, and they don't record what was actually agreed to, from
    where, or under which version of the consent text.

    ConsentRecord is the append-only trail behind those flags — one row
    per consent EVENT, written at the same two points the boolean flags are
    set (apps.patients.services.PatientService.register for front-desk
    registration, apps.patients.portal_views.PortalBookView for a patient's
    first booking at a new hospital), never edited or deleted afterward.
    """
    CONSENT_DPDP_PROCESSING = "dpdp_data_processing"
    CONSENT_HIE_SHARING     = "hie_data_sharing"
    CONSENT_TYPE_CHOICES = [
        (CONSENT_DPDP_PROCESSING, "DPDP — Personal Data Processing"),
        (CONSENT_HIE_SHARING,     "HIE — Cross-Hospital Data Sharing"),
    ]

    SOURCE_FRONT_DESK = "front_desk"
    SOURCE_PORTAL     = "patient_portal"
    SOURCE_CHOICES = [
        (SOURCE_FRONT_DESK, "Front Desk Registration"),
        (SOURCE_PORTAL,     "Patient Portal"),
    ]

    patient         = models.ForeignKey(Patient, on_delete=models.PROTECT,
                                        related_name="consent_records")
    consent_type    = models.CharField(max_length=30, choices=CONSENT_TYPE_CHOICES, db_index=True)
    granted         = models.BooleanField(default=True)
    source          = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    # Who captured it — set for front-desk-attested consent (staff confirms
    # they obtained it from the patient); null for patient-portal consent,
    # since there the patient is the one performing the action themselves.
    recorded_by     = models.ForeignKey(StaffUser, on_delete=models.SET_NULL,
                                        null=True, blank=True)
    ip_address      = models.GenericIPAddressField(null=True, blank=True)
    user_agent      = models.TextField(blank=True)
    # Free-text tag for whichever version of the consent/policy language was
    # shown at the time — bump this constant (see services.py) whenever the
    # actual consent copy changes, so old rows stay honest about what the
    # patient actually saw rather than being silently reinterpreted later.
    policy_version  = models.CharField(max_length=20, default="v1")
    notes           = models.TextField(blank=True)
    created_at      = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        app_label = "compliance"
        db_table  = "consent_record"
        ordering  = ["-created_at"]

    def __str__(self):
        return f"{self.get_consent_type_display()} — {'granted' if self.granted else 'revoked'} ({self.source})"
