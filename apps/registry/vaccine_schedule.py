"""
apps/registry/vaccine_schedule.py
----------------------------------
Builds a patient's vaccination roadmap by merging their real
SharedVaccination records against a *configurable* schedule (a
VaccinationSchedule's ordered VaccinationScheduleRule rows — see
apps/registry/models.py), instead of the single hardcoded list this file
used to define. Each hospital can now point at its own schedule
(Tenant.active_vaccination_schedule_id); the patient portal falls back to
a shared "Default Schedule" system template for cross-hospital views.

IMPORTANT — the DEFAULT_VACCINE_SCHEDULE list below is a simplified
reference schedule loosely modeled on India's National Immunization
Schedule, for demonstration purposes only. Before any of this is relied on
for real clinical guidance, it needs review and sign-off against the
actual schedule a hospital follows (the government NIS and the IAP
private-practice schedule diverge in places) — the label wording, the
exact ages, and the due-date windows should not be treated as medical
advice.

Status semantics (rewritten — this is the core UX fix this module made):
  - A roadmap slot with a matching SharedVaccination record is "completed"
    (verified) or "pending_review" (self-reported, not yet reviewed) or
    "rejected" (reviewed and rejected) or "ordered" (a doctor recorded an
    ad-hoc recommendation, not yet administered — see
    PatientVaccinationOrderView / PatientVaccinationAdministerView) or
    "declined" (a doctor marked it not clinically required for this patient
    — see PatientVaccinationDeclineView) — i.e. whatever the record's real
    verification_status tells us. "declined" is deliberately never
    "unknown" and never carries a "due_now" timing — it's a resolved slot,
    not an open question.
  - A roadmap slot with NO matching record is always "unknown" — never
    "overdue". The system has no record of the vaccine either way; it does
    not know whether it was given elsewhere, and inferring "overdue" from
    mere silence is misleading, especially for a brand-new patient with no
    recorded history at all.
  - A separate `timing` field ("upcoming" / "due_now" / "past_window") is
    still computed from the patient's age vs. the rule's
    [min_age_days, max_age_days] window, but it is informational/planning
    metadata layered on top of an "unknown" status — never a status verdict
    on its own. This is what lets the UI say "record unavailable,
    recommended now" instead of "overdue".
      "upcoming"     — the window hasn't opened yet.
      "due_now"      — the window is open (or opening within
                        _DUE_LEAD_DAYS) and still recent enough that
                        "recommended now" is an honest thing to tell the
                        patient.
      "past_window"  — the window opened long enough ago (past
                        max_age_days, or past min_age_days by more than
                        _PAST_WINDOW_GRACE_DAYS when a rule has no
                        max_age_days) that "recommended now" would be
                        misleading — e.g. telling a 5-year-old's parent
                        that a birth-window vaccine is "recommended now".
                        Still "unknown" status (no record either way), just
                        a different timing classification so the UI can
                        phrase it as "no record on file" instead of
                        implying it's freshly due.
"""

from datetime import date

# ── DEPRECATED / LEGACY ──────────────────────────────────────────────────
# No longer used as the live data source for build_roadmap() — kept here,
# unused, only because the data migration in
# apps/registry/migrations/0017_vaccinationschedule_vaccinationschedulerule.py
# already copied every one of these rows into the DB (as the "Default
# Schedule" VaccinationSchedule/VaccinationScheduleRule rows) and this
# constant is a convenient point-in-time record of exactly what was copied.
# Do not add new call sites reading this constant directly — resolve a
# schedule's rules from the DB (see build_roadmap()'s `rules` parameter)
# instead, so per-hospital customization actually takes effect.
#
# due_days = age in days at which the vaccine is recommended.
DEFAULT_VACCINE_SCHEDULE = [
    {"vaccine_name": "BCG",               "label": "Birth",       "due_days": 0},
    {"vaccine_name": "Hepatitis B - 1",   "label": "Birth",       "due_days": 0},
    {"vaccine_name": "OPV - 0",           "label": "Birth",       "due_days": 0},
    {"vaccine_name": "DTP - 1",           "label": "6 weeks",     "due_days": 42},
    {"vaccine_name": "OPV - 1",           "label": "6 weeks",     "due_days": 42},
    {"vaccine_name": "Hepatitis B - 2",   "label": "6 weeks",     "due_days": 42},
    {"vaccine_name": "DTP - 2",           "label": "10 weeks",    "due_days": 70},
    {"vaccine_name": "OPV - 2",           "label": "10 weeks",    "due_days": 70},
    {"vaccine_name": "DTP - 3",           "label": "14 weeks",    "due_days": 98},
    {"vaccine_name": "OPV - 3",           "label": "14 weeks",    "due_days": 98},
    {"vaccine_name": "Hepatitis B - 3",   "label": "14 weeks",    "due_days": 98},
    {"vaccine_name": "Measles - 1",       "label": "9 months",    "due_days": 274},
    {"vaccine_name": "MMR - 1",           "label": "9 months",    "due_days": 274},
    {"vaccine_name": "MMR - 2 (Booster)", "label": "16-18 months","due_days": 548},
    {"vaccine_name": "DTP Booster - 1",   "label": "16-18 months","due_days": 548},
    {"vaccine_name": "DTP Booster - 2",   "label": "5 years",     "due_days": 1825},
    {"vaccine_name": "Typhoid Booster",   "label": "6 years",     "due_days": 2190},
    {"vaccine_name": "Tdap/Td Booster",   "label": "10 years",    "due_days": 3650},
]

