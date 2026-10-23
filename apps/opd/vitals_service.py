"""apps/opd/vitals_service.py"""
from apps.documents.lib_vitals import recorded, save_visit, visit_vitals
from core.utils.age import age_years_months


def record_vitals(appointment, db, hospital_id, user_id, data):
    """Store the vitals of this appointment. Returns (the visit's vitals, whether they are new)."""
    patient = appointment.patient
    age = age_years_months(patient.get_patient_details()["date_of_birth"])
    shared = patient.get_patient_details()["record"]
    new = appointment.id not in recorded([appointment.id])
    save_visit(shared, appointment.id, hospital_id, user_id, data, is_minor=age is not None and age[0] < 18)
    appointment.__dict__.pop("vitals", None)
    return visit_vitals(appointment.id), new
