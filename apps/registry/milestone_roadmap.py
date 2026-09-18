"""
apps/registry/milestone_roadmap.py
-------------------------------------
Builds a child's developmental-milestone roadmap by merging their real
SharedMilestoneRecord rows against a configurable schedule (a
MilestoneSchedule's ordered MilestoneScheduleRule rows) — structural mirror
of apps.registry.vaccine_schedule.build_roadmap()/summarize_roadmap(); see
that module's docstring for the fuller rationale behind the
matched/unmatched-slot merge approach and the status/timing split.

Status semantics (simpler than vaccinations — no certificate-review
workflow here, so there's no "pending_review"/"rejected"):
  - A roadmap slot with a matching SharedMilestoneRecord shows that record's
    real status: "achieved" / "not_yet" / "concern".
  - A roadmap slot with NO matching record is "unassessed" — never inferred
    as a missed or delayed milestone from silence alone, same reasoning as
    vaccine_schedule's "unknown" status.
  - `timing` ("upcoming" / "due_now" / "past_window") is the same
    informational planning metadata as vaccine_schedule, computed from the
    child's age vs. the rule's [min_age_days, max_age_days] window.
"""

from datetime import date

_DUE_LEAD_DAYS = 14
_PAST_WINDOW_GRACE_DAYS = 90


def _rule_get(rule, key):
    if isinstance(rule, dict):
        return rule.get(key)
    return getattr(rule, key, None)


def _serialize_matched(rule, record):
    return {
        "domain": record.domain,
        "milestone": record.milestone,
        "scheduled_label": _rule_get(rule, "scheduled_label") if rule else record.scheduled_label,
        "achieved_date": str(record.achieved_date) if record.achieved_date else None,
        "assessed_date": str(record.assessed_date) if record.assessed_date else None,
        "status": record.status,
        "timing": None,  # not applicable — a real record already resolved this slot
        "notes": record.notes,
        "record_id": record.id,
        "recorded_by_name": record.recorded_by_name,
        "extra": rule is None,
    }


def build_roadmap(awpid, date_of_birth, rules, *, viewer_tenant_id=None, hie_consent=True):
    """
    Merges a child's real SharedMilestoneRecord rows with a schedule's rules
    into one ordered list. `rules` — a queryset/list of
    MilestoneScheduleRule instances (or dicts with the same keys: domain,
    milestone, scheduled_label, min_age_days, max_age_days), already ordered
    (MilestoneScheduleRule.Meta orders by sort_order).

    `hie_consent` — mirrors vaccine_schedule.build_roadmap(): when False,
    records logged at a hospital other than viewer_tenant_id are excluded
    (a milestone record has no "pending_review" exemption to carry over,
    since there is no cross-hospital review workflow for these).
    """
    from .models import SharedMilestoneRecord

    rules = list(rules)

    records_qs = SharedMilestoneRecord.objects.using("default").filter(awpid=awpid)
    if not hie_consent:
        from django.db.models import Q
        records_qs = records_qs.filter(
            Q(source_tenant_id__isnull=True) | Q(source_tenant_id=viewer_tenant_id)
        )
    records = list(records_qs.order_by("assessed_date"))
    matched_ids = set()
    today = date.today()
    age_days = (today - date_of_birth).days if date_of_birth else None

    roadmap = []
    for rule in rules:
        label = _rule_get(rule, "scheduled_label")
        domain = _rule_get(rule, "domain")
        milestone = _rule_get(rule, "milestone")
        min_age_days = _rule_get(rule, "min_age_days")
        max_age_days = _rule_get(rule, "max_age_days")

        rec = next(
            (r for r in records
             if r.id not in matched_ids
             and r.scheduled_label == label
             and r.domain == domain
             and r.milestone.strip().lower() == (milestone or "").strip().lower()),
            None,
        )
        if rec:
            matched_ids.add(rec.id)
            roadmap.append(_serialize_matched(rule, rec))
            continue

        timing = None
        if age_days is not None and min_age_days is not None:
            due_from = min_age_days - _DUE_LEAD_DAYS
            past_window_from = (
                max_age_days if max_age_days is not None
                else min_age_days + _PAST_WINDOW_GRACE_DAYS
            )
            if age_days < due_from:
                timing = "upcoming"
            elif age_days >= past_window_from:
                timing = "past_window"
            else:
                timing = "due_now"

        roadmap.append({
            "domain": domain,
            "milestone": milestone,
            "scheduled_label": label,
            "achieved_date": None,
            "assessed_date": None,
            "status": "unassessed",
            "timing": timing,
            "notes": "",
            "record_id": None,
            "recorded_by_name": None,
            "extra": False,
        })

    for r in records:
        if r.id not in matched_ids:
            roadmap.append(_serialize_matched(None, r))

    return roadmap


def summarize_roadmap(roadmap):
    """
    Aggregate view mirroring vaccine_schedule.summarize_roadmap(): completion
    count against the real schedule slots (excludes extra=True), the next
    recommended (due_now, unassessed) item, and a bucketed stats dict for a
    "N/M achieved" style summary.
    """
    schedule_items = [item for item in roadmap if not item.get("extra")]
    total_count = len(schedule_items)
    achieved_count = sum(1 for item in schedule_items if item["status"] == "achieved")

    next_recommended = next(
        (item for item in schedule_items if item["status"] == "unassessed" and item.get("timing") == "due_now"),
        None,
    )

    stats = {
        "achieved": achieved_count,
        "upcoming": sum(
            1 for item in schedule_items
            if item["status"] == "unassessed" and item.get("timing") == "upcoming"
        ),
        "needs_review": sum(
            1 for item in schedule_items
            if item["status"] == "concern"
            or (item["status"] == "unassessed" and item.get("timing") in ("due_now", "past_window"))
        ),
        "not_yet": sum(1 for item in schedule_items if item["status"] == "not_yet"),
    }

    return {
        "achieved_count": achieved_count,
        "total_count": total_count,
        "next_recommended": next_recommended,
        "stats": stats,
    }
