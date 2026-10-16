"""
apps/opd/vitals_service.py
--------------------------
A nurse records a visit's vitals in the hospital screens; they are stored in Atomwalk (apps/vitals.py). This
finds who the patient is, whether they are a child, and hands the fields over.
"""
from apps.patients.models import Patient
from apps.documents.lib_vitals import recorded, save_visit, visit_vitals
from core.utils.age import age_years_months


def record_vitals(appointment, db, hospital_id, user_id, data):
    """Store the vitals of this appointment. Returns (the visit's vitals, whether they are new)."""
    from apps.opd.models import HospitalPatient

    patient = HospitalPatient.objects.using(db).filter(uuid=appointment.patient_id).first()
    age = age_years_months(patient.date_of_birth) if patient else None
    shared = Patient.objects.using("default").filter(awpid=appointment.patient_awpid).first()
    new = appointment.id not in recorded([appointment.id])
    save_visit(shared, appointment.id, hospital_id, user_id, data, is_minor=age is not None and age[0] < 18)
    appointment.__dict__.pop("vitals", None)
    return visit_vitals(appointment.id), new
