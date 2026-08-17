from rest_framework import serializers
from .models import LabTest, LabRequest, LabReport, LabReportItem


class LabTestSerializer(serializers.ModelSerializer):
    class Meta:
        model  = LabTest
        fields = ["id", "name", "code", "sample_type", "turnaround_hours", "price", "description", "is_active"]
        read_only_fields = ["id"]


class LabReportItemSerializer(serializers.ModelSerializer):
    class Meta:
        model  = LabReportItem
        fields = ["id", "parameter_name", "result_value", "unit", "reference_range", "is_abnormal"]
        read_only_fields = ["id"]


class LabReportSerializer(serializers.ModelSerializer):
    items = LabReportItemSerializer(many=True, read_only=True)

    class Meta:
        model  = LabReport
        fields = ["id", "request", "patient", "report_number", "status",
                  "result_summary", "file_url", "file_name", "mime_type",
                  "performed_by", "verified_by", "delivered_at", "created_at", "items"]
        read_only_fields = ["id", "report_number", "created_at"]


class LabRequestSerializer(serializers.ModelSerializer):
    test_name        = serializers.CharField(source="test.name", read_only=True)
    test_code        = serializers.CharField(source="test.code", read_only=True)
    test_price       = serializers.DecimalField(source="test.price", max_digits=8, decimal_places=2, read_only=True)
    test_turnaround_hours = serializers.IntegerField(source="test.turnaround_hours", read_only=True)
    patient_name     = serializers.CharField(source="patient.full_name", read_only=True)
    patient_uhid     = serializers.CharField(source="patient.uhid", read_only=True)
    patient_phone    = serializers.CharField(source="patient.mobile", read_only=True)
    requested_by_name = serializers.SerializerMethodField()
    report           = serializers.SerializerMethodField()
    attached_document = serializers.SerializerMethodField()

    class Meta:
        model  = LabRequest
        fields = [
            "id", "patient", "patient_name", "patient_uhid", "patient_phone",
            "encounter", "appointment_id", "test", "test_name", "test_code",
            "test_price", "test_turnaround_hours",
            "requested_by", "requested_by_name", "branch",
            "status", "urgency", "clinical_notes", "request_number",
            "patient_choice", "payment_preference", "payment_status",
            "choice_made_by", "choice_made_at", "invoice_id",
            "ordered_at", "collected_at", "report", "attached_document",
        ]
        read_only_fields = ["id", "request_number", "ordered_at", "invoice_id"]

    def get_requested_by_name(self, obj):
        try:
            return f"{obj.requested_by.first_name} {obj.requested_by.last_name}".strip()
        except Exception:
            return ""

    def get_report(self, obj):
        try:
            r = obj.report
        except LabReport.DoesNotExist:
            return None
        return {
            "id": r.id, "status": r.status, "report_number": r.report_number,
            "result_summary": r.result_summary, "file_data": r.file_url,
            "file_name": r.file_name, "mime_type": r.mime_type,
            "delivered_at": r.delivered_at,
            "items": LabReportItemSerializer(r.items.all(), many=True).data,
        }

    def get_attached_document(self, obj):
        """
        For "outside" orders — the report the patient (or nurse, on their
        behalf) uploaded via the patient-document flow, so doctor/nurse
        logins can open it the same way the patient portal already can.
        Only a lightweight pointer (id/title) — full content is fetched
        on demand via PATIENTS.DOCUMENT(id), same as the History sidebar's
        Attachments section, to keep this list endpoint cheap.
        """
        if obj.patient_choice != "outside":
            return None
        db = self.context.get("db")
        if not db:
            return None
        try:
            awpid = obj.patient.awpid
        except Exception:
            return None
        from apps.registry.models import SharedDocument
        doc = (SharedDocument.objects.using("default")
               .filter(awpid=awpid, source_ref=f"labreq:{db}:{obj.id}")
               .order_by("-created_at").first())
        if not doc:
            return None
        return {"id": doc.id, "title": doc.title, "created_at": doc.created_at}


class LabRequestChoiceSerializer(serializers.Serializer):
    patient_choice     = serializers.ChoiceField(choices=["in_house", "outside"])
    payment_preference = serializers.ChoiceField(choices=["pay_online", "pay_at_lab"], required=False, allow_blank=True)
