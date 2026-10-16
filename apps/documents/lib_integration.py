"""Where the timeline rules (services.py) get a patient's date of birth and sex and a document's type, text and date from, and who may see a patient."""
from apps.documents.lib_documents import document_text as doc_text
from apps.hospital_master.models import Hospital
from apps.patients.models import PatientRelationship
from apps.hospital_patients.models import HospitalPatient

MAX_AGE_DAYS = 6574

SEX_MAP = {"M": "male", "F": "female"}

DOC_TYPE_MAP = {
    "prescription": "PRESCRIPTION",
    "lab_report": "LAB",
    "discharge_summary": "DISCHARGE_SUMMARY",
    "medical_bill": "BILL",
    "vaccination_record": "VACCINATION_CARD",
}


def patient_dob_sex(patient):
    return patient.date_of_birth, SEX_MAP.get((patient.gender or "").upper(), "male")


def doc_type(document):
    return DOC_TYPE_MAP.get(document.document_type, "OTHER")


def doc_date(document):
    return document.document_date or document.created_at.date()


def is_clinician(user):
    return getattr(user, "role", "") in ("doctor", "nurse") or bool({"doctor", "nurse"} & set(getattr(user, "acts_as", None) or ()))


def can_view_patient(user, patient):
    """A patient sees themselves and their dependents; hospital staff see the patients of their own hospital."""
    if getattr(user, "role", "") == "patient":
        mine = getattr(user, "awpid", None)
        return bool(mine) and (mine == patient.awpid or PatientRelationship.objects.filter(guardian__awpid=mine, dependent=patient).exists())
    if getattr(user, "is_platform", False) or not getattr(user, "hospital_id", None):
        return False
    hospital = Hospital.objects.filter(pk=user.hospital_id).first()
    return bool(hospital and HospitalPatient.objects.using(hospital.db_name).filter(awpid=patient.awpid).exists())
