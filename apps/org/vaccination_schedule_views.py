"""
apps/org/vaccination_schedule_views.py
---------------------------------------
Hospital-admin config endpoints for VaccinationSchedule /
VaccinationScheduleRule (apps.registry.models) — the configurable roadmap a
hospital's PatientVaccinationListCreateView.get() and the patient portal
build against (see apps.registry.vaccine_schedule.build_roadmap()).

Both models live in the shared registry DB ("default" alias — see
core.db_router.REGISTRY_APPS), not the tenant DB, same as Tenant itself, so
every query here explicitly uses "default" (matching the existing style in
apps.patients.growth_vaccination_views).

Endpoints (all IsHospitalAdmin — same gate as apps.org.views' RolesPage
backend):
  GET   /api/v1/org/vaccination-schedules/          — this hospital's own
        schedules + every active system template (owner_tenant_id=None,
        is_template=True) available to clone from.
  POST  /api/v1/org/vaccination-schedules/          — clone a template
        {template_id, name?} into a new schedule owned by this tenant, and
        set it as Tenant.active_vaccination_schedule_id.
  GET   /api/v1/org/vaccination-schedules/<id>/     — schedule + ordered rules.
        Allowed for this tenant's own schedules AND system templates
        (read-only preview before cloning).
  PATCH /api/v1/org/vaccination-schedules/<id>/     — edit name/description/
        active + add/update/delete rules. Only for schedules owned by this
        tenant (owner_tenant_id == request.tenant_id) — system templates are
        never edited in place; clone one first.
  POST  /api/v1/org/vaccination-schedules/<id>/activate/ — point this
        tenant's active_vaccination_schedule_id at one of its own schedules,
        or directly at a system template (no clone/customization needed).
"""

import logging

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from core.permissions import IsHospitalAdmin
from core.response import success, created, error, not_found

logger = logging.getLogger(__name__)


def _rule_dict(rule):
    return {
        "id": rule.id,
        "vaccine_name": rule.vaccine_name,
        "dose_number": rule.dose_number,
        "scheduled_label": rule.scheduled_label,
        "min_age_days": rule.min_age_days,
        "max_age_days": rule.max_age_days,
        "mandatory": rule.mandatory,
        "sort_order": rule.sort_order,
    }


def _schedule_dict(schedule, active_id=None, rule_count=None):
    return {
        "id": schedule.id,
        "name": schedule.name,
        "description": schedule.description,
        "is_template": schedule.is_template,
        "active": schedule.active,
        "owner_tenant_id": schedule.owner_tenant_id,
        "is_active_for_this_hospital": active_id is not None and schedule.id == active_id,
        "rule_count": rule_count if rule_count is not None else schedule.rules.count(),
    }


class VaccinationScheduleListCreateView(APIView):
    """
    GET  — this hospital's own schedules + available system templates.
    POST — clone a template into a schedule owned by this hospital and
           activate it. Body: { "template_id": <id>, "name"?: str }
    """
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def get(self, request):
        from apps.registry.models import VaccinationSchedule
        from apps.tenants.models import Tenant

        tenant = Tenant.objects.using("default").filter(pk=request.tenant_id).first()
        active_id = tenant.active_vaccination_schedule_id if tenant else None

        own = VaccinationSchedule.objects.using("default").filter(owner_tenant_id=request.tenant_id).order_by("-created_at")
        templates = (
            VaccinationSchedule.objects.using("default")
            .filter(owner_tenant_id__isnull=True, is_template=True, active=True)
            .order_by("name")
        )

        return success(data={
            "own_schedules": [_schedule_dict(s, active_id) for s in own],
            "templates": [_schedule_dict(s, active_id) for s in templates],
            "active_schedule_id": active_id,
        })

    def post(self, request):
        from apps.registry.models import VaccinationSchedule, VaccinationScheduleRule
        from apps.tenants.models import Tenant

        template_id = request.data.get("template_id")
        if not template_id:
            return error("template_id is required.", errors={"template_id": "Required."})

        template = VaccinationSchedule.objects.using("default").filter(
            pk=template_id, owner_tenant_id__isnull=True, is_template=True,
        ).first()
        if not template:
            return not_found("Template schedule not found.")

        name = (request.data.get("name") or "").strip() or f"{template.name} (customized)"
        new_schedule = VaccinationSchedule.objects.using("default").create(
            name=name,
            description=template.description,
            owner_tenant_id=request.tenant_id,
            is_template=False,
            active=True,
        )

        template_rules = list(
            VaccinationScheduleRule.objects.using("default").filter(schedule=template).order_by("sort_order")
        )
        VaccinationScheduleRule.objects.using("default").bulk_create([
            VaccinationScheduleRule(
                schedule=new_schedule,
                vaccine_name=r.vaccine_name,
                dose_number=r.dose_number,
                scheduled_label=r.scheduled_label,
                min_age_days=r.min_age_days,
                max_age_days=r.max_age_days,
                mandatory=r.mandatory,
                sort_order=r.sort_order,
            )
            for r in template_rules
        ])

        tenant = Tenant.objects.using("default").filter(pk=request.tenant_id).first()
        if tenant:
            tenant.active_vaccination_schedule_id = new_schedule.id
            tenant.save(using="default", update_fields=["active_vaccination_schedule_id"])

        return created(
            data=_schedule_dict(new_schedule, new_schedule.id, len(template_rules)),
            message=f"Cloned '{template.name}' and set as this hospital's active schedule.",
        )


