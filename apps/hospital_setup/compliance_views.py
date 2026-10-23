"""apps/hospital_setup/compliance_views.py"""

import logging

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from core.api.response import success, error, created, not_found
from core.api.pagination import paginate_queryset, paginate_list
from core.api.permissions import IsHospitalAdmin, IsHospitalStaff, IsPatient

from apps.hospital_setup.models import RecordAmendment, ConsentRecord
from apps.hospital_setup.compliance_serializers import (
    AuditLogSerializer,
    RecordAmendmentSerializer,
    RecordAmendmentCreateSerializer,
    RecordAmendmentResolveSerializer,
    ConsentRecordSerializer,
)
from apps.patients.services import accounts

logger = logging.getLogger(__name__)


# ── Hospital staff: PHI access log ──────────────────────────────────────────

class AuditLogListView(APIView):
    """GET /api/v1/compliance/audit-log/"""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def get(self, request):
        from apps.hospital_setup.models import AuditLog

        qs = AuditLog.objects.using(request.hospital_db).all()

        patient_id = request.query_params.get("patient_id")
        if patient_id:
            qs = qs.filter(patient_id=patient_id)

        action = request.query_params.get("action")
        if action:
            qs = qs.filter(action__icontains=action)

        resource_type = request.query_params.get("resource_type")
        if resource_type:
            qs = qs.filter(resource_type__iexact=resource_type)

        page_items, meta = paginate_queryset(request, qs)
        return success(data={
            "results": AuditLogSerializer(page_items, many=True).data,
            "pagination": meta,
        })


# ── Hospital staff: record amendments (DPDP Art. 13) ───────────────────────

class RecordAmendmentStaffListView(APIView):
    """GET /api/v1/compliance/amendments/"""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def get(self, request):
        db = request.hospital_db
        qs = RecordAmendment.objects.using(db).select_related("patient", "reviewed_by").all()

        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        page_items, meta = paginate_queryset(request, qs)
        patients = [a.patient for a in page_items]
        for p in patients[:1]:
            p.get_patient_details(batch=patients)
        return success(data={
            "results": RecordAmendmentSerializer(page_items, many=True).data,
            "pagination": meta,
        })


class RecordAmendmentResolveView(APIView):
    """POST /api/v1/compliance/amendments/<pk>/resolve/"""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def post(self, request, pk):
        from django.utils import timezone

        db = request.hospital_db
        try:
            amendment = RecordAmendment.objects.using(db).get(pk=pk)
        except RecordAmendment.DoesNotExist:
            return not_found("Amendment request not found.")

        if amendment.status != "pending":
            return error("This request has already been resolved.")

        serializer = RecordAmendmentResolveSerializer(data=request.data)
        if not serializer.is_valid():
            return error("Validation error.", errors=serializer.errors)

        d = serializer.validated_data
        amendment.status = d["status"]
        amendment.review_notes = d.get("review_notes", "")
        amendment.reviewed_by_id = request.user.id
        amendment.resolved_at = timezone.now()
        amendment.save(using=db, update_fields=["status", "review_notes", "reviewed_by", "resolved_at"])

        return success(data=RecordAmendmentSerializer(amendment).data, message="Request resolved.")


# ── Hospital staff: consent history ─────────────────────────────────────────

class ConsentRecordListView(APIView):
    """GET /api/v1/compliance/consents/?patient_id="""
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request):
        db = request.hospital_db
        qs = ConsentRecord.objects.using(db).select_related("patient", "recorded_by").all()

        patient_id = request.query_params.get("patient_id")
        if patient_id:
            qs = qs.filter(patient_id=patient_id)

        page_items, meta = paginate_queryset(request, qs)
        patients = [c.patient for c in page_items]
        for p in patients[:1]:
            p.get_patient_details(batch=patients)
        return success(data={
            "results": ConsentRecordSerializer(page_items, many=True).data,
            "pagination": meta,
        })


# ── Patient portal: request a correction ────────────────────────────────────

class PortalRecordAmendmentView(APIView):
    """GET  /api/v1/compliance/portal/amendments/            — my requests, every hospital"""
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.hospital_master.models import Hospital
        from apps.opd.models import HospitalPatient
        from apps.patients.models import PatientRelationship

        acct = accounts().get(pk=request.user.id)
        target_awpid = (request.query_params.get("patient_awpid") or "").strip() or acct.awpid
        if target_awpid != acct.awpid:
            is_family = PatientRelationship.objects.using("default").filter(
                guardian__awpid=acct.awpid, dependent__awpid=target_awpid,
            ).exists()
            if not is_family:
                return error("That patient isn't linked to your account.", status=403)

        results = []
        for hospital in Hospital.objects.using("default").filter(is_active=True):
            db = hospital.db_name
            try:
                from apps.hospital_master.services import ensure_hospital_db
                ensure_hospital_db(db)

                patient = HospitalPatient.objects.using(db).filter(awpid=target_awpid).first()
                if not patient:
                    continue
                rows = RecordAmendment.objects.using(db).filter(patient=patient).select_related("reviewed_by")
                for row in rows:
                    data = RecordAmendmentSerializer(row).data
                    data["hospital"] = hospital.name
                    data["hospital_id"] = hospital.id
                    results.append(data)
            except Exception as exc:
                logger.warning("portal amendments: skipped %s (%s)", db, exc)

        results.sort(key=lambda r: r["requested_at"], reverse=True)
        page_items, meta = paginate_list(request, results)
        return success(data={"results": page_items, "pagination": meta})

    def post(self, request):
        from apps.hospital_master.models import Hospital
        from apps.hospital_master.services import ensure_hospital_db
        from apps.opd.models import HospitalPatient
        from apps.patients.models import PatientRelationship

        d = request.data
        hospital_id = d.get("hospital_id")
        if not hospital_id:
            return error("hospital_id is required.", errors={"hospital_id": "Required."})

        try:
            hospital = Hospital.objects.using("default").get(pk=hospital_id, is_active=True)
        except Hospital.DoesNotExist:
            return error("Hospital not found.")

        acct = accounts().get(pk=request.user.id)
        target_awpid = (d.get("patient_awpid") or "").strip() or acct.awpid
        if target_awpid != acct.awpid:
            is_family = PatientRelationship.objects.using("default").filter(
                guardian__awpid=acct.awpid, dependent__awpid=target_awpid,
            ).exists()
            if not is_family:
                return error("That patient isn't linked to your account.", status=403)

        db = hospital.db_name
        ensure_hospital_db(db)

        patient = HospitalPatient.objects.using(db).filter(awpid=target_awpid).first()
        if not patient:
            return error("No record found for this patient at that hospital.")

        serializer = RecordAmendmentCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return error("Validation error.", errors=serializer.errors)

        row = RecordAmendment.objects.using(db).create(patient=patient, **serializer.validated_data)
        data = RecordAmendmentSerializer(row).data
        data["hospital"] = hospital.name
        data["hospital_id"] = hospital.id
        return created(data=data, message="Correction request submitted.")
