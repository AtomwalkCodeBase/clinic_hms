"""
apps/compliance/serializers.py
--------------------------------
Serializers for the audit-log review API (backed by apps.org.AuditLog, not
a table in this app — see views.py::AuditLogListView), RecordAmendment
(patient correction requests), and ConsentRecord (consent proof trail).
"""

from rest_framework import serializers

from .models import RecordAmendment, ConsentRecord


class AuditLogSerializer(serializers.Serializer):
    """
    Read-only — mirrors apps.org.models.AuditLog. A plain Serializer (not
    ModelSerializer) because this app doesn't own that model; it just reads
    it from the tenant DB (see views.py).
    """
    id             = serializers.IntegerField()
    actor_user_id  = serializers.IntegerField(allow_null=True)
    actor_email    = serializers.CharField()
    actor_role     = serializers.CharField()
    action         = serializers.CharField()
    resource_type  = serializers.CharField()
    resource_id    = serializers.CharField()
    patient_id     = serializers.UUIDField(allow_null=True)
    ip_address     = serializers.IPAddressField(allow_null=True)
    metadata       = serializers.JSONField()
    created_at     = serializers.DateTimeField()


class RecordAmendmentSerializer(serializers.ModelSerializer):
    patient_name      = serializers.CharField(source="patient.full_name", read_only=True)
    patient_uhid      = serializers.CharField(source="patient.uhid", read_only=True)
    reviewed_by_name  = serializers.SerializerMethodField()
    status_display    = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = RecordAmendment
        fields = [
            "id", "patient", "patient_name", "patient_uhid",
            "resource_type", "resource_id", "field_name",
            "current_value", "requested_value", "reason",
            "status", "status_display", "reviewed_by", "reviewed_by_name",
            "review_notes", "requested_at", "resolved_at",
        ]
        read_only_fields = [
            "id", "patient", "patient_name", "patient_uhid", "reviewed_by",
            "reviewed_by_name", "status_display", "requested_at", "resolved_at",
        ]

    def get_reviewed_by_name(self, obj):
        if not obj.reviewed_by_id:
            return None
        return obj.reviewed_by.get_full_name() or obj.reviewed_by.email or obj.reviewed_by.phone


class RecordAmendmentCreateSerializer(serializers.Serializer):
    """
    Patient-facing — what a patient submits to request a correction.
    `patient` and `status` are set by the view, not accepted from the client.
    """
    resource_type   = serializers.CharField(max_length=50)
    # A patient describing "my address is wrong" has no way to know the
    # internal row id of their own Patient record — defaults to 0 (not a
    # real id) when omitted; the reviewing staff member resolves the exact
    # record from resource_type + field_name + the patient it's attached to.
    resource_id     = serializers.IntegerField(required=False, default=0)
    field_name      = serializers.CharField(max_length=100)
    current_value   = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    requested_value = serializers.CharField(max_length=2000)
    reason          = serializers.CharField(max_length=2000, required=False, allow_blank=True)


class RecordAmendmentResolveSerializer(serializers.Serializer):
    """Staff-facing — approve or reject a pending request."""
    status       = serializers.ChoiceField(choices=[RecordAmendment.STATUS_CHOICES[1], RecordAmendment.STATUS_CHOICES[2]])
    review_notes = serializers.CharField(max_length=2000, required=False, allow_blank=True)


class ConsentRecordSerializer(serializers.ModelSerializer):
    patient_name         = serializers.CharField(source="patient.full_name", read_only=True)
    patient_uhid         = serializers.CharField(source="patient.uhid", read_only=True)
    consent_type_display = serializers.CharField(source="get_consent_type_display", read_only=True)
    source_display       = serializers.CharField(source="get_source_display", read_only=True)
    recorded_by_name     = serializers.SerializerMethodField()

    class Meta:
        model = ConsentRecord
        fields = [
            "id", "patient", "patient_name", "patient_uhid",
            "consent_type", "consent_type_display", "granted", "source", "source_display",
            "recorded_by", "recorded_by_name", "ip_address", "policy_version",
            "notes", "created_at",
        ]
        read_only_fields = fields

    def get_recorded_by_name(self, obj):
        if not obj.recorded_by_id:
            return None
        return obj.recorded_by.get_full_name() or obj.recorded_by.email or obj.recorded_by.phone
