"""A visit's vitals and growth readings, the hospital write-through to the shared clinical events, and the growth reference percentiles."""

import logging
import math
from datetime import date, datetime, time
from decimal import Decimal
from types import SimpleNamespace

from apps.documents.models import GrowthMeasurement, Vitals
from django.utils import timezone

logger = logging.getLogger(__name__)


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
        for f in VITAL_SIGNS + GROWTH:
            if hasattr(row, f) and getattr(row, f) not in (None, ""):
                setattr(one, f, getattr(row, f))
        one.recorded_by_user_id = getattr(row, "recorded_by_user_id", None) or one.recorded_by_user_id
        one.recorded_at = getattr(row, "recorded_at", None) or timezone.make_aware(datetime.combine(row.measured_on, time(12, 0)))
        one.id = row.id
    one.bmi = bmi(one)
    return one
def save_visit(patient, appointment_id, hospital_id, user_id, data, *, is_minor):
    """
    Store what the nurse recorded for a visit. `patient` is the atomwalk patient (or None), `data` the validated fields.
    A child's height, weight and head size go to growth_measurement; everything else, and an adult's height and weight,
    to vitals. Returns the visit's vitals as one object.
    """
    common = {"patient": patient, "source_hospital_id": hospital_id}
    kept = VITAL_SIGNS if is_minor else VITAL_SIGNS + ADULT_GROWTH
    Vitals.objects.using("default").update_or_create(
        appointment_id=appointment_id, defaults={**common, "recorded_by_user_id": user_id, **{f: data[f] for f in kept if f in data}})
    if is_minor:
        growth = {f: data[f] for f in GROWTH if f in data}
        rows = GrowthMeasurement.objects.using("default").filter(source_id=appointment_id)
        if any(v is not None for v in growth.values()):
            GrowthMeasurement.objects.using("default").update_or_create(
                source_id=appointment_id, defaults={**common,
                                                    "measured_on": timezone.localdate(), **growth})
        elif growth:
            rows.delete()                                      # the nurse cleared them
    return visit_vitals(appointment_id)
def visits_vitals(appointment_ids):
    """{appointment id: that visit's vitals as one object} for the visits that have any."""
    ids = list(appointment_ids)
    vitals = {v.appointment_id: v for v in Vitals.objects.using("default").filter(appointment_id__in=ids)}
    growth = {g.source_id: g for g in GrowthMeasurement.objects.using("default").filter(source_id__in=ids)}
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
    return done | set(GrowthMeasurement.objects.using("default").filter(source_id__in=ids).values_list("source_id", flat=True))
def history_readings(awpid, limit=20):
    """
    A patient's latest readings, newest first, one per visit, in the shape the history screens and the emergency summary
    read (bp_systolic, resp_rate ... head_circumference_cm). Another hospital's id is never part of it.
    """
    by_visit, loose = {}, []
    for row in list(Vitals.objects.using("default").filter(patient__awpid=awpid).order_by("-recorded_at")[:limit]) + \
            list(GrowthMeasurement.objects.using("default").filter(patient__awpid=awpid, is_rejected=False).order_by("-measured_on")[:limit]):
        visit = row.appointment_id if isinstance(row, Vitals) else row.source_id
        (by_visit.setdefault(visit, []) if visit else loose).append(row)
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
                 "head_circumference_cm": _number(head), "bmi": _number(bmi(row)), "source": source}
        if str(day) not in points or (source == "this_hospital" and points[str(day)]["source"] != "this_hospital"):
            points[str(day)] = point
    return sorted(points.values(), key=lambda p: p["date"])
__all__ = ["save_visit", "visit_vitals", "visits_vitals", "attach_vitals", "recorded", "history_readings", "growth_points"]


def bmi(row):
    if row.weight_kg and row.height_cm and row.height_cm > 0:
        return Decimal(f"{float(row.weight_kg) / ((float(row.height_cm) / 100) ** 2):.1f}")
    return None


