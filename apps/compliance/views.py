"""
apps/compliance/views.py
--------------------------
Two audiences:

  Hospital staff (tenant-scoped, request.tenant_db already resolved by
  JWTTenantAuthentication):
    AuditLogListView             — read apps.org.AuditLog (PHI access trail)
    RecordAmendmentStaffListView — list correction requests for this hospital
    RecordAmendmentResolveView   — approve/reject a request
    ConsentRecordListView        — a patient's consent history

  Patients (portal JWT has no fixed tenant — request.tenant_db is None; a
  hospital must be picked explicitly, same pattern as
  apps.patients.portal_views.PortalBookView):
    PortalRecordAmendmentView    — GET: my requests across every hospital
                                    POST: submit a new request against one
"""

import logging

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from core.response import success, error, created, not_found
from core.pagination import paginate_queryset, paginate_list
from core.permissions import IsHospitalAdmin, IsHospitalStaff, IsPatient

from .models import RecordAmendment, ConsentRecord
from .serializers import (
    AuditLogSerializer,
    RecordAmendmentSerializer,
    RecordAmendmentCreateSerializer,
    RecordAmendmentResolveSerializer,
    ConsentRecordSerializer,
)

logger = logging.getLogger(__name__)


# ── Hospital staff: PHI access log ──────────────────────────────────────────

class AuditLogListView(APIView):
    """
    GET /api/v1/compliance/audit-log/
    Query params: patient_id (uuid), action (substring), resource_type, page, page_size.
    Hospital-admin-only — this is every staff member's PHI access trail for
    the whole hospital, not something a doctor needs to browse day to day.
    """
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def get(self, request):
        from apps.org.models import AuditLog

        qs = AuditLog.objects.using(request.tenant_db).all()

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
    """
    GET /api/v1/compliance/amendments/
    Query params: status (pending/approved/rejected), page, page_size.
    """
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def get(self, request):
        db = request.tenant_db
        qs = RecordAmendment.objects.using(db).select_related("patient", "reviewed_by").all()

        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        page_items, meta = paginate_queryset(request, qs)
        return success(data={
            "results": RecordAmendmentSerializer(page_items, many=True).data,
            "pagination": meta,
        })


class RecordAmendmentResolveView(APIView):
    """
    POST /api/v1/compliance/amendments/<pk>/resolve/
    Body: {status: "approved"|"rejected", review_notes}

    Records the decision only — it does NOT automatically rewrite the
    underlying field. Auto-applying an arbitrary (resource_type, resource_id,
    field_name) triple across every model in the system is exactly the kind
    of "generic write" that turns a correction workflow into a data-integrity
    hole. The reviewer applies the actual fix through the normal edit screen
    for that record, then marks the request resolved here — same
    responsibility split as any real medical-records-correction process.
    """
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def post(self, request, pk):
        from django.utils import timezone

        db = request.tenant_db
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
    """
    GET /api/v1/compliance/consents/?patient_id=
    Any hospital staff member can look this up for a specific patient — same
    visibility level as viewing the rest of that patient's chart.
    """
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request):
        db = request.tenant_db
        qs = ConsentRecord.objects.using(db).select_related("patient", "recorded_by").all()

        patient_id = request.query_params.get("patient_id")
        if patient_id:
            qs = qs.filter(patient_id=patient_id)

        page_items, meta = paginate_queryset(request, qs)
        return success(data={
            "results": ConsentRecordSerializer(page_items, many=True).data,
            "pagination": meta,
        })


# ── Patient portal: request a correction ────────────────────────────────────

class PortalRecordAmendmentView(APIView):
    """
    GET  /api/v1/compliance/portal/amendments/            — my requests, every hospital
    POST /api/v1/compliance/portal/amendments/             — submit a new request
      Body: {tenant_id, patient_awpid? (defaults to self),
             resource_type, resource_id, field_name, current_value?,
             requested_value, reason?}
    """
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.tenants.models import Tenant
        from apps.patients.models import Patient
        from apps.registry.models import PatientAccount

        acct = PatientAccount.objects.using("default").get(pk=request.user.id)

        results = []
        for tenant in Tenant.objects.using("default").filter(is_active=True):
            db = tenant.db_name
            try:
                from apps.tenants.utils import _make_db_config
                from django.conf import settings
                if db not in settings.DATABASES:
                    settings.DATABASES[db] = _make_db_config(db)

                patient = Patient.objects.using(db).filter(awpid=acct.awpid).first()
                if not patient:
                    continue
                rows = RecordAmendment.objects.using(db).filter(patient=patient).select_related("reviewed_by")
                for row in rows:
                    data = RecordAmendmentSerializer(row).data
                    data["hospital"] = tenant.name
                    data["tenant_id"] = tenant.id
                    results.append(data)
            except Exception as exc:
                logger.warning("portal amendments: skipped %s (%s)", db, exc)

        results.sort(key=lambda r: r["requested_at"], reverse=True)
        page_items, meta = paginate_list(request, results)
        return success(data={"results": page_items, "pagination": meta})

    def post(self, request):
        from apps.tenants.models import Tenant
        from apps.tenants.utils import _make_db_config
        from apps.patients.models import Patient
        from apps.registry.models import PatientAccount, PatientRelationship
        from django.conf import settings

        d = request.data
        tenant_id = d.get("tenant_id")
        if not tenant_id:
            return error("tenant_id is required.", errors={"tenant_id": "Required."})

        try:
            tenant = Tenant.objects.using("default").get(pk=tenant_id, is_active=True)
        except Tenant.DoesNotExist:
            return error("Hospital not found.")

        acct = PatientAccount.objects.using("default").get(pk=request.user.id)
        target_awpid = (d.get("patient_awpid") or "").strip() or acct.awpid
        if target_awpid != acct.awpid:
            is_family = PatientRelationship.objects.using("default").filter(
                guardian_awpid=acct.awpid, dependent_awpid=target_awpid,
            ).exists()
            if not is_family:
                return error("That patient isn't linked to your account.", status=403)

        db = tenant.db_name
        if db not in settings.DATABASES:
            settings.DATABASES[db] = _make_db_config(db)

        patient = Patient.objects.using(db).filter(awpid=target_awpid).first()
        if not patient:
            return error("No record found for this patient at that hospital.")

        serializer = RecordAmendmentCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return error("Validation error.", errors=serializer.errors)

        row = RecordAmendment.objects.using(db).create(patient=patient, **serializer.validated_data)
        data = RecordAmendmentSerializer(row).data
        data["hospital"] = tenant.name
        data["tenant_id"] = tenant.id
        return created(data=data, message="Correction request submitted.")
