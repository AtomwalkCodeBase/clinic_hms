"""apps/clinical/views.py"""
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from core.response import success, created, error, not_found
from core.permissions import IsDoctor, IsNurse, IsDoctorOrNurse, IsHospitalStaff
from core.pagination import paginate_queryset

from .serializers import (
    EncounterDetailSerializer, EncounterListSerializer,
    VitalSerializer, DiagnosisSerializer,
)
from .models import Encounter, Vital, Diagnosis


class EncounterListCreateView(APIView):
    """GET + POST /api/v1/clinical/encounters/"""
    permission_classes = [IsAuthenticated, IsDoctorOrNurse]

    def get(self, request):
        qs = Encounter.objects.using(request.tenant_db).select_related(
            "patient", "doctor"
        ).order_by("-encounter_date", "-created_at")
        # Optional filter by doctor
        doctor_id = request.query_params.get("doctor_id")
        if doctor_id:
            qs = qs.filter(doctor_id=doctor_id)
        patient_id = request.query_params.get("patient_id")
        if patient_id:
            qs = qs.filter(patient_id=patient_id)
        page_items, meta = paginate_queryset(request, qs)
        return success(data={
            "results": EncounterListSerializer(page_items, many=True).data,
            "pagination": meta,
        })

    def post(self, request):
        serializer = EncounterDetailSerializer(data=request.data)
        if not serializer.is_valid():
            return error("Validation error.", errors=serializer.errors)
        encounter = Encounter.objects.using(request.tenant_db).create(
            **{k: v for k, v in serializer.validated_data.items()
               if k not in ("vitals", "diagnoses", "followups", "documents")}
        )
        return created(data=EncounterDetailSerializer(encounter).data)


class EncounterDetailView(APIView):
    """GET /api/v1/clinical/encounters/<id>/"""
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request, pk):
        try:
            enc = Encounter.objects.using(request.tenant_db).prefetch_related(
                "vitals", "diagnoses", "followups", "documents"
            ).get(pk=pk)
        except Encounter.DoesNotExist:
            return not_found("Encounter not found.")
        return success(data=EncounterDetailSerializer(enc).data)


class EncounterCloseView(APIView):
    """POST /api/v1/clinical/encounters/<id>/close/"""
    permission_classes = [IsAuthenticated, IsDoctor]

    def post(self, request, pk):
        try:
            enc = Encounter.objects.using(request.tenant_db).get(pk=pk)
        except Encounter.DoesNotExist:
            return not_found("Encounter not found.")
        if enc.status == "closed":
            return error("Encounter is already closed.")
        enc.status    = "closed"
        enc.closed_at = timezone.now()
        enc.save(using=request.tenant_db, update_fields=["status", "closed_at"])
        # Signal fires here → HIE write-through
        return success(message="Encounter closed.")


class VitalListCreateView(APIView):
    """GET + POST /api/v1/clinical/vitals/"""
    permission_classes = [IsAuthenticated, IsDoctorOrNurse]

    def get(self, request):
        patient_id = request.query_params.get("patient_id")
        if not patient_id:
            return error("patient_id query parameter is required.")
        qs = Vital.objects.using(request.tenant_db).filter(
            patient_id=patient_id
        ).order_by("-recorded_at")
        page_items, meta = paginate_queryset(request, qs)
        return success(data={
            "results": VitalSerializer(page_items, many=True).data,
            "pagination": meta,
        })

    def post(self, request):
        serializer = VitalSerializer(data=request.data)
        if not serializer.is_valid():
            return error("Validation error.", errors=serializer.errors)
        vital = Vital.objects.using(request.tenant_db).create(**serializer.validated_data)
        return created(data=VitalSerializer(vital).data)


class DiagnosisListCreateView(APIView):
    """GET + POST /api/v1/clinical/diagnoses/"""
    permission_classes = [IsAuthenticated, IsDoctor]

    def get(self, request):
        encounter_id = request.query_params.get("encounter_id")
        if not encounter_id:
            return error("encounter_id required.")
        qs = Diagnosis.objects.using(request.tenant_db).filter(encounter_id=encounter_id)
        return success(data=DiagnosisSerializer(qs, many=True).data)

    def post(self, request):
        serializer = DiagnosisSerializer(data=request.data)
        if not serializer.is_valid():
            return error("Validation error.", errors=serializer.errors)
        diagnosis = Diagnosis.objects.using(request.tenant_db).create(**serializer.validated_data)
        return created(data=DiagnosisSerializer(diagnosis).data)
