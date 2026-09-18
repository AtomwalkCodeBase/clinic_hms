"""
apps/patients/pediatric_views.py
------------------------------------
Staff-facing pediatric-only endpoints, split out of growth_vaccination_views.py
to keep the birth-history and developmental-milestone additions separate
from the pre-existing growth/vaccination code they sit alongside.

  GET   /api/v1/patients/<pk>/birth-history/          — view (any hospital staff)
  POST  /api/v1/patients/<pk>/birth-history/          — create (front desk or doctor)
  PATCH /api/v1/patients/<pk>/birth-history/           — edit (front desk or doctor)

  GET  /api/v1/patients/<pk>/milestones/              — roadmap (schedule + real records)
  POST /api/v1/patients/<pk>/milestones/               — record an assessment

Every endpoint here is pediatric-only in *intent* — the frontend gates these
screens/panels to minor patients (age < 18, the same is_minor derivation
PatientGrowthView already uses) — but the backend does not hard-block an
adult patient_id from being posted to, matching how PatientVaccinationListCreateView
and PatientAllergyListCreateView also don't age-gate server-side. The age
check belongs at the UI layer because it's a display/workflow concern, not
a data-integrity one; nothing here is unsafe to store against an adult
record, it just wouldn't normally happen.
"""

import logging
from datetime import date

from django.utils import timezone
from rest_framework.views import APIView

from core.response import success, created, error, not_found
from core.permissions import IsHospitalStaff, IsDoctorOrFrontDesk, IsDoctorOrNurse

from .models import Patient, BirthHistory
from .serializers import BirthHistorySerializer
from .age_utils import age_years_months as _age_years_months

logger = logging.getLogger(__name__)


class BirthHistoryView(APIView):
    """
    GET    — any hospital staff can view.
    POST   — create (front desk at registration, or doctor at consultation
             if not already captured).
    PATCH  — edit the existing record (doctor correcting/completing it
             later is the main case, but front desk can too — see the
             "Both" build decision on where Birth History is captured).
    """
    def get_permissions(self):
        if self.request.method == "GET":
            return [IsHospitalStaff()]
        return [IsDoctorOrFrontDesk()]

    def get(self, request, pk):
        try:
            patient = Patient.objects.using(request.tenant_db).get(pk=pk)
        except Patient.DoesNotExist:
            return not_found("Patient not found.")
        bh = BirthHistory.objects.using(request.tenant_db).filter(patient=patient).first()
        if not bh:
            return success(data=None, message="No birth history recorded yet.")
        return success(data=BirthHistorySerializer(bh).data)

    def post(self, request, pk):
        try:
            patient = Patient.objects.using(request.tenant_db).get(pk=pk)
        except Patient.DoesNotExist:
            return not_found("Patient not found.")
        if BirthHistory.objects.using(request.tenant_db).filter(patient=patient).exists():
            return error(
                "Birth history already exists for this patient — use PATCH to edit it.",
                status=400,
            )
        serializer = BirthHistorySerializer(data=request.data)
        if not serializer.is_valid():
            return error(message="Validation error.", errors=serializer.errors)
        bh = BirthHistory.objects.using(request.tenant_db).create(
            patient=patient,
            recorded_by=request.user.id,
            **serializer.validated_data,
        )
        return created(data=BirthHistorySerializer(bh).data, message="Birth history recorded.")

    def patch(self, request, pk):
        try:
            patient = Patient.objects.using(request.tenant_db).get(pk=pk)
        except Patient.DoesNotExist:
            return not_found("Patient not found.")
        bh = BirthHistory.objects.using(request.tenant_db).filter(patient=patient).first()
        if not bh:
            return not_found("No birth history recorded yet for this patient — use POST to create it.")
        serializer = BirthHistorySerializer(bh, data=request.data, partial=True)
        if not serializer.is_valid():
            return error(message="Validation error.", errors=serializer.errors)
        serializer.save(updated_by=request.user.id)
        return success(data=BirthHistorySerializer(bh).data, message="Birth history updated.")


