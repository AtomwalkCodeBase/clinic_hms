"""
apps/patients/pediatrics/schedule_views.py
------------------------------------------
Config endpoints for the vaccination and milestone schedules. The two kinds are the same thing (a named, ordered list of
rules, cloned from a system template into a hospital's own copy), so one set of views serves both; `_Kind` holds the few
differences (which tenant column points at the live schedule, which rule fields exist).

Hospital admin (IsHospitalAdmin), /api/v1/org/{vaccination,milestone}-schedules/
  GET    list     this hospital's own schedules + the active system templates to clone from
  POST   list     clone a template {template_id, name?} into this hospital's own schedule and make it the active one
  GET    <id>/    a schedule + its ordered rules (own schedule, or any template as a read-only preview)
  PATCH  <id>/    edit name / description / active and add / update / delete rules; only for the hospital's own schedule
  POST   <id>/activate/   make an own schedule, or a template as it is, the active one

Platform admin (IsPlatformAdmin), /api/v1/platform/{vaccination,milestone}-templates/
  GET / POST       list every template (inactive ones too) / create one with its rules
  GET / PATCH / DELETE  <id>/   a template + rules / edit it / delete it (refused while a hospital has it active)

A rule in a PATCH body: with "id" it updates that rule (or removes it with "_delete": true); without "id" it creates one.
Schedules live in the registry DB, hence the explicit "default" alias everywhere.
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from core.permissions import IsHospitalAdmin, IsPlatformAdmin
from core.response import success, created, error, not_found
from apps.patients.pediatrics.schedule_dicts import milestone_rule_dict, schedule_dict, template_dict, vaccination_rule_dict


class _InvalidRule(ValueError):
    """A rule in the request has a number that can't be right; the message says which."""


_NUMBERS = ("min_age_days", "max_age_days", "dose_number", "sort_order")


def _whole_number(value, key):
    """The value as a whole number of 0 or more, or _InvalidRule."""
    try:
        number = int(value) if not isinstance(value, bool) and float(value) == int(float(value)) else None
    except (TypeError, ValueError):
        number = None
    if number is None or number < 0:
        raise _InvalidRule(f"{key.replace('_', ' ').capitalize()} must be a whole number of 0 or more.")
    return number


def _checked_numbers(rd, current=None):
    """The numeric fields given in `rd` as whole numbers, checked against each other (the maximum age may not be below the
    minimum). `current` is the existing rule when editing, so a change to one age is checked against the other."""
    numbers = {k: _whole_number(rd[k], k) for k in _NUMBERS if rd.get(k) not in (None, "")}
    low = numbers.get("min_age_days", getattr(current, "min_age_days", None))
    high = numbers["max_age_days"] if "max_age_days" in numbers else (None if "max_age_days" in rd else getattr(current, "max_age_days", None))
    if low is not None and high is not None and high < low:
        raise _InvalidRule("The maximum age cannot be below the minimum age.")
    return numbers


class _Kind:
    def __init__(self, noun, tenant_column, name_key, extra_key, extra_default, rule_dict, template_message):
        self.noun, self.tenant_column, self.name_key = noun, tenant_column, name_key
        self.extra_key, self.extra_default = extra_key, extra_default   # dose_number (defaults to 1) / domain (required)
        self.rule_dict, self.template_message = rule_dict, template_message
        self.editable = [name_key, extra_key, "scheduled_label", "min_age_days", "max_age_days", "mandatory", "sort_order"]

    @property
    def Schedule(self):
        from apps.registry import models
        return getattr(models, f"{self.noun.title()}Schedule")

    @property
    def Rule(self):
        from apps.registry import models
        return getattr(models, f"{self.noun.title()}ScheduleRule")

    def new_rule(self, rd, default_sort):
        """The field values for a new rule from a request dict, or None when it is missing something required."""
        if not rd.get(self.name_key) or not rd.get("scheduled_label") or rd.get("min_age_days") is None:
            return None
        if self.extra_default is None and rd.get(self.extra_key) not in dict(self.Rule.DOMAIN_CHOICES):
            return None
        numbers = _checked_numbers(rd)
        return {
            self.name_key: rd[self.name_key], self.extra_key: numbers.get(self.extra_key, rd.get(self.extra_key, self.extra_default)),
            "scheduled_label": rd["scheduled_label"], "min_age_days": numbers["min_age_days"],
            "max_age_days": numbers.get("max_age_days"), "mandatory": rd.get("mandatory", True),
            "sort_order": numbers.get("sort_order", default_sort),
        }

    def rules_json(self, schedule):
        rules = schedule.rules.all().order_by("sort_order")
        return rules, [self.rule_dict(r) for r in rules]


VACCINATION = _Kind("vaccination", "active_vaccination_schedule_id", "vaccine_name", "dose_number", 1,
                    vaccination_rule_dict, "Vaccination schedule template created.")
MILESTONE = _Kind("milestone", "active_milestone_schedule_id", "milestone", "domain", None,
                  milestone_rule_dict, "Milestone schedule template created.")


