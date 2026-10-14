"""
apps/atomwalk/vitals.py
-----------------------
How a visit's vital signs are stored and read back. They live in Atomwalk, not in the hospital's database:

  vitals               blood pressure, pulse, temperature, oxygen, breathing, blood sugar, the nurse's note, and an
                       adult's height and weight
  growth_measurement   a child's height, weight and head size

A nurse enters everything on one form. save_visit() splits it by those two tables (a child's visit writes a row in
each), and visit_vitals() / visits_vitals() put it back together as one object for the screens, so the screens, the
doctor's history and the growth charts all keep reading "the vitals of this visit". The appointment is the hospital's, so
it is kept as a plain id.
"""
from datetime import datetime, time
from types import SimpleNamespace

from django.utils import timezone

from .models import GrowthMeasurement, Vitals

VITAL_SIGNS = ("systolic_bp", "diastolic_bp", "pulse_rate", "temperature", "spo2", "respiratory_rate", "blood_sugar_rbs", "nurse_notes")
GROWTH = ("height_cm", "weight_kg", "head_circumference_cm")
ADULT_GROWTH = ("height_cm", "weight_kg")                    # an adult's height and weight are kept with the other vitals


def _number(value):
    return float(value) if value is not None else None


def _merged(vitals, growth):
    """One object with every field of a visit's vitals, whichever table it came from."""
    one = SimpleNamespace(id=None, recorded_at=None, recorded_by_user_id=None, bmi=None, nurse_notes="",
                          **{f: None for f in VITAL_SIGNS + GROWTH if f != "nurse_notes"})
    for row in (growth, vitals):                               # vitals last: its note and time win
        if row is None:
            continue
        for f in VITAL_SIGNS + GROWTH + ("bmi",):
            if hasattr(row, f) and getattr(row, f) not in (None, ""):
                setattr(one, f, getattr(row, f))
        one.recorded_by_user_id = row.recorded_by_user_id or one.recorded_by_user_id
        one.recorded_at = getattr(row, "recorded_at", None) or timezone.make_aware(datetime.combine(row.measured_on, time(12, 0)))
        one.id = row.id
    return one


def save_visit(patient, appointment_id, hospital_id, user_id, data, *, is_minor):
    """
    Store what the nurse recorded for a visit. `patient` is the atomwalk patient (or None), `data` the validated fields.
    A child's height, weight and head size go to growth_measurement; everything else, and an adult's height and weight,
    to vitals. Returns the visit's vitals as one object.
    """
    common = {"patient": patient, "source_hospital_id": hospital_id, "recorded_by_user_id": user_id}
    kept = VITAL_SIGNS if is_minor else VITAL_SIGNS + ADULT_GROWTH
    Vitals.objects.using("default").update_or_create(
        appointment_id=appointment_id, defaults={**common, **{f: data[f] for f in kept if f in data}})
    if is_minor:
        growth = {f: data[f] for f in GROWTH if f in data}
        rows = GrowthMeasurement.objects.using("default").filter(appointment_id=appointment_id)
        if any(v is not None for v in growth.values()):
            GrowthMeasurement.objects.using("default").update_or_create(
                appointment_id=appointment_id, defaults={**common, "measured_on": timezone.localdate(), **growth})
        elif growth:
            rows.delete()                                      # the nurse cleared them
    return visit_vitals(appointment_id)


def visits_vitals(appointment_ids):
    """{appointment id: that visit's vitals as one object} for the visits that have any."""
    ids = list(appointment_ids)
    vitals = {v.appointment_id: v for v in Vitals.objects.using("default").filter(appointment_id__in=ids)}
    growth = {g.appointment_id: g for g in GrowthMeasurement.objects.using("default").filter(appointment_id__in=ids)}
    return {i: _merged(vitals.get(i), growth.get(i)) for i in set(vitals) | set(growth)}


def visit_vitals(appointment_id):
    return visits_vitals([appointment_id]).get(appointment_id)