class PatientMilestoneListCreateView(APIView):
    """
    GET  /api/v1/patients/<pk>/milestones/  — roadmap (schedule + real records)
    POST /api/v1/patients/<pk>/milestones/  — record a milestone assessment
         Body: { domain, milestone, scheduled_label?, status ("achieved" |
                 "not_yet" | "concern"), achieved_date?, assessed_date?, notes? }
    """
    permission_classes = [IsDoctorOrNurse]

    def get(self, request, pk):
        from apps.registry.milestone_roadmap import build_roadmap
        from apps.registry.models import MilestoneSchedule, MilestoneScheduleRule
        from apps.tenants.models import Tenant

        try:
            patient = Patient.objects.using(request.tenant_db).get(pk=pk)
        except Patient.DoesNotExist:
            return not_found("Patient not found.")

        rules = []
        tenant = Tenant.objects.using("default").filter(pk=request.tenant_id).first()
        schedule_id = tenant.active_milestone_schedule_id if tenant else None
        schedule = None
        if schedule_id:
            schedule = MilestoneSchedule.objects.using("default").filter(pk=schedule_id, active=True).first()
        if not schedule:
            schedule = (
                MilestoneSchedule.objects.using("default")
                .filter(owner_tenant_id__isnull=True, is_template=True, active=True)
                .order_by("id")
                .first()
            )
        if schedule:
            rules = list(
                MilestoneScheduleRule.objects.using("default")
                .filter(schedule=schedule)
                .order_by("sort_order")
            )

        roadmap = build_roadmap(
            patient.awpid, patient.date_of_birth, rules,
            viewer_tenant_id=request.tenant_id, hie_consent=patient.hie_consent_given,
        )
        return success(data={
            "patient_name": patient.full_name,
            "date_of_birth": patient.date_of_birth,
            "consent_given": patient.hie_consent_given,
            "roadmap": roadmap,
        })

    def post(self, request, pk):
        from apps.registry.models import SharedMilestoneRecord

        try:
            patient = Patient.objects.using(request.tenant_db).get(pk=pk)
        except Patient.DoesNotExist:
            return not_found("Patient not found.")

        d = request.data
        domain = (d.get("domain") or "").strip()
        milestone = (d.get("milestone") or "").strip()
        status_val = (d.get("status") or SharedMilestoneRecord.STATUS_ACHIEVED).strip()
        scheduled_label = (d.get("scheduled_label") or "").strip()
        notes = (d.get("notes") or "").strip()

        if not domain or domain not in dict(SharedMilestoneRecord._meta.get_field("domain").choices):
            return error("A valid domain is required.", errors={"domain": "Required/invalid."})
        if not milestone:
            return error("Milestone is required.", errors={"milestone": "Required."})
        if status_val not in dict(SharedMilestoneRecord.STATUS_CHOICES):
            return error("Invalid status.", errors={"status": "Invalid."})

        achieved_date = d.get("achieved_date") or (date.today().isoformat() if status_val == SharedMilestoneRecord.STATUS_ACHIEVED else None)
        assessed_date = d.get("assessed_date") or date.today().isoformat()

        staff_name = getattr(request.user, "full_name", None) or getattr(request.user, "email", "Staff")
        record = SharedMilestoneRecord.objects.using("default").create(
            awpid=patient.awpid,
            domain=domain,
            milestone=milestone,
            scheduled_label=scheduled_label,
            status=status_val,
            achieved_date=achieved_date if status_val == SharedMilestoneRecord.STATUS_ACHIEVED else None,
            assessed_date=assessed_date,
            notes=notes,
            recorded_by_name=staff_name,
            source_tenant_id=request.tenant_id,
        )
        return created(data={
            "id": record.id,
            "domain": record.domain,
            "milestone": record.milestone,
            "status": record.status,
            "achieved_date": str(record.achieved_date) if record.achieved_date else None,
            "assessed_date": str(record.assessed_date) if record.assessed_date else None,
        }, message="Milestone assessment recorded.")