# How much slack before "upcoming" flips to "due_now". Deliberately generous
# so a slightly-early visit doesn't misleadingly flag the timing as due yet.
_DUE_LEAD_DAYS = 14

# How far past a rule's window (measured from min_age_days, only used when
# the rule has no max_age_days) the patient's age can drift before "due_now"
# flips to "past_window". This is NOT a clinical "overdue" cutoff — status
# stays "unknown" either way (see module docstring) — it only controls when
# the UI should stop phrasing an unrecorded vaccine as "recommended now" and
# start phrasing it as "no record on file, window has passed". 90 days is a
# reasonable starting default; tune per-rule via max_age_days if a schedule
# needs a tighter or looser window than that.
_PAST_WINDOW_GRACE_DAYS = 90


def _rule_get(rule, key):
    """Read a field off a rule that may be a VaccinationScheduleRule
    instance or a plain dict (per build_roadmap()'s docstring — callers may
    pass either)."""
    if isinstance(rule, dict):
        return rule.get(key)
    return getattr(rule, key, None)


def _serialize_matched(rule, record):
    # "completed" is the friendly alias for STATUS_VERIFIED; every other
    # verification_status value (pending_review/rejected/ordered/declined)
    # passes straight through as the roadmap status — see the state-machine
    # note on SharedVaccination for why "ordered"/"declined" live on this
    # same field instead of a separate one.
    status = "completed" if record.verification_status == record.STATUS_VERIFIED else record.verification_status
    return {
        "vaccine_name": record.vaccine_name,
        "scheduled_label": _rule_get(rule, "scheduled_label") if rule else record.scheduled_label,
        "administered_date": str(record.administered_date) if record.administered_date else None,
        "due_date": str(record.due_date) if record.due_date else None,
        "reason": record.reason,
        "dose_number": record.dose_number,
        "status": status,
        "timing": None,  # not applicable — a real record already resolved this slot
        "source": record.source,
        "verification_status": record.verification_status,
        "record_id": record.id,
        "has_certificate": bool(record.file_data),
        # Who actually logged this — "staff" (clinic-administered, doctor-
        # ordered, a self-reported one a doctor has since reviewed) vs
        # "patient" (self-reported, however verification_status currently
        # stands). Paired with verified_by_name so the portal can show
        # "Recorded by: Dr. X" for a clinic/doctor-ordered record vs
        # "Recorded by: Parent" for a self-reported one, and a
        # verified/awaiting-verification/ordered/declined badge.
        "recorded_by": record.recorded_by,
        "verified_by_name": record.verified_by_name,
        "extra": rule is None,
    }


