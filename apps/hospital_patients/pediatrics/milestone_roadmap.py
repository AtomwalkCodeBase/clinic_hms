"""
apps/hospital_patients/pediatrics/milestone_roadmap.py
---------------------------------------------
A child's developmental-milestone roadmap: a hospital's schedule (MilestoneScheduleRule rows) laid over the child's real
MilestoneRecord assessments. Same shape as vaccine_schedule.py (see roadmap.py).

A slot's `status` is the assessment's own ("achieved", "not_yet", "concern"), or "unassessed" when there is none,
never "delayed": silence is not evidence.
"""

from .roadmap import merge, rule_get, same_name


def _serialize_matched(rule, record):
    return {
        "domain": record.domain,
        "milestone": record.milestone,
        "scheduled_label": rule_get(rule, "scheduled_label") if rule else record.scheduled_label,
        "achieved_date": str(record.achieved_date) if record.achieved_date else None,
        "assessed_date": str(record.assessed_date) if record.assessed_date else None,
        "status": record.status,
        "timing": None,                      # a real assessment already settled this slot
        "notes": record.notes,
        "record_id": record.id,
        "recorded_by_name": record.recorded_by_name,
        "extra": rule is None,
    }


def build_roadmap(awpid, date_of_birth, rules, *, viewer_hospital_id=None, hie_consent=True):
    """
    The child's real MilestoneRecord rows laid over a schedule's rules (see roadmap.py). `rules` is a queryset or
    list of MilestoneScheduleRule (or dicts with domain, milestone, scheduled_label, min_age_days, max_age_days),
    already in display order. `hie_consent=False` drops records logged at a hospital other than viewer_hospital_id;
    there is no cross-hospital review step for milestones, so nothing is exempt.
    """
    from apps.atomwalk.models import MilestoneRecord

    records = MilestoneRecord.objects.using("default").filter(awpid=awpid)
    if not hie_consent:
        from django.db.models import Q
        records = records.filter(Q(source_hospital_id__isnull=True) | Q(source_hospital_id=viewer_hospital_id))

    def open_slot(rule, timing):
        return {
            "domain": rule_get(rule, "domain"), "milestone": rule_get(rule, "milestone"),
            "scheduled_label": rule_get(rule, "scheduled_label"), "achieved_date": None, "assessed_date": None,
            "status": "unassessed", "timing": timing, "notes": "", "record_id": None, "recorded_by_name": None,
            "extra": False,
        }

    return merge(
        list(rules), list(records.order_by("assessed_date")), date_of_birth=date_of_birth,
        same_slot=lambda rule, r: (r.scheduled_label == rule_get(rule, "scheduled_label")
                                   and r.domain == rule_get(rule, "domain")
                                   and same_name(r.milestone, rule_get(rule, "milestone"))),
        matched=_serialize_matched, open_slot=open_slot)


def summarize_roadmap(roadmap):
    """Counts for "N of M achieved": only the schedule's own slots count (not `extra` assessments)."""
    slots = [item for item in roadmap if not item.get("extra")]
    unassessed = [i for i in slots if i["status"] == "unassessed"]
    achieved = sum(1 for i in slots if i["status"] == "achieved")
    return {
        "achieved_count": achieved,
        "total_count": len(slots),
        "next_recommended": next((i for i in unassessed if i.get("timing") == "due_now"), None),
        "stats": {
            "achieved": achieved,
            "upcoming": sum(1 for i in unassessed if i.get("timing") == "upcoming"),
            "needs_review": sum(1 for i in slots if i["status"] == "concern")
                            + sum(1 for i in unassessed if i.get("timing") in ("due_now", "past_window")),
            "not_yet": sum(1 for i in slots if i["status"] == "not_yet"),
        },
    }
