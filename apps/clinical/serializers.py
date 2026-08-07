"""apps/clinical/serializers.py"""
from rest_framework import serializers
from .models import Encounter, Vital, Diagnosis, FollowUp, ClinicalDocument


class VitalSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Vital
        fields = [
            "id", "patient", "encounter", "source", "recorded_at",
            "bp_systolic", "bp_diastolic", "pulse_rate", "spo2",
            "temperature", "weight_kg", "height_cm", "resp_rate",
            "blood_sugar_mgdl", "notes",
        ]
        read_only_fields = ["id"]


class DiagnosisSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Diagnosis
        fields = [
            "id", "encounter", "icd10_code", "description",
            "clinical_status", "is_primary", "onset_date", "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class FollowUpSerializer(serializers.ModelSerializer):
    class Meta:
        model  = FollowUp
        fields = ["id", "encounter", "follow_up_date", "instructions", "referral_to", "created_at"]
        read_only_fields = ["id", "created_at"]


class ClinicalDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ClinicalDocument
        fields = ["id", "patient", "encounter", "document_type", "title", "file_url", "uploaded_at"]
        read_only_fields = ["id", "uploaded_at"]


class EncounterDetailSerializer(serializers.ModelSerializer):
    vitals     = VitalSerializer(many=True, read_only=True)
    diagnoses  = DiagnosisSerializer(many=True, read_only=True)
    followups  = FollowUpSerializer(many=True, read_only=True)
    documents  = ClinicalDocumentSerializer(many=True, read_only=True)

    class Meta:
        model  = Encounter
        fields = [
            "id", "patient", "doctor", "branch", "department",
            "encounter_date", "status", "chief_complaint", "history",
            "examination_notes", "advice", "closed_at", "created_at",
            "vitals", "diagnoses", "followups", "documents",
        ]
        read_only_fields = ["id", "status", "closed_at", "created_at"]


class EncounterListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views."""
    class Meta:
        model  = Encounter
        fields = ["id", "patient", "doctor", "encounter_date", "status", "chief_complaint", "created_at"]
