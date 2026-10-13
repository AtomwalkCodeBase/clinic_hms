"""
apps/patients/pediatrics/roadmap.py
-----------------------------------
What the vaccination roadmap (vaccine_schedule.py) and the milestone roadmap (milestone_roadmap.py) share: lay a
schedule's rules over a child's real records, one slot per rule, then any records that fit no rule.

A slot with a matching record shows that record's real status. A slot with NO record is never called "overdue" or
"missed" (silence is not evidence, and it may have been done elsewhere); it only gets an informational `timing`
from the child's age against the rule's [min_age_days, max_age_days] window:
  "upcoming"    the window has not opened yet
  "due_now"     the window is open (or opens within DUE_LEAD_DAYS)
  "past_window" it closed long ago, so "recommended now" would mislead; the UI says "no record on file" instead
"""
from datetime import date

# slack before "upcoming" flips to "due_now", so a slightly early visit does not look due yet
DUE_LEAD_DAYS = 14
# for a rule with no max_age_days: how long after min_age_days "due_now" lasts before it becomes "past_window"
PAST_WINDOW_GRACE_DAYS = 90


def rule_get(rule, key):
    """A rule may be a model instance or a plain dict."""
    return rule.get(key) if isinstance(rule, dict) else getattr(rule, key, None)


def timing_for(age_days, min_age_days, max_age_days):
    if age_days is None or min_age_days is None:
        return None
    if age_days < min_age_days - DUE_LEAD_DAYS:
        return "upcoming"
    past_from = max_age_days if max_age_days is not None else min_age_days + PAST_WINDOW_GRACE_DAYS
    return "past_window" if age_days >= past_from else "due_now"


def same_name(a, b):
    return (a or "").strip().lower() == (b or "").strip().lower()


def merge(rules, records, *, date_of_birth, same_slot, matched, open_slot):
    """
    One entry per rule, in rule order, then the records that matched no rule (extra=True).
      same_slot(rule, record) -> bool   does this record fill this slot (each record fills at most one)
      matched(rule_or_None, record)     the entry for a slot with a record (rule is None for an extra record)
      open_slot(rule, timing)           the entry for a slot with no record
    """
    age_days = (date.today() - date_of_birth).days if date_of_birth else None
    used, roadmap = set(), []
    for rule in rules:
        record = next((r for r in records if r.id not in used and same_slot(rule, r)), None)
        if record:
            used.add(record.id)
            roadmap.append(matched(rule, record))
        else:
            timing = timing_for(age_days, rule_get(rule, "min_age_days"), rule_get(rule, "max_age_days"))
            roadmap.append(open_slot(rule, timing))
    roadmap += [matched(None, r) for r in records if r.id not in used]
    return roadmap


def rules_for(noun, tenant_id=None):
    """
    The rules to build a roadmap from, in display order: `noun` is "vaccination" or "milestone". A hospital's staff pass
    their tenant_id and get that hospital's active schedule; with no tenant_id (the patient portal, which spans
    hospitals) or when the hospital has none set, the system "Default Schedule" template is used.
    """
    from apps.registry import models
    from apps.tenants.models import Tenant

    Schedule = getattr(models, f"{noun.title()}Schedule")
    schedule = None
    if tenant_id:
        tenant = Tenant.objects.using("default").filter(pk=tenant_id).first()
        schedule_id = getattr(tenant, f"active_{noun}_schedule_id", None)
        schedule = Schedule.objects.using("default").filter(pk=schedule_id, active=True).first() if schedule_id else None
    if not schedule:
        schedule = (Schedule.objects.using("default")
                    .filter(owner_tenant_id__isnull=True, is_template=True, active=True).order_by("id").first())
    return list(schedule.rules.order_by("sort_order")) if schedule else []
