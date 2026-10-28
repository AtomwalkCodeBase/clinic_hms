"""Where the timeline rules (the services folder) get a patient's date of birth and sex and a document's type, text and date from, which LLM answers them, and who may see a patient."""
import json
import time

from django.conf import settings

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


def ask_llm(system: str, user: str, timeout: int = None) -> str:
    """The prompt of the services folder sent to the company LLM api (settings.LLM_API_URL, token auth, {"user_prompt": ...} in, the answer text out),
    to a local Ollama when LLM_API_STYLE is "ollama", or to an OpenAI-compatible api (Groq, xAI Grok, OpenAI) when it is "openai"."""
    import requests

    if not settings.LLM_API_URL:
        raise ValueError("LLM_API_URL is not set")
    timeout = timeout or settings.LLM_API_TIMEOUT
    prompt = f"{system}\n\n{user}"
    if settings.LLM_API_STYLE == "ollama":
        resp = requests.post(
            settings.LLM_API_URL,
            json={"model": settings.LLM_API_MODEL, "messages": [{"role": "user", "content": prompt}], "stream": False, "format": "json"},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]
    if settings.LLM_API_STYLE == "openai":
        for attempt in range(6):
            resp = requests.post(
                settings.LLM_API_URL,
                json={"model": settings.LLM_API_MODEL, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                      "response_format": {"type": "json_object"}},
                headers={"Authorization": f"Bearer {settings.LLM_API_TOKEN}"},
                timeout=timeout,
            )
            if resp.status_code not in (429, 500, 502, 503) or attempt == 5:
                break
            # A hosted api limits requests per minute: wait as long as it asks (or longer each time) and ask again
            time.sleep(min(float(resp.headers.get("retry-after") or 0) or 5 * 2 ** attempt, 60))
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    resp = requests.post(
        settings.LLM_API_URL,
        json={"user_prompt": prompt},
        headers={"Authorization": f"Token {settings.LLM_API_TOKEN}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    body = resp.json()
    if isinstance(body, dict):
        if body.get("error"):
            raise ValueError(f"LLM api error: {body['error']}")
        body = next((body[k] for k in ("response", "answer", "text", "content", "result", "output", "reply", "message") if k in body), json.dumps(body))
    return body if isinstance(body, str) else json.dumps(body)


def patient_dob_sex(patient):
    return patient.date_of_birth, SEX_MAP.get((patient.gender or "").upper(), "male")


def doc_type(document):
    return DOC_TYPE_MAP.get(document.doc_classification, "OTHER")


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