def sync_encounter_to_hie(encounter, db, patient, hospital_id=None):
    """
    Copy this encounter's diagnoses to the shared clinical events so other hospitals can see this patient's
    cross-provider history. Never blocks sign-off: all failures are logged and swallowed.

    `hospital_id` is the atomwalk id of the hospital writing the rows (request.hospital_id);
    when omitted (seed commands) it is resolved from `db` — see resolve_source_hospital_id.
    """
    if patient is None or not getattr(patient, "awpid", None):
        logger.warning("HIE sync skipped for encounter %s: no patient/awpid.", encounter.id)
        return

    from apps.documents.models import ClinicalEvent
    from apps.patients.models import Patient
    from apps.hospital_master.services import resolve_source_hospital_id
    from apps.documents.lib_processing import rebuild_patient

    shared = Patient.objects.using("default").filter(awpid=patient.awpid).first()
    if shared is None:
        logger.warning("HIE sync skipped for encounter %s: %s has no shared patient.", encounter.id, patient.awpid)
        return
    source_hospital_id = hospital_id or resolve_source_hospital_id(db)
    seen_on = getattr(getattr(encounter, "appointment", None), "scheduled_date", None) or date.today()

    # OPDEncounter.diagnoses is a JSON list of {code, description}
    for diag in (encounter.diagnoses or []):
        try:
            ClinicalEvent.objects.using("default").update_or_create(
                patient=shared, source_hospital_id=source_hospital_id, event_type="DIAGNOSIS", icd10=diag.get("code", ""),
                defaults={"condition_text": diag.get("description", ""), "clinical_status": "active", "event_date": seen_on,
                          "source": "HOSPITAL"},
            )
        except Exception:
            logger.exception("HIE ClinicalEvent write failed for encounter=%s", encounter.id)
    try:
        rebuild_patient(shared.pk)
    except Exception:
        logger.exception("Episodes rebuild failed for encounter=%s", encounter.id)


# measurement -> sex -> [(age_months, L, M, S), ...] sorted by age
REFERENCE_TABLES = {
    "weight": {
        "M": [
            (0, 0.3487, 3.3464, 0.1460), (1, 0.2297, 4.4709, 0.1340), (2, 0.1970, 5.5675, 0.1239),
            (3, 0.1738, 6.3762, 0.1173), (6, 0.1257, 7.9340, 0.1096), (9, 0.0917, 8.9014, 0.1088),
            (12, 0.0644, 9.6479, 0.1092), (18, 0.0211, 10.9385, 0.1112), (24, -0.0137, 12.1515, 0.1143),
            (36, -0.0689, 14.3429, 0.1212), (48, -0.1131, 16.3489, 0.1276), (60, -0.1506, 18.3366, 0.1352),
        ],
        "F": [
            (0, 0.3809, 3.2322, 0.1417), (1, 0.1714, 4.1873, 0.1372), (2, 0.0962, 5.1282, 0.1300),
            (3, 0.0402, 5.8458, 0.1262), (6, -0.0756, 7.2970, 0.1220), (9, -0.1507, 8.2254, 0.1220),
            (12, -0.2024, 8.9481, 0.1227), (18, -0.2637, 10.2315, 0.1231), (24, -0.2941, 11.4775, 0.1239),
            (36, -0.3201, 13.8503, 0.1292), (48, -0.3361, 16.0697, 0.1388), (60, -0.3518, 18.2193, 0.1482),
        ],
    },
    # 0-24mo from the length-for-age (recumbent) table, 24-60mo from the
    # height-for-age (standing) table — see module docstring for why.
    "height": {
        "M": [
            (0, 1, 49.8842, 0.0379), (1, 1, 54.7244, 0.0356), (2, 1, 58.4249, 0.0342),
            (3, 1, 61.4292, 0.0333), (6, 1, 67.6236, 0.0316), (9, 1, 71.9687, 0.0312),
            (12, 1, 75.7488, 0.0314), (18, 1, 82.2587, 0.0328), (24, 1, 87.8161, 0.0348),
            (36, 1, 96.0835, 0.0386), (48, 1, 103.3273, 0.0406), (60, 1, 109.9638, 0.0421),
        ],
        "F": [
            (0, 1, 49.1477, 0.0379), (1, 1, 53.6872, 0.0364), (2, 1, 57.0673, 0.0357),
            (3, 1, 59.8029, 0.0352), (6, 1, 65.7311, 0.0345), (9, 1, 70.1435, 0.0344),
            (12, 1, 74.0150, 0.0348), (18, 1, 80.7079, 0.0360), (24, 1, 86.4153, 0.0373),
            (36, 1, 95.0515, 0.0401), (48, 1, 102.7312, 0.0419), (60, 1, 109.4233, 0.0435),
        ],
    },
    "head_circumference": {
        "M": [
            (0, 1, 34.4618, 0.0369), (1, 1, 37.2759, 0.0313), (2, 1, 39.1285, 0.0300),
            (3, 1, 40.5135, 0.0292), (6, 1, 43.3306, 0.0282), (9, 1, 44.9998, 0.0279),
            (12, 1, 46.0661, 0.0279), (18, 1, 47.3711, 0.0280), (24, 1, 48.2515, 0.0282),
            (36, 1, 49.4612, 0.0287), (48, 1, 50.2115, 0.0291), (60, 1, 50.7375, 0.0295),
        ],
        "F": [
            (0, 1, 33.8787, 0.0350), (1, 1, 36.5463, 0.0321), (2, 1, 38.2521, 0.0317),
            (3, 1, 39.5328, 0.0314), (6, 1, 42.1995, 0.0309), (9, 1, 43.8300, 0.0305),
            (12, 1, 44.8965, 0.0303), (18, 1, 46.2424, 0.0299), (24, 1, 47.1822, 0.0296),
            (36, 1, 48.5099, 0.0291), (48, 1, 49.3321, 0.0288), (60, 1, 49.9229, 0.0285),
        ],
    },
}
MEASUREMENTS = ("weight", "height", "head_circumference")
def _lms(measurement, sex, age_months):
    """The (L, M, S) coefficients for this child, or None when the table doesn't cover them (WHO covers 0-60 months, M or F)."""
    table = REFERENCE_TABLES.get(measurement, {}).get(sex)
    if not table or age_months is None or not 0 <= age_months <= 60:
        return None
    for (a0, *c0), (a1, *c1) in zip(table, table[1:]):
        if a0 <= age_months <= a1:
            frac = (age_months - a0) / (a1 - a0)
            return tuple(x0 + frac * (x1 - x0) for x0, x1 in zip(c0, c1))
    return tuple(table[-1][1:])
