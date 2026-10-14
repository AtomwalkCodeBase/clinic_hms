"""
apps/hospital_patients/pediatrics/vaccine_schedule.py
--------------------------------------------
A child's vaccination roadmap: a hospital's schedule (VaccinationScheduleRule rows) laid over the child's real
ImmunizationRecord records. See roadmap.py for how slots are matched and what `timing` means.

A slot's `status`:
  record exists  "completed" (verified), "pending_review" (a parent's upload), "rejected", "ordered" (doctor asked for
                 it, not given yet) or "declined" (doctor says not needed): the record's own verification_status
  no record      "unknown", never "overdue": silence is not evidence, the dose may have been given elsewhere
"""
from .roadmap import merge, rule_get, same_name


def _serialize_matched(rule, record):
    status = "completed" if record.verification_status == record.STATUS_VERIFIED else record.verification_status
    return {
        "vaccine_name": record.vaccine_name,
        "scheduled_label": rule_get(rule, "scheduled_label") if rule else record.scheduled_label,
        "administered_date": str(record.administered_date) if record.administered_date else None,
        "due_date": str(record.due_date) if record.due_date else None,
        "reason": record.reason,
        "dose_number": record.dose_number,
        "status": status,
        "timing": None,                       # a real record already settled this slot
        "source": record.source,
        "verification_status": record.verification_status,
        "record_id": record.id,
        "has_certificate": bool(record.file_data),
        "recorded_by": record.recorded_by,    # "staff" or "patient" (a parent's upload)
        "verified_by_name": record.verified_by_name,
        "extra": rule is None,                # a record that fits no slot of the schedule
    }


def build_roadmap(awpid, date_of_birth, rules, *, viewer_hospital_id=None, hie_consent=True):
    """
    `rules`: a queryset or list of VaccinationScheduleRule (or dicts with vaccine_name, scheduled_label, min_age_days,
    max_age_days), in display order; the caller picks the schedule (see rules_for in roadmap.py).

    `hie_consent=False` drops records from OTHER hospitals than viewer_hospital_id. Two kinds stay visible anyway:
    records never attributed to a hospital (source_hospital_id is None), and "pending_review" ones, because any
    hospital's staff must be able to review a parent's upload. Only the staff roadmap passes False; the patient
    portal never filters.
    """
    from apps.atomwalk.models import ImmunizationRecord

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
    """
    Counts for "N of M completed". Only the schedule's own slots count (not `extra` records).
    `next_recommended` is the first unknown slot that is due now.
    stats: completed; upcoming (unknown, window not open yet); needs_review (pending_review, or unknown and due now /
    past window: an open question for the parent or doctor); outside (records, extra or not, not given at a clinic).
    """
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
