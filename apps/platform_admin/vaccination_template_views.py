"""
apps/platform_admin/vaccination_template_views.py
----------------------------------------------------
Platform-admin CRUD for system-level vaccination schedule templates —
VaccinationSchedule rows with owner_tenant_id=None, is_template=True (see
apps.registry.models). These are the starting points every hospital admin
sees under "available templates" in
apps.org.vaccination_schedule_views.VaccinationScheduleListCreateView.get()
and can clone into their own editable schedule.

Matches the permission/response conventions of apps.platform_admin.views
(IsPlatformAdmin, core.response helpers) rather than introducing a new
style.

Endpoints:
  GET    /api/v1/platform/vaccination-templates/        — list every template
         (including inactive ones — platform admin needs full visibility,
         unlike the hospital-admin-facing list which only shows active=True).
  POST   /api/v1/platform/vaccination-templates/        — create a new
         template schedule, optionally with initial rules.
  GET    /api/v1/platform/vaccination-templates/<id>/   — template + rules.
  PATCH  /api/v1/platform/vaccination-templates/<id>/   — edit name/
         description/active + add/update/delete rules (same rules payload
         shape as apps.org.vaccination_schedule_views.VaccinationScheduleDetailView).
  DELETE /api/v1/platform/vaccination-templates/<id>/   — delete a template.
         Refused (400) if any Tenant currently has
         active_vaccination_schedule_id pointing at it — deleting would
         silently break that hospital's roadmap (active_vaccination_schedule_id
         is a plain IntegerField, not an FK, so there is no DB constraint to
         catch this; it must be checked here).
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
        "vaccine_name": rule.vaccine_name,
        "dose_number": rule.dose_number,
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


class VaccinationTemplateListCreateView(APIView):
    """
    GET  — every system template.
    POST — create one. Body: { name, description?, active?, rules?: [...] }
    """
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        from apps.registry.models import VaccinationSchedule
        from apps.tenants.models import Tenant

        templates = (
            VaccinationSchedule.objects.using("default")
            .filter(owner_tenant_id__isnull=True, is_template=True)
            .order_by("name")
        )
        usage_counts = {}
        for tid in Tenant.objects.using("default").exclude(
            active_vaccination_schedule_id__isnull=True
        ).values_list("active_vaccination_schedule_id", flat=True):
            usage_counts[tid] = usage_counts.get(tid, 0) + 1

        return success(data=[
            _template_dict(t, tenants_using=usage_counts.get(t.id, 0)) for t in templates
        ])

    def post(self, request):
        from apps.registry.models import VaccinationSchedule, VaccinationScheduleRule

        d = request.data
        name = (d.get("name") or "").strip()
        if not name:
            return error("Name is required.", errors={"name": "Required."})

        template = VaccinationSchedule.objects.using("default").create(
            name=name,
            description=(d.get("description") or "").strip(),
            owner_tenant_id=None,
            is_template=True,
            active=bool(d.get("active", True)),
        )

        rules_in = d.get("rules") or []
        created_rules = []
        if isinstance(rules_in, list):
            for i, rd in enumerate(rules_in):
                if not isinstance(rd, dict):
                    continue
                if not rd.get("vaccine_name") or not rd.get("scheduled_label") or rd.get("min_age_days") is None:
                    continue
                created_rules.append(VaccinationScheduleRule(
                    schedule=template,
                    vaccine_name=rd["vaccine_name"],
                    scheduled_label=rd["scheduled_label"],
                    min_age_days=rd["min_age_days"],
                    max_age_days=rd.get("max_age_days"),
                    dose_number=rd.get("dose_number", 1),
                    mandatory=rd.get("mandatory", True),
                    sort_order=rd.get("sort_order", i),
                ))
        if created_rules:
            VaccinationScheduleRule.objects.using("default").bulk_create(created_rules)

        return created(
            data=_template_dict(template, rule_count=len(created_rules), tenants_using=0),
            message="Vaccination schedule template created.",
        )


class VaccinationTemplateDetailView(APIView):
    """
    GET    — template + ordered rules.
    PATCH  — edit name/description/active + add/update/delete rules.
    DELETE — delete the template (blocked if any tenant's active schedule
             points at it).
    """
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def _get(self, pk):
        from apps.registry.models import VaccinationSchedule
        return VaccinationSchedule.objects.using("default").filter(
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
        from apps.registry.models import VaccinationScheduleRule

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

        rules_touched = 0
        if "rules" in d and isinstance(d["rules"], list):
            for rd in d["rules"]:
                if not isinstance(rd, dict):
                    continue
                rid = rd.get("id")

                if rid and rd.get("_delete"):
                    VaccinationScheduleRule.objects.using("default").filter(pk=rid, schedule=template).delete()
                    rules_touched += 1
                    continue

                if rid:
                    rule = VaccinationScheduleRule.objects.using("default").filter(pk=rid, schedule=template).first()
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
                        schedule=template,
                        vaccine_name=rd["vaccine_name"],
                        scheduled_label=rd["scheduled_label"],
                        min_age_days=rd["min_age_days"],
                        max_age_days=rd.get("max_age_days"),
                        dose_number=rd.get("dose_number", 1),
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

        in_use = Tenant.objects.using("default").filter(active_vaccination_schedule_id=template.id).count()
        if in_use:
            return error(
                f"{in_use} hospital(s) currently have this template set as their active schedule — "
                "it can't be deleted while in use. Deactivate it instead, or have those hospitals "
                "switch schedules first.",
                status=400,
            )

        template.delete(using="default")
        return success(message="Template deleted.")