def build_roadmap(awpid, date_of_birth, rules):
    """
    Merges a patient's real SharedVaccination records with a schedule's
    rules to produce one ordered list: rule slots that are fulfilled show
    the real record (status "completed"/"pending_review"/"rejected"); rule
    slots with no matching record show status "unknown" plus an
    informational `timing` ("upcoming"/"due_now"); records that don't match
    any rule (extra or self-reported outside the given schedule) are
    appended at the end.

    `rules` — a queryset or list of VaccinationScheduleRule instances (or
    dicts with the same keys: vaccine_name, scheduled_label, min_age_days,
    max_age_days), already in the order the roadmap should render in
    (VaccinationScheduleRule.Meta orders by sort_order). Callers resolve
    which schedule's rules to pass — see PortalVaccinationListView /
    PatientVaccinationListCreateView for the per-hospital / cross-hospital
    resolution logic.
    """
    from .models import SharedVaccination

    rules = list(rules)

    records = list(
        SharedVaccination.objects.using("default")
        .filter(awpid=awpid)
        .order_by("administered_date")
    )
    matched_ids = set()
    today = date.today()
    age_days = (today - date_of_birth).days if date_of_birth else None

    roadmap = []
    for rule in rules:
        label = _rule_get(rule, "scheduled_label")
        vaccine_name = _rule_get(rule, "vaccine_name")
        min_age_days = _rule_get(rule, "min_age_days")
        max_age_days = _rule_get(rule, "max_age_days")

        rec = next(
            (r for r in records
             if r.id not in matched_ids
             and r.scheduled_label == label
             and r.vaccine_name.strip().lower() == (vaccine_name or "").strip().lower()),
            None,
        )
        if rec:
            matched_ids.add(rec.id)
            roadmap.append(_serialize_matched(rule, rec))
            continue

        # No record → status is always "unknown" (never "overdue" — see
        # module docstring). `timing` is purely informational planning
        # metadata about whether the age window has been reached, and — if
        # it's been reached — whether it's still recent enough that "due
        # now" is an honest way to describe it (vs. "past_window", for
        # windows that closed long ago; see module docstring).
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
            "vaccine_name": vaccine_name,
            "scheduled_label": label,
            "administered_date": None,
            "due_date": None,
            "reason": "",
            "dose_number": None,
            "status": "unknown",
            "timing": timing,
            "source": None,
            "verification_status": None,
            "record_id": None,
            "has_certificate": False,
            "recorded_by": None,
            "verified_by_name": None,
            "extra": False,
        })

    for r in records:
        if r.id not in matched_ids:
            roadmap.append(_serialize_matched(None, r))

    return roadmap


def summarize_roadmap(roadmap):
    """
    Aggregate view of a roadmap built by build_roadmap(): how many of the
    real schedule slots are completed, and what's the next recommended one.

    "Real schedule items" excludes anything appended past the schedule
    (extra=True — a self-reported/outside record that didn't match any
    rule), since those aren't part of the denominator a patient would
    expect a completion % against.

    next_recommended picks the first schedule-order item with status
    "unknown" and timing "due_now" (schedule order — i.e. rule sort_order —
    decides, not any notion of urgency, since "unknown" items carry no
    urgency signal by design), or None if nothing is currently recommended.

    Field name note: this used to be called `next_due`. Both `next_due` and
    `next_recommended` are returned with the same value for backward
    compatibility with any already-deployed frontend build that reads the
    old key; new frontend code should read `next_recommended`.

    `stats` — a 4-bucket breakdown for the patient-facing "N/M completed"
    replacement (see apps/patients/portal_views.py PortalVaccinationListView
    callers), designed so the UI never has to phrase "no record on file" as
    "missed":
      - completed:    schedule slots with status "completed" (a verified
                       real record).
      - upcoming:      schedule slots with status "unknown" and
                       timing "upcoming" — window hasn't opened yet, nothing
                       to do.
      - needs_review:  schedule slots that represent an open question a
                       parent/doctor should look at — "pending_review"
                       (self-reported, awaiting doctor verification) plus
                       "unknown" slots with timing "due_now" or
                       "past_window" (window reached/passed, no record
                       either way, worth checking). Deliberately excludes
                       "declined" and "rejected" — a doctor already looked
                       at those and resolved them, so nothing is pending.
      - outside:       records — matched to a schedule slot or appended as
                       "extra" — whose `source` is not "clinic", i.e.
                       self-reported or ad-hoc doctor-ordered vaccinations
                       that didn't happen through this hospital's own
                       in-house administration. "unknown" slots have no
                       record (source is None) and are correctly excluded.
                       Counted across the *full* roadmap (including
                       extra=True items), unlike the other three buckets,
                       because "outside" records are exactly the kind of
                       thing that tends to live past the end of the
                       official schedule (e.g. a self-reported vaccine that
                       doesn't match any configured rule).
    """
    schedule_items = [item for item in roadmap if not item.get("extra")]
    total_count = len(schedule_items)
    completed_count = sum(1 for item in schedule_items if item["status"] == "completed")

    next_recommended = next(
        (item for item in schedule_items if item["status"] == "unknown" and item.get("timing") == "due_now"),
        None,
    )

    stats = {
        "completed": completed_count,
        "upcoming": sum(
            1 for item in schedule_items
            if item["status"] == "unknown" and item.get("timing") == "upcoming"
        ),
        "needs_review": sum(
            1 for item in schedule_items
            if item["status"] == "pending_review"
            or (item["status"] == "unknown" and item.get("timing") in ("due_now", "past_window"))
        ),
        "outside": sum(
            1 for item in roadmap
            if item.get("source") is not None and item["source"] != "clinic"
        ),
    }

    return {
        "completed_count": completed_count,
        "total_count": total_count,
        "next_recommended": next_recommended,
        "next_due": next_recommended,  # deprecated alias — see docstring
        "stats": stats,
    }
