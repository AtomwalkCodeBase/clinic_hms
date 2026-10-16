"""Vaccination and milestone roadmaps (a child's real records laid over a schedule's rules) and schedules as the API returns them."""

from datetime import date

from apps.documents.models import Schedule


# slack before "upcoming" flips to "due_now", so a slightly early visit does not look due yet
DUE_LEAD_DAYS = 14
# for a rule with no max_age_days: how long after min_age_days "due_now" lasts before it becomes "past_window"
PAST_WINDOW_GRACE_DAYS = 90
def rule_get(rule, key):
    """A rule may be a model instance or a plain dict."""
    if isinstance(rule, dict):
        return rule.get(key)
    return getattr(rule, "item" if key in ("vaccine_name", "milestone") else key, None)
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
    """One entry per rule, in rule order, then the records that matched no rule (extra=True)."""
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
def default_schedule(noun):
    return (Schedule.objects.using("default")
            .filter(kind=noun, owner_hospital_id__isnull=True, is_template=True, active=True).order_by("id").first())


def active_schedule(noun, hospital_id=None):
    """A hospital's active schedule is its own schedule that is switched on (the latest one if several are); with none, or"""
    if hospital_id:
        own = (Schedule.objects.using("default").filter(kind=noun, owner_hospital_id=hospital_id, active=True)
               .order_by("-updated_at", "-id").first())
        if own:
            return own
    return default_schedule(noun)


def schedule_usage(noun):
    """{schedule id: number of hospitals whose active schedule it is}."""
    from apps.hospital_master.models import Hospital

    usage = {}
    for hospital_id in Hospital.objects.using("default").values_list("id", flat=True):
        schedule = active_schedule(noun, hospital_id)
        if schedule:
            usage[schedule.id] = usage.get(schedule.id, 0) + 1
    return usage


def rules_for(noun, hospital_id=None):
    """The rules to build a roadmap from, in display order: `noun` is "vaccination" or "milestone"."""
    schedule = active_schedule(noun, hospital_id)
    return list(schedule.s_rules.order_by("sort_order")) if schedule else []


def _serialize_matched(rule, record):
    status = "completed" if record.verification_status == record.STATUS_VERIFIED else record.verification_status
    return {
        "vaccine_name": record.vaccine_name,
        "scheduled_label": rule_get(rule, "scheduled_label") if rule else record.scheduled_label,
        "administered_date": str(record.administered_date) if record.administered_date else None,
        "due_date": str(record.due_date) if record.due_date else None,
        "reason": record.remarks,
        "dose_number": record.dose_number,
        "status": status,
        "timing": None,                       # a real record already settled this slot
        "source": record.source,
        "verification_status": record.verification_status,
        "record_id": record.id,
        "has_certificate": record.document_id is not None,
        "recorded_by": recorded_by(record),    # "staff" or "patient" (a parent's upload)
        "verified_by_name": "",
        "extra": rule is None,                # a record that fits no slot of the schedule
    }
def build_roadmap(awpid, date_of_birth, rules, *, viewer_hospital_id=None, hie_consent=True):
    """`rules`: a queryset or list of VaccinationScheduleRule (or dicts with vaccine_name, scheduled_label, min_age_days,"""
    from apps.documents.models import ImmunizationRecord

    records = ImmunizationRecord.objects.using("default").filter(patient__awpid=awpid)
    if not hie_consent:
        from django.db.models import Q
        records = records.filter(Q(source_hospital_id__isnull=True) | Q(source_hospital_id=viewer_hospital_id)
                                 | Q(verification_status=ImmunizationRecord.STATUS_PENDING))

    def open_slot(rule, timing):
        return {
            "vaccine_name": rule_get(rule, "vaccine_name"), "scheduled_label": rule_get(rule, "scheduled_label"),
            "administered_date": None, "due_date": None, "reason": "", "dose_number": None,
            "status": "unknown", "timing": timing, "source": None, "verification_status": None,
            "record_id": None, "has_certificate": False, "recorded_by": None, "verified_by_name": None, "extra": False,
        }

    return merge(
        list(rules), list(records.order_by("administered_date")), date_of_birth=date_of_birth,
        same_slot=lambda rule, r: (r.scheduled_label == rule_get(rule, "scheduled_label")
                                   and same_name(r.vaccine_name, rule_get(rule, "vaccine_name"))),
        matched=_serialize_matched, open_slot=open_slot)
def summarize_roadmap(roadmap):
    """Counts for "N of M completed". Only the schedule's own slots count (not `extra` records)."""
    slots = [item for item in roadmap if not item.get("extra")]
    unknown = [i for i in slots if i["status"] == "unknown"]
    completed = sum(1 for i in slots if i["status"] == "completed")
    return {
        "completed_count": completed,
        "total_count": len(slots),
        "next_recommended": next((i for i in unknown if i.get("timing") == "due_now"), None),
        "stats": {
            "completed": completed,
            "upcoming": sum(1 for i in unknown if i.get("timing") == "upcoming"),
            "needs_review": sum(1 for i in slots if i["status"] == "pending_review")
                            + sum(1 for i in unknown if i.get("timing") in ("due_now", "past_window")),
            "outside": sum(1 for i in roadmap if i.get("source") not in (None, "clinic")),
        },
    }


def recorded_by(record):
    return "patient" if record.source == record.SOURCE_SELF_REPORTED else "staff"


def _milestone_roadmap_serialize_matched(rule, record):
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
def milestone_roadmap_build_roadmap(awpid, date_of_birth, rules, *, viewer_hospital_id=None, hie_consent=True):
    """The child's real MilestoneRecord rows laid over a schedule's rules (see roadmap.py). `rules` is a queryset or"""
    from apps.documents.models import MilestoneRecord

    records = MilestoneRecord.objects.using("default").filter(patient__awpid=awpid)
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
        matched=_milestone_roadmap_serialize_matched, open_slot=open_slot)
def milestone_roadmap_summarize_roadmap(roadmap):
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


def vaccination_rule_dict(rule):
    return {
        "id": rule.id,
        "vaccine_name": rule_get(rule, "vaccine_name"),
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
        "milestone": rule_get(rule, "milestone"),
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
        "owner_hospital_id": schedule.owner_hospital_id,
        "is_active_for_this_hospital": active_id is not None and schedule.id == active_id,
        "rule_count": rule_count if rule_count is not None else schedule.s_rules.count(),
    }
def template_dict(schedule, rule_count=None, hospitals_using=None):
    return {
        "id": schedule.id,
        "name": schedule.name,
        "description": schedule.description,
        "active": schedule.active,
        "created_at": schedule.created_at.isoformat(),
        "updated_at": schedule.updated_at.isoformat(),
        "rule_count": rule_count if rule_count is not None else schedule.s_rules.count(),
        "hospitals_using": hospitals_using,
    }
