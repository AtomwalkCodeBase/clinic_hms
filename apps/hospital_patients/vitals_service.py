"""apps/opd/vitals_service.py

A visit's vitals live in the hospital database (opd_vitals). A minor's weight, height and head circumference are also written to the shared
growth_measurement so the child's growth chart spans every hospital; the other readings stay with the hospital that took them."""

import logging
from datetime import datetime, time

from django.utils import timezone

from apps.documents.lib_vitals import bmi
from apps.documents.models import GrowthMeasurement
from apps.hospital_patients.models import Vitals
from core.utils import age_years_months

logger = logging.getLogger(__name__)

GROWTH = ("height_cm", "weight_kg", "head_circumference_cm")
FIELDS = ("systolic_bp", "diastolic_bp", "pulse_rate", "temperature", "spo2", "respiratory_rate", "blood_sugar_rbs", "nurse_notes") + GROWTH


def _number(value):
    return float(value) if value is not None else None


def _with_bmi(row):
    row.bmi = bmi(row)
    return row


def save_visit(appointment, db, hospital_id, user_id, data, *, shared_patient, is_minor):
    """Store what the nurse recorded for a visit."""
    row, _ = Vitals.objects.using(db).update_or_create(
        appointment=appointment,
        defaults={"recorded_by_id": user_id, **{f: data[f] for f in FIELDS if f in data}})
    if is_minor and shared_patient is not None:
        growth = {f: data[f] for f in GROWTH if f in data}
        if any(v is not None for v in growth.values()):
            GrowthMeasurement.objects.using("default").update_or_create(
                source_id=appointment.pk, defaults={"patient": shared_patient, "source_hospital_id": hospital_id,
                                                    "measured_on": timezone.localdate(), **growth})
        elif growth:
            GrowthMeasurement.objects.using("default").filter(source_id=appointment.pk).delete()      # the nurse cleared them
    return _with_bmi(row)


def visits_vitals(appointment_ids, db):
    """{appointment id: that visit's vitals} for the visits that have any."""
    return {v.appointment_id: _with_bmi(v) for v in Vitals.objects.using(db).filter(appointment_id__in=list(appointment_ids))}


def visit_vitals(appointment_id, db):
    return visits_vitals([appointment_id], db).get(appointment_id)


def attach_vitals(appointments, db):
    """Load the vitals of a page of appointments in one query instead of one per appointment (Appointment.vitals)."""
    appointments = list(appointments)
    found = visits_vitals((a.pk for a in appointments), db)
    for a in appointments:
        a.__dict__["vitals"] = found.get(a.pk)
    return appointments


def recorded(appointment_ids, db):
    """Which of these appointments have vitals recorded."""
    return set(Vitals.objects.using(db).filter(appointment_id__in=list(appointment_ids)).values_list("appointment_id", flat=True))


def record_vitals(appointment, db, hospital_id, user_id, data):
    """Store the vitals of this appointment. Returns (the visit's vitals, whether they are new)."""
    details = appointment.patient.get_patient_details()
    age = age_years_months(details["date_of_birth"])
    new = appointment.pk not in recorded([appointment.pk], db)
    row = save_visit(appointment, db, hospital_id, user_id, data, shared_patient=details["record"], is_minor=age is not None and age[0] < 18)
    appointment.__dict__.pop("vitals", None)
    return row, new


def _hospital_vitals(awpid, limit=None):
    """[(hospital id, vitals)] from every hospital the patient is registered at, newest first."""
    from apps.hospital_master.models import Hospital
    from apps.hospital_master.services import ensure_hospital_db
    from apps.hospital_patients.models import HospitalPatient

    found = []
    for hospital in Hospital.objects.using("default").filter(is_active=True):
        db = hospital.db_name
        try:
            ensure_hospital_db(db)
            patient_id = HospitalPatient.objects.using(db).filter(awpid=awpid).values_list("pk", flat=True).first()
            if patient_id is not None:
                rows = Vitals.objects.using(db).filter(appointment__patient_id=patient_id).order_by("-recorded_at")
                found += [(hospital.pk, _with_bmi(v)) for v in (rows[:limit] if limit else rows)]
        except Exception:
            logger.warning("vitals: skipped %s for %s", db, awpid, exc_info=True)
    return sorted(found, key=lambda pair: pair[1].recorded_at, reverse=True)


def _reading(row, recorded_at, source):
    return {"recorded_at": recorded_at, "source": source, "bp_systolic": getattr(row, "systolic_bp", None),
            "bp_diastolic": getattr(row, "diastolic_bp", None), "pulse_rate": getattr(row, "pulse_rate", None), "spo2": getattr(row, "spo2", None),
            "temperature": getattr(row, "temperature", None), "weight_kg": row.weight_kg, "height_cm": row.height_cm,
            "head_circumference_cm": row.head_circumference_cm, "resp_rate": getattr(row, "respiratory_rate", None),
            "blood_sugar_mgdl": getattr(row, "blood_sugar_rbs", None)}


def history_readings(awpid, limit=20):
    """A patient's latest readings from every hospital, newest first, one per visit, in the shape the history screens and the emergency summary read."""
    visits = _hospital_vitals(awpid, limit)
    seen = {v.appointment_id for _, v in visits}
    readings = [_reading(v, v.recorded_at, "clinic") for _, v in visits]
    for g in GrowthMeasurement.objects.using("default").filter(patient__awpid=awpid, is_rejected=False).order_by("-measured_on")[:limit]:
        if g.source_id not in seen:
            readings.append(_reading(g, timezone.make_aware(datetime.combine(g.measured_on, time(12, 0))), g.source))
    return sorted(readings, key=lambda r: r["recorded_at"], reverse=True)[:limit]


def growth_points(awpid, *, hospital_id=None, include_other=True):
    """The points of a growth chart, one per day, oldest first: {"date", height_cm, weight_kg, head_circumference_cm, bmi, source}."""
    points = {}
    rows = [(g.measured_on, g, g.head_circumference_cm, g.source, g.source_hospital_id) for g in
            GrowthMeasurement.objects.using("default").filter(patient__awpid=awpid, is_rejected=False)]
    rows += [(v.recorded_at.date(), v, v.head_circumference_cm, "clinic", hid) for hid, v in _hospital_vitals(awpid) if v.height_cm or v.weight_kg]
    for day, row, head, kind, row_hospital in sorted(rows, key=lambda r: r[0]):
        if not (row.height_cm or row.weight_kg or head):
            continue
        if hospital_id is None:
            source = kind
        elif row_hospital == hospital_id:
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
