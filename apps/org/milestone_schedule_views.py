"""
apps/org/milestone_schedule_views.py
--------------------------------------
Hospital-admin config endpoints for MilestoneSchedule / MilestoneScheduleRule
(apps.registry.models) — the configurable pediatric developmental-milestone
roadmap a hospital's PatientMilestoneListCreateView.get() builds against
(see apps.registry.milestone_roadmap.build_roadmap()).

Exact structural mirror of apps.org.vaccination_schedule_views — see that
module's docstring for the fuller rationale (registry-DB "default" alias,
clone-a-template pattern, why owner_tenant_id is a plain IntegerField).
This is the hospital-configurable milestone catalog the "Hospital-
configurable" build decision called for (as opposed to a fixed catalog).

Endpoints (all IsHospitalAdmin):
  GET   /api/v1/org/milestone-schedules/          — this hospital's own
        schedules + every active system template available to clone from.
  POST  /api/v1/org/milestone-schedules/          — clone a template
        {template_id, name?} into a schedule owned by this tenant, and set
        it as Tenant.active_milestone_schedule_id.
  GET   /api/v1/org/milestone-schedules/<id>/     — schedule + ordered rules.
  PATCH /api/v1/org/milestone-schedules/<id>/     — edit name/description/
        active + add/update/delete rules. Only for schedules owned by this
        tenant — system templates are never edited in place.
  POST  /api/v1/org/milestone-schedules/<id>/activate/ — point this
        tenant's active_milestone_schedule_id at one of its own schedules,
        or directly at a system template.
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
        "domain": rule.domain,
        "milestone": rule.milestone,
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


class MilestoneScheduleListCreateView(APIView):
    """
    GET  — this hospital's own schedules + available system templates.
    POST — clone a template into a schedule owned by this hospital and
           activate it. Body: { "template_id": <id>, "name"?: str }
    """
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def get(self, request):
        from apps.registry.models import MilestoneSchedule
        from apps.tenants.models import Tenant

        tenant = Tenant.objects.using("default").filter(pk=request.tenant_id).first()
        active_id = tenant.active_milestone_schedule_id if tenant else None

        own = MilestoneSchedule.objects.using("default").filter(owner_tenant_id=request.tenant_id).order_by("-created_at")
        templates = (
            MilestoneSchedule.objects.using("default")
            .filter(owner_tenant_id__isnull=True, is_template=True, active=True)
            .order_by("name")
        )

        return success(data={
            "own_schedules": [_schedule_dict(s, active_id) for s in own],
            "templates": [_schedule_dict(s, active_id) for s in templates],
            "active_schedule_id": active_id,
        })

    def post(self, request):
        from apps.registry.models import MilestoneSchedule, MilestoneScheduleRule
        from apps.tenants.models import Tenant

        template_id = request.data.get("template_id")
        if not template_id:
            return error("template_id is required.", errors={"template_id": "Required."})

        template = MilestoneSchedule.objects.using("default").filter(
            pk=template_id, owner_tenant_id__isnull=True, is_template=True,
        ).first()
        if not template:
            return not_found("Template schedule not found.")

        name = (request.data.get("name") or "").strip() or f"{template.name} (customized)"
        new_schedule = MilestoneSchedule.objects.using("default").create(
            name=name,
            description=template.description,
            owner_tenant_id=request.tenant_id,
            is_template=False,
            active=True,
        )

        template_rules = list(
            MilestoneScheduleRule.objects.using("default").filter(schedule=template).order_by("sort_order")
        )
        MilestoneScheduleRule.objects.using("default").bulk_create([
            MilestoneScheduleRule(
                schedule=new_schedule,
                domain=r.domain,
                milestone=r.milestone,
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
            tenant.active_milestone_schedule_id = new_schedule.id
            tenant.save(using="default", update_fields=["active_milestone_schedule_id"])

        return created(
            data=_schedule_dict(new_schedule, new_schedule.id, len(template_rules)),
            message=f"Cloned '{template.name}' and set as this hospital's active milestone schedule.",
        )


class MilestoneScheduleDetailView(APIView):
    """
    GET   — schedule + ordered rules. Own schedules or any system template
            (read-only preview).
    PATCH — edit name/description/active, and add/update/delete rules. Only
            for schedules this tenant owns.
            Body: { name?, description?, active?,
                     rules?: [ {id?, domain, milestone, scheduled_label,
                                min_age_days, max_age_days?, mandatory?,
                                sort_order?, _delete?}, ... ] }
    """
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def _visible_schedule(self, request, pk):
        from apps.registry.models import MilestoneSchedule
        schedule = MilestoneSchedule.objects.using("default").filter(pk=pk).first()
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
        from apps.registry.models import MilestoneSchedule, MilestoneScheduleRule

        schedule = MilestoneSchedule.objects.using("default").filter(
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

        valid_domains = dict(MilestoneScheduleRule.DOMAIN_CHOICES)
        rules_touched = 0
        if "rules" in d and isinstance(d["rules"], list):
            for rd in d["rules"]:
                if not isinstance(rd, dict):
                    continue
                rid = rd.get("id")

                if rid and rd.get("_delete"):
                    MilestoneScheduleRule.objects.using("default").filter(pk=rid, schedule=schedule).delete()
                    rules_touched += 1
                    continue

                if rid:
                    rule = MilestoneScheduleRule.objects.using("default").filter(pk=rid, schedule=schedule).first()
                    if not rule:
                        continue
                    editable = ["domain", "milestone", "scheduled_label", "min_age_days", "max_age_days",
                                "mandatory", "sort_order"]
                    changed = [f for f in editable if f in rd]
                    for f in changed:
                        setattr(rule, f, rd[f])
                    if changed:
                        rule.save(using="default", update_fields=changed)
                        rules_touched += 1
                else:
                    if (not rd.get("domain") or rd.get("domain") not in valid_domains
                            or not rd.get("milestone") or not rd.get("scheduled_label")
                            or rd.get("min_age_days") is None):
                        continue
                    MilestoneScheduleRule.objects.using("default").create(
                        schedule=schedule,
                        domain=rd["domain"],
                        milestone=rd["milestone"],
                        scheduled_label=rd["scheduled_label"],
                        min_age_days=rd["min_age_days"],
                        max_age_days=rd.get("max_age_days"),
                        mandatory=rd.get("mandatory", True),
                        sort_order=rd.get("sort_order", 0),
                    )
                    rules_touched += 1

        rules = schedule.rules.all().order_by("sort_order")
        data = _schedule_dict(schedule, rule_count=len(rules))
        data["rules"] = [_rule_dict(r) for r in rules]
        return success(data=data, message=f"Schedule updated ({rules_touched} rule change(s)).")


class MilestoneScheduleActivateView(APIView):
    """
    POST /api/v1/org/milestone-schedules/<id>/activate/
    Sets this tenant's active_milestone_schedule_id — either to one of its
    own schedules, or directly to a system template.
    """
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def post(self, request, pk):
        from apps.registry.models import MilestoneSchedule
        from apps.tenants.models import Tenant

        schedule = MilestoneSchedule.objects.using("default").filter(pk=pk, active=True).first()
        if not schedule:
            return not_found("Schedule not found.")
        if schedule.owner_tenant_id is not None and schedule.owner_tenant_id != request.tenant_id:
            return error("You can only activate your own schedules or a system template.")

        tenant = Tenant.objects.using("default").filter(pk=request.tenant_id).first()
        if not tenant:
            return not_found("Tenant not found.")
        tenant.active_milestone_schedule_id = schedule.id
        tenant.save(using="default", update_fields=["active_milestone_schedule_id"])
        return success(
            data={"active_schedule_id": schedule.id},
            message=f"'{schedule.name}' is now this hospital's active milestone schedule.",
        )