def get_percentile(measurement, sex, age_months, value):
    """
    {"z_score", "percentile" (0-100)} for one measurement, or None when it can't be scored (no value, age outside
    0-60 months, sex not M or F). measurement: "weight" (kg), "height" or "head_circumference" (cm).
    """
    lms = _lms(measurement, sex, age_months)
    if value is None or lms is None:
        return None
    L, M, S = lms
    value = float(value)
    z = (((value / M) ** L) - 1) / (L * S) if L != 0 else math.log(value / M) / S
    z = max(-5, min(5, z))                         # a wildly out-of-range reading shouldn't blow up the percentile
    return {"z_score": round(z, 2), "percentile": round(0.5 * (1 + math.erf(z / math.sqrt(2))) * 100, 1)}
_MEASURED = {"weight": "weight_kg", "height": "height_cm", "head_circumference": "head_circumference_cm"}
def add_percentiles(series, gender, date_of_birth, *, only_source=None):
    """
    Add a "percentiles" dict to each reading in `series` (dicts with "date" as YYYY-MM-DD, weight_kg, height_cm,
    head_circumference_cm, "source") taken before the child turned 5. `only_source` limits it to readings from that
    source. Returns whether any reading got a percentile.
    """
    if gender not in ("M", "F") or not date_of_birth:
        return False
    found = False
    for point in series:
        if only_source and point["source"] != only_source:
            continue
        taken = date.fromisoformat(point["date"])
        months = (taken.year - date_of_birth.year) * 12 + (taken.month - date_of_birth.month)
        if not 0 <= months <= 60:
            continue
        point["percentiles"] = {}
        for name in MEASUREMENTS:
            result = get_percentile(name, gender, months, point[_MEASURED[name]])
            if result:
                point["percentiles"][name] = result
                found = True
    return found
