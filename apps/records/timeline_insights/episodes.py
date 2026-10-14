"""
Episodes and recurrence: a patient's clinical events (diagnoses and admissions, from hospitals and from documents) grouped
into illnesses, and a flag for an illness that keeps coming back.

  chronic condition   one ongoing episode, from the first time it was written down to the last
  acute condition     a new episode when the events are more than EPISODE_GAP_DAYS apart
  recurrence          RECURRENCE_EPISODES or more episodes of the same condition that started in the last RECURRENCE_MONTHS

rebuild(patient) is safe to run again at any time: it recomputes both from the events. A person's verdict on a flag
(acknowledged_by_id) survives, and so does a rejected event (left out).
"""
from datetime import date, timedelta

from apps.atomwalk.models import ClinicalEvent, HealthEpisode, RecurrenceFlag

EPISODE_GAP_DAYS = 30
RECURRENCE_EPISODES = 3
RECURRENCE_MONTHS = 12
_SEVERITY = ["NORMAL", "MILD", "ABNORMAL", "CRITICAL"]


def condition_group(code, text):
    """What counts as "the same condition": the ICD-10 category (J06.9 -> J06), else the condition's name."""
    return (code or "").strip().upper()[:3] or (text or "").strip().upper()[:40]


def _episodes_of(events):
    """Split one condition's events (oldest first) into episodes: a list of event lists."""
    if events[0].category == "CHRONIC":
        return [events]
    episodes = [[events[0]]]
    for event in events[1:]:
        if (event.event_date - episodes[-1][-1].event_date).days > EPISODE_GAP_DAYS:
            episodes.append([event])
        else:
            episodes[-1].append(event)
    return episodes


def rebuild(patient, today=None):
    """Recompute the patient's episodes and recurrence flags from their events."""
    today = today or date.today()
    events = list(ClinicalEvent.objects.using("default")
                  .filter(patient=patient, is_rejected=False, event_date__isnull=False).exclude(condition_group="")
                  .order_by("event_date", "id"))
    by_group = {}
    for event in events:
        by_group.setdefault(event.condition_group, []).append(event)

    kept = set()
    for group, group_events in by_group.items():
        for episode_events in _episodes_of(group_events):
            first, last = episode_events[0], episode_events[-1]
            chronic = first.category == "CHRONIC"
            key = group if chronic else f"{group}:{first.event_date}"
            kept.add(key)
            episode, _ = HealthEpisode.objects.using("default").update_or_create(patient=patient, key=key, defaults={
                "condition_group": group, "label": first.condition_text[:255] or group, "category": first.category or "ACUTE",
                "start_date": first.event_date, "end_date": None if chronic else last.event_date, "last_seen": last.event_date,
                "peak_severity": max((e.severity for e in episode_events), key=_SEVERITY.index), "event_count": len(episode_events),
                "is_provisional": all(e.is_provisional for e in episode_events)})
            ClinicalEvent.objects.using("default").filter(pk__in=[e.pk for e in episode_events]).update(episode=episode)
    HealthEpisode.objects.using("default").filter(patient=patient).exclude(key__in=kept).delete()
    _flag_recurrences(patient, today)


def _flag_recurrences(patient, today):
    since = today - timedelta(days=30 * RECURRENCE_MONTHS)
    counts = {}
    for episode in HealthEpisode.objects.using("default").filter(patient=patient, category="ACUTE", start_date__gte=since):
        counts.setdefault(episode.condition_group, []).append(episode)
    flags = RecurrenceFlag.objects.using("default")
    repeating = {g: es for g, es in counts.items() if len(es) >= RECURRENCE_EPISODES}
    for group, group_episodes in repeating.items():
        flags.update_or_create(patient=patient, condition_group=group, defaults={
            "label": group_episodes[0].label, "triggered_on": max(e.start_date for e in group_episodes),
            "rule": {"episodes": RECURRENCE_EPISODES, "months": RECURRENCE_MONTHS}, "episodes_last_12m": len(group_episodes),
            "clinical_hint": f"{len(group_episodes)} episodes in {RECURRENCE_MONTHS} months"})
    flags.filter(patient=patient).exclude(condition_group__in=repeating).delete()


def rebuild_all():
    """Every patient that has events (after a change to the rules above)."""
    from apps.atomwalk.models import Patient
    ids = ClinicalEvent.objects.using("default").values_list("patient_id", flat=True).distinct()
    for patient in Patient.objects.using("default").filter(pk__in=[i for i in ids if i]):
        rebuild(patient)


__all__ = ["rebuild", "rebuild_all", "condition_group"]