def _edit(kind, schedule, d):
    """Apply a PATCH body to a schedule and its rules. Returns how many rule changes were made. Raises _InvalidRule, before
    anything is saved, when a rule's numbers are wrong."""
    rules_in = [rd for rd in (d["rules"] if isinstance(d.get("rules"), list) else []) if isinstance(rd, dict)]
    existing = {str(r.id): r for r in schedule.rules.all()}
    checked = {}
    for rd in rules_in:
        if rd.get("_delete"):
            continue
        current = existing.get(str(rd.get("id"))) if rd.get("id") else None
        if "min_age_days" in rd and rd["min_age_days"] in (None, ""):
            raise _InvalidRule("Minimum age is required.")
        checked[id(rd)] = _checked_numbers(rd, current) if (current or rd.get("min_age_days") is not None) else {}
        if not rd.get("id"):
            kind.new_rule(rd, 0)                                    # also checks the rest of a new rule

    changed = []
    if "name" in d and (d["name"] or "").strip():
        schedule.name = d["name"].strip()
        changed.append("name")
    if "description" in d:
        schedule.description = d["description"] or ""
        changed.append("description")
    if "active" in d:
        schedule.active = bool(d["active"])
        changed.append("active")
    if changed:
        schedule.save(using="default", update_fields=changed)

    touched = 0
    Rule = kind.Rule
    for rd in rules_in:
        rid = rd.get("id")
        if rid and rd.get("_delete"):
            Rule.objects.using("default").filter(pk=rid, schedule=schedule).delete()
            touched += 1
        elif rid:
            rule = Rule.objects.using("default").filter(pk=rid, schedule=schedule).first()
            fields = [f for f in kind.editable if f in rd] if rule else []
            for f in fields:
                setattr(rule, f, checked[id(rd)].get(f, None if rd[f] in (None, "") else rd[f]) if f in _NUMBERS else rd[f])
            if fields:
                rule.save(using="default", update_fields=fields)
                touched += 1
        else:
            values = kind.new_rule(rd, 0)
            if values:
                Rule.objects.using("default").create(schedule=schedule, **values)
                touched += 1
    return touched


def _set_active(request, kind, schedule):
    from apps.tenants.models import Tenant
    tenant = Tenant.objects.using("default").filter(pk=request.tenant_id).first()
    if tenant:
        setattr(tenant, kind.tenant_column, schedule.id)
        tenant.save(using="default", update_fields=[kind.tenant_column])
    return tenant


# ── hospital admin ────────────────────────────────────────────────────────────────────────────────────────────────
def hospital_views(kind):
    class ListCreate(APIView):
        permission_classes = [IsAuthenticated, IsHospitalAdmin]

        def get(self, request):
            from apps.tenants.models import Tenant
            tenant = Tenant.objects.using("default").filter(pk=request.tenant_id).first()
            active_id = getattr(tenant, kind.tenant_column) if tenant else None
            own = kind.Schedule.objects.using("default").filter(owner_tenant_id=request.tenant_id).order_by("-created_at")
            templates = (kind.Schedule.objects.using("default")
                         .filter(owner_tenant_id__isnull=True, is_template=True, active=True).order_by("name"))
            return success(data={
                "own_schedules": [schedule_dict(s, active_id) for s in own],
                "templates": [schedule_dict(s, active_id) for s in templates],
                "active_schedule_id": active_id,
            })

        def post(self, request):
            template_id = request.data.get("template_id")
            if not template_id:
                return error("template_id is required.", errors={"template_id": "Required."})
            template = kind.Schedule.objects.using("default").filter(
                pk=template_id, owner_tenant_id__isnull=True, is_template=True).first()
            if not template:
                return not_found("Template schedule not found.")

            name = (request.data.get("name") or "").strip() or f"{template.name} (customized)"
            clone = kind.Schedule.objects.using("default").create(
                name=name, description=template.description, owner_tenant_id=request.tenant_id,
                is_template=False, active=True)
            rules = list(kind.Rule.objects.using("default").filter(schedule=template).order_by("sort_order"))
            kind.Rule.objects.using("default").bulk_create([
                kind.Rule(schedule=clone, item=r.item, dose_number=r.dose_number, domain=r.domain,
                          scheduled_label=r.scheduled_label, min_age_days=r.min_age_days, max_age_days=r.max_age_days,
                          mandatory=r.mandatory, sort_order=r.sort_order)
                for r in rules])
            _set_active(request, kind, clone)
            label = "" if kind is VACCINATION else f"{kind.noun} "
            return created(data=schedule_dict(clone, clone.id, len(rules)),
                           message=f"Cloned '{template.name}' and set as this hospital's active {label}schedule.")

    class Detail(APIView):
        permission_classes = [IsAuthenticated, IsHospitalAdmin]

        def get(self, request, pk):
            schedule = kind.Schedule.objects.using("default").filter(pk=pk).first()
            if not schedule or schedule.owner_tenant_id not in (None, request.tenant_id):
                return not_found("Schedule not found.")
            rules, rules_json = kind.rules_json(schedule)
            return success(data={**schedule_dict(schedule, rule_count=len(rules)), "rules": rules_json})

        def patch(self, request, pk):
            schedule = kind.Schedule.objects.using("default").filter(pk=pk, owner_tenant_id=request.tenant_id).first()
            if not schedule:
                return not_found("Schedule not found, or not owned by this hospital — clone a template first.")
            try:
                touched = _edit(kind, schedule, request.data)
            except _InvalidRule as exc:
                return error(str(exc))
            rules, rules_json = kind.rules_json(schedule)
            return success(data={**schedule_dict(schedule, rule_count=len(rules)), "rules": rules_json},
                           message=f"Schedule updated ({touched} rule change(s)).")

    class Activate(APIView):
        """Make an own schedule, or a system template as it is (no clone), this hospital's active one."""
        permission_classes = [IsAuthenticated, IsHospitalAdmin]

        def post(self, request, pk):
            schedule = kind.Schedule.objects.using("default").filter(pk=pk, active=True).first()
            if not schedule:
                return not_found("Schedule not found.")
            if schedule.owner_tenant_id not in (None, request.tenant_id):
                return error("You can only activate your own schedules or a system template.")
            if not _set_active(request, kind, schedule):
                return not_found("Tenant not found.")
            return success(data={"active_schedule_id": schedule.id},
                           message=f"'{schedule.name}' is now this hospital's active {kind.noun} schedule.")

    return ListCreate, Detail, Activate


