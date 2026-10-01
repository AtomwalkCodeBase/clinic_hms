"""
apps/registry/schedule_dicts.py
-------------------------------
JSON shapes for vaccination / milestone schedules and rules, shared by the hospital-admin views
(apps/org/{vaccination,milestone}_schedule_views.py) and the platform-admin template views
(apps/platform_admin/{vaccination,milestone}_template_views.py), which each carried identical copies.
"""


def vaccination_rule_dict(rule):
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


def milestone_rule_dict(rule):
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


def schedule_dict(schedule, active_id=None, rule_count=None):
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


def template_dict(schedule, rule_count=None, tenants_using=None):
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
