"""
apps/platform_admin/milestone_template_views.py
----------------------------------------------------
Platform-admin CRUD for system-level developmental-milestone schedule
templates — MilestoneSchedule rows with owner_tenant_id=None, is_template=
True (see apps.registry.models). Exact structural mirror of
apps.platform_admin.vaccination_template_views — see that module's
docstring for the fuller rationale.

Endpoints:
  GET    /api/v1/platform/milestone-templates/        — list every template.
  POST   /api/v1/platform/milestone-templates/        — create a new
         template schedule, optionally with initial rules.
  GET    /api/v1/platform/milestone-templates/<id>/   — template + rules.
  PATCH  /api/v1/platform/milestone-templates/<id>/   — edit name/
         description/active + add/update/delete rules.
  DELETE /api/v1/platform/milestone-templates/<id>/   — delete a template.
         Refused (400) if any Tenant currently has
         active_milestone_schedule_id pointing at it.
"""

import logging

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from core.permissions import IsPlatformAdmin
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


def _template_dict(schedule, rule_count=None, tenants_using=None):
    return {
        "id": schedule.id,
        "name": schedule.name,
        "description": schedule.description,
        "active": schedule.active,
        "created_at": schedule.created_at.isoformat(),
        "updated_at": schedule.updated_at.isoformat(),
        "rule_count": rule_count if rule_count is not None else schedule.rules.count(),
        "tenants_using": tenants_using,
    }


class MilestoneTemplateListCreateView(APIView):
    """
    GET  — every system template.
    POST — create one. Body: { name, description?, active?, rules?: [...] }
    """
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        from apps.registry.models import MilestoneSchedule
        from apps.tenants.models import Tenant

        templates = (
            MilestoneSchedule.objects.using("default")
            .filter(owner_tenant_id__isnull=True, is_template=True)
            .order_by("name")
        )
        usage_counts = {}
        for tid in Tenant.objects.using("default").exclude(
            active_milestone_schedule_id__isnull=True
        ).values_list("active_milestone_schedule_id", flat=True):
            usage_counts[tid] = usage_counts.get(tid, 0) + 1

        return success(data=[
            _template_dict(t, tenants_using=usage_counts.get(t.id, 0)) for t in templates
        ])

    def post(self, request):
        from apps.registry.models import MilestoneSchedule, MilestoneScheduleRule

        d = request.data
        name = (d.get("name") or "").strip()
        if not name:
            return error("Name is required.", errors={"name": "Required."})

        template = MilestoneSchedule.objects.using("default").create(
            name=name,
            description=(d.get("description") or "").strip(),
            owner_tenant_id=None,
            is_template=True,
            active=bool(d.get("active", True)),
        )

        valid_domains = dict(MilestoneScheduleRule.DOMAIN_CHOICES)
        rules_in = d.get("rules") or []
        created_rules = []
        if isinstance(rules_in, list):
            for i, rd in enumerate(rules_in):
                if not isinstance(rd, dict):
                    continue
                if (not rd.get("domain") or rd.get("domain") not in valid_domains
                        or not rd.get("milestone") or not rd.get("scheduled_label")
                        or rd.get("min_age_days") is None):
                    continue
                created_rules.append(MilestoneScheduleRule(
                    schedule=template,
                    domain=rd["domain"],
                    milestone=rd["milestone"],
                    scheduled_label=rd["scheduled_label"],
                    min_age_days=rd["min_age_days"],
                    max_age_days=rd.get("max_age_days"),
                    mandatory=rd.get("mandatory", True),
                    sort_order=rd.get("sort_order", i),
                ))
        if created_rules:
            MilestoneScheduleRule.objects.using("default").bulk_create(created_rules)

        return created(
            data=_template_dict(template, rule_count=len(created_rules), tenants_using=0),
            message="Milestone schedule template created.",
        )


class MilestoneTemplateDetailView(APIView):
    """
    GET    — template + ordered rules.
    PATCH  — edit name/description/active + add/update/delete rules.
    DELETE — delete the template (blocked if any tenant's active schedule
             points at it).
    """
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def _get(self, pk):
        from apps.registry.models import MilestoneSchedule
        return MilestoneSchedule.objects.using("default").filter(
            pk=pk, owner_tenant_id__isnull=True, is_template=True,
        ).first()

    def get(self, request, pk):
        template = self._get(pk)
        if not template:
            return not_found("Template not found.")
        rules = template.rules.all().order_by("sort_order")
        data = _template_dict(template, rule_count=len(rules))
        data["rules"] = [_rule_dict(r) for r in rules]
        return success(data=data)

    def patch(self, request, pk):
        from apps.registry.models import MilestoneScheduleRule

        template = self._get(pk)
        if not template:
            return not_found("Template not found.")

        d = request.data
        updated_fields = []
        if "name" in d and (d["name"] or "").strip():
            template.name = d["name"].strip()
            updated_fields.append("name")
        if "description" in d:
            template.description = d["description"] or ""
            updated_fields.append("description")
        if "active" in d:
            template.active = bool(d["active"])
            updated_fields.append("active")
        if updated_fields:
            template.save(using="default", update_fields=updated_fields)

        valid_domains = dict(MilestoneScheduleRule.DOMAIN_CHOICES)
        rules_touched = 0
        if "rules" in d and isinstance(d["rules"], list):
            for rd in d["rules"]:
                if not isinstance(rd, dict):
                    continue
                rid = rd.get("id")

                if rid and rd.get("_delete"):
                    MilestoneScheduleRule.objects.using("default").filter(pk=rid, schedule=template).delete()
                    rules_touched += 1
                    continue

                if rid:
                    rule = MilestoneScheduleRule.objects.using("default").filter(pk=rid, schedule=template).first()
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
                        schedule=template,
                        domain=rd["domain"],
                        milestone=rd["milestone"],
                        scheduled_label=rd["scheduled_label"],
                        min_age_days=rd["min_age_days"],
                        max_age_days=rd.get("max_age_days"),
                        mandatory=rd.get("mandatory", True),
                        sort_order=rd.get("sort_order", 0),
                    )
                    rules_touched += 1

        rules = template.rules.all().order_by("sort_order")
        data = _template_dict(template, rule_count=len(rules))
        data["rules"] = [_rule_dict(r) for r in rules]
        return success(data=data, message=f"Template updated ({rules_touched} rule change(s)).")

    def delete(self, request, pk):
        from apps.tenants.models import Tenant

        template = self._get(pk)
        if not template:
            return not_found("Template not found.")

        in_use = Tenant.objects.using("default").filter(active_milestone_schedule_id=template.id).count()
        if in_use:
            return error(
                f"{in_use} hospital(s) currently have this template set as their active milestone schedule — "
                "it can't be deleted while in use. Deactivate it instead, or have those hospitals "
                "switch schedules first.",
                status=400,
            )

        template.delete(using="default")
        return success(message="Template deleted.")