# ── platform admin ────────────────────────────────────────────────────────────────────────────────────────────────
def template_views(kind):
    def get_template(pk):
        return kind.Schedule.objects.using("default").filter(pk=pk, owner_tenant_id__isnull=True, is_template=True).first()

    class ListCreate(APIView):
        permission_classes = [IsAuthenticated, IsPlatformAdmin]

        def get(self, request):
            from apps.tenants.models import Tenant
            templates = (kind.Schedule.objects.using("default")
                         .filter(owner_tenant_id__isnull=True, is_template=True).order_by("name"))
            using = {}
            for schedule_id in (Tenant.objects.using("default").exclude(**{kind.tenant_column + "__isnull": True})
                                .values_list(kind.tenant_column, flat=True)):
                using[schedule_id] = using.get(schedule_id, 0) + 1
            return success(data=[template_dict(t, tenants_using=using.get(t.id, 0)) for t in templates])

        def post(self, request):
            d = request.data
            name = (d.get("name") or "").strip()
            if not name:
                return error("Name is required.", errors={"name": "Required."})
            rules_in = d.get("rules") if isinstance(d.get("rules"), list) else []
            try:
                checked = [kind.new_rule(rd, i) if isinstance(rd, dict) else None for i, rd in enumerate(rules_in)]
            except _InvalidRule as exc:
                return error(str(exc))
            template = kind.Schedule.objects.using("default").create(
                name=name, description=(d.get("description") or "").strip(), owner_tenant_id=None,
                is_template=True, active=bool(d.get("active", True)))
            rules = [kind.Rule(schedule=template, **values) for values in checked if values]
            if rules:
                kind.Rule.objects.using("default").bulk_create(rules)
            return created(data=template_dict(template, rule_count=len(rules), tenants_using=0),
                           message=kind.template_message)

    class Detail(APIView):
        permission_classes = [IsAuthenticated, IsPlatformAdmin]

        def get(self, request, pk):
            template = get_template(pk)
            if not template:
                return not_found("Template not found.")
            rules, rules_json = kind.rules_json(template)
            return success(data={**template_dict(template, rule_count=len(rules)), "rules": rules_json})

        def patch(self, request, pk):
            template = get_template(pk)
            if not template:
                return not_found("Template not found.")
            try:
                touched = _edit(kind, template, request.data)
            except _InvalidRule as exc:
                return error(str(exc))
            rules, rules_json = kind.rules_json(template)
            return success(data={**template_dict(template, rule_count=len(rules)), "rules": rules_json},
                           message=f"Template updated ({touched} rule change(s)).")

        def delete(self, request, pk):
            from apps.tenants.models import Tenant
            template = get_template(pk)
            if not template:
                return not_found("Template not found.")
            in_use = Tenant.objects.using("default").filter(**{kind.tenant_column: template.id}).count()
            if in_use:
                return error(
                    f"{in_use} hospital(s) currently have this template set as their active {kind.noun} schedule — "
                    "it can't be deleted while in use. Deactivate it instead, or have those hospitals "
                    "switch schedules first.", status=400)
            template.delete(using="default")
            return success(message="Template deleted.")

    return ListCreate, Detail


VaccinationScheduleListCreateView, VaccinationScheduleDetailView, VaccinationScheduleActivateView = hospital_views(VACCINATION)
MilestoneScheduleListCreateView, MilestoneScheduleDetailView, MilestoneScheduleActivateView = hospital_views(MILESTONE)
VaccinationTemplateListCreateView, VaccinationTemplateDetailView = template_views(VACCINATION)
MilestoneTemplateListCreateView, MilestoneTemplateDetailView = template_views(MILESTONE)
