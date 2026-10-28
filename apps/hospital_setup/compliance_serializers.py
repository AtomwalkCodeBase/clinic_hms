"""apps/hospital_setup/compliance_serializers.py"""

from rest_framework import serializers
from core.api.serializers import PkModelSerializer

from apps.hospital_setup.models import RecordAmendment


class AuditLogSerializer(serializers.Serializer):
    """Read-only — mirrors apps.hospital_setup.models.AuditLog. A plain Serializer (not"""
    id             = serializers.IntegerField()
    actor_user_id  = serializers.IntegerField(allow_null=True)
    actor_email    = serializers.CharField()
    actor_role     = serializers.CharField()
    action         = serializers.CharField()
    resource_type  = serializers.CharField()
    resource_id    = serializers.CharField()
    patient_id     = serializers.IntegerField(allow_null=True)
    ip_address     = serializers.IPAddressField(allow_null=True)
    metadata       = serializers.JSONField()
    created_at     = serializers.DateTimeField()


class RecordAmendmentSerializer(PkModelSerializer):
    patient_name      = serializers.CharField(source="patient.get_patient_details.full_name", read_only=True)
    patient_uhid      = serializers.CharField(source="patient.uhid", read_only=True)
    reviewed_by_name  = serializers.SerializerMethodField()
    status_display    = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = RecordAmendment
        fields = [
            "record_amendment_id", "patient", "patient_name", "patient_uhid",
            "resource_type", "resource_id", "field_name",
            "current_value", "requested_value", "reason",
            "status", "status_display", "reviewed_by", "reviewed_by_name",
            "review_notes", "requested_at", "resolved_at",
        ]
        read_only_fields = [
            "record_amendment_id", "patient", "patient_name", "patient_uhid", "reviewed_by",
            "reviewed_by_name", "status_display", "requested_at", "resolved_at",
        ]

    def get_reviewed_by_name(self, obj):
        if not obj.reviewed_by_id:
            return None
        return obj.reviewed_by.get_full_name() or obj.reviewed_by.email or obj.reviewed_by.phone


class RecordAmendmentCreateSerializer(serializers.Serializer):
    """Patient-facing — what a patient submits to request a correction."""
    resource_type   = serializers.CharField(max_length=50)
    # A patient describing "my address is wrong" has no way to know the
    resource_id     = serializers.CharField(max_length=64, required=False, default="0")
    field_name      = serializers.CharField(max_length=100)
    current_value   = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    requested_value = serializers.CharField(max_length=2000)
    reason          = serializers.CharField(max_length=2000, required=False, allow_blank=True)


class RecordAmendmentResolveSerializer(serializers.Serializer):
    """Staff-facing — approve or reject a pending request."""
    status       = serializers.ChoiceField(choices=[RecordAmendment.STATUS_CHOICES[1], RecordAmendment.STATUS_CHOICES[2]])
    review_notes = serializers.CharField(max_length=2000, required=False, allow_blank=True)