class VaccinationScheduleDetailView(APIView):
    """
    GET   — schedule + ordered rules. Own schedules or any system template
            (read-only preview).
    PATCH — edit name/description/active, and add/update/delete rules. Only
            for schedules this tenant owns.
            Body: { name?, description?, active?,
                     rules?: [ {id?, vaccine_name, scheduled_label,
                                min_age_days, max_age_days?, dose_number?,
                                mandatory?, sort_order?, _delete?}, ... ] }
            A rule entry with "id" updates (or, with "_delete": true,
            removes) that rule; one without "id" creates a new rule.
    """
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def _visible_schedule(self, request, pk):
        from apps.registry.models import VaccinationSchedule
        schedule = VaccinationSchedule.objects.using("default").filter(pk=pk).first()
        if not schedule:
            return None
        if schedule.owner_tenant_id is not None and schedule.owner_tenant_id != request.tenant_id:
            return None
        return schedule

    def get(self, request, pk):
        schedule = self._visible_schedule(request, pk)
        if not schedule:
            return not_found("Schedule not found.")
        rules = schedule.rules.all().order_by("sort_order")
        data = _schedule_dict(schedule, rule_count=len(rules))
        data["rules"] = [_rule_dict(r) for r in rules]
        return success(data=data)

    def patch(self, request, pk):
        from apps.registry.models import VaccinationSchedule, VaccinationScheduleRule

        schedule = VaccinationSchedule.objects.using("default").filter(
            pk=pk, owner_tenant_id=request.tenant_id,
        ).first()
        if not schedule:
            return not_found("Schedule not found, or not owned by this hospital — clone a template first.")

        d = request.data
        updated_fields = []
        if "name" in d and (d["name"] or "").strip():
            schedule.name = d["name"].strip()
            updated_fields.append("name")
        if "description" in d:
            schedule.description = d["description"] or ""
            updated_fields.append("description")
        if "active" in d:
            schedule.active = bool(d["active"])
            updated_fields.append("active")
        if updated_fields:
            schedule.save(using="default", update_fields=updated_fields)

        rules_touched = 0
        if "rules" in d and isinstance(d["rules"], list):
            for rd in d["rules"]:
                if not isinstance(rd, dict):
                    continue
                rid = rd.get("id")

                if rid and rd.get("_delete"):
                    VaccinationScheduleRule.objects.using("default").filter(pk=rid, schedule=schedule).delete()
                    rules_touched += 1
                    continue

                if rid:
                    rule = VaccinationScheduleRule.objects.using("default").filter(pk=rid, schedule=schedule).first()
                    if not rule:
                        continue
                    editable = ["vaccine_name", "scheduled_label", "min_age_days", "max_age_days",
                                "dose_number", "mandatory", "sort_order"]
                    changed = [f for f in editable if f in rd]
                    for f in changed:
                        setattr(rule, f, rd[f])
                    if changed:
                        rule.save(using="default", update_fields=changed)
                        rules_touched += 1
                else:
                    if not rd.get("vaccine_name") or not rd.get("scheduled_label") or rd.get("min_age_days") is None:
                        continue
                    VaccinationScheduleRule.objects.using("default").create(
                        schedule=schedule,
                        vaccine_name=rd["vaccine_name"],
                        scheduled_label=rd["scheduled_label"],
                        min_age_days=rd["min_age_days"],
                        max_age_days=rd.get("max_age_days"),
                        dose_number=rd.get("dose_number", 1),
                        mandatory=rd.get("mandatory", True),
                        sort_order=rd.get("sort_order", 0),
                    )
                    rules_touched += 1

        rules = schedule.rules.all().order_by("sort_order")
        data = _schedule_dict(schedule, rule_count=len(rules))
        data["rules"] = [_rule_dict(r) for r in rules]
        return success(data=data, message=f"Schedule updated ({rules_touched} rule change(s)).")


class VaccinationScheduleActivateView(APIView):
    """
    POST /api/v1/org/vaccination-schedules/<id>/activate/
    Sets this tenant's active_vaccination_schedule_id — either to one of its
    own schedules, or directly to a system template (skips the clone step
    for a hospital happy to use the template as-is; editing later still
    requires cloning it first, per VaccinationScheduleDetailView.patch).
    """
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def post(self, request, pk):
        from apps.registry.models import VaccinationSchedule
        from apps.tenants.models import Tenant

        schedule = VaccinationSchedule.objects.using("default").filter(pk=pk, active=True).first()
        if not schedule:
            return not_found("Schedule not found.")
        if schedule.owner_tenant_id is not None and schedule.owner_tenant_id != request.tenant_id:
            return error("You can only activate your own schedules or a system template.")

        tenant = Tenant.objects.using("default").filter(pk=request.tenant_id).first()
        if not tenant:
            return not_found("Tenant not found.")
        tenant.active_vaccination_schedule_id = schedule.id
        tenant.save(using="default", update_fields=["active_vaccination_schedule_id"])
        return success(
            data={"active_schedule_id": schedule.id},
            message=f"'{schedule.name}' is now this hospital's active vaccination schedule.",
        )