def attach_vitals(appointments):
    """Load the vitals of a page of appointments in two queries instead of one per appointment (Appointment.vitals)."""
    appointments = list(appointments)
    found = visits_vitals(a.id for a in appointments)
    for a in appointments:
        a.__dict__["vitals"] = found.get(a.id)
    return appointments


def recorded(appointment_ids):
    """Which of these appointments have vitals recorded."""
    ids = list(appointment_ids)
    done = set(Vitals.objects.using("default").filter(appointment_id__in=ids).values_list("appointment_id", flat=True))
    return done | set(GrowthMeasurement.objects.using("default").filter(appointment_id__in=ids).values_list("appointment_id", flat=True))


def history_readings(awpid, limit=20):
    """
    A patient's latest readings, newest first, one per visit, in the shape the history screens and the emergency summary
    read (bp_systolic, resp_rate ... head_circumference_cm). Another hospital's id is never part of it.
    """
    by_visit, loose = {}, []
    for row in list(Vitals.objects.using("default").filter(patient__awpid=awpid).order_by("-recorded_at")[:limit]) + \
            list(GrowthMeasurement.objects.using("default").filter(patient__awpid=awpid, is_rejected=False).order_by("-measured_on")[:limit]):
        (by_visit.setdefault(row.appointment_id, []) if row.appointment_id else loose).append(row)
    readings = [_reading(*pair) for pair in ((r, None) for r in loose)]
    readings += [_reading(*[next((r for r in rows if isinstance(r, cls)), None) for cls in (Vitals, GrowthMeasurement)])
                 for rows in by_visit.values()]
    return sorted(readings, key=lambda r: r["recorded_at"], reverse=True)[:limit]


def _reading(vitals, growth):
    one = _merged(vitals, growth)
    return {"recorded_at": one.recorded_at, "source": (vitals or growth).source, "bp_systolic": one.systolic_bp,
            "bp_diastolic": one.diastolic_bp, "pulse_rate": one.pulse_rate, "spo2": one.spo2, "temperature": one.temperature,
            "weight_kg": one.weight_kg, "height_cm": one.height_cm, "head_circumference_cm": one.head_circumference_cm,
            "resp_rate": one.respiratory_rate, "blood_sugar_mgdl": one.blood_sugar_rbs}


def growth_points(awpid, *, hospital_id=None, include_other=True):
    """
    The points of a growth chart, one per day, oldest first: {"date", height_cm, weight_kg, head_circumference_cm, bmi,
    "source"}. With a `hospital_id` (the staff view) a reading is "this_hospital" or "other_hospital", and other
    hospitals' readings are left out unless `include_other` and only count on days this hospital has none. Without it (the
    patient's own view) the source is the reading's own: clinic or home.
    """
    points = {}
    rows = [(g.measured_on, g, g.head_circumference_cm) for g in
            GrowthMeasurement.objects.using("default").filter(patient__awpid=awpid, is_rejected=False)]
    rows += [(v.recorded_at.date(), v, None) for v in
             Vitals.objects.using("default").filter(patient__awpid=awpid) if v.height_cm or v.weight_kg]
    for day, row, head in sorted(rows, key=lambda r: r[0]):
        if not (row.height_cm or row.weight_kg or head):
            continue
        if hospital_id is None:
            source = row.source
        elif row.source_hospital_id == hospital_id:
            source = "this_hospital"
        elif include_other:
            source = "other_hospital"
        else:
            continue
        point = {"date": str(day), "height_cm": _number(row.height_cm), "weight_kg": _number(row.weight_kg),
                 "head_circumference_cm": _number(head), "bmi": _number(row.bmi), "source": source}
        if str(day) not in points or (source == "this_hospital" and points[str(day)]["source"] != "this_hospital"):
            points[str(day)] = point
    return sorted(points.values(), key=lambda p: p["date"])


__all__ = ["save_visit", "visit_vitals", "visits_vitals", "attach_vitals", "recorded", "history_readings", "growth_points"]
