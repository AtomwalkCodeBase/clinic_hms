"""Laboratory trends, medicine history, data gaps and plain-language test results for one patient, built from the same rows as the timeline."""
from datetime import date

from . import integration as ig
from .lib_documents import awaiting_review_q, confirmed_q, display_name
from .models import ClinicalEvent, DocumentExtraction, GrowthMeasurement, ImmunizationRecord, LabResult, MedicalDocument, BirthHistory
from .services.clinical_rules import evaluate_lab
from .services.config import load_config

LABELS = {
    "HEMOGLOBIN_G_DL": ("Haemoglobin", "g/dL"), "PLATELETS_PER_UL": ("Platelet count", "/µL"), "WBC_PER_UL": ("White cell count", "/µL"),
    "GLUCOSE_MG_DL": ("Blood glucose", "mg/dL"), "SODIUM_MMOL_L": ("Sodium", "mmol/L"), "POTASSIUM_MMOL_L": ("Potassium", "mmol/L"),
    "BILIRUBIN_TOTAL_MG_DL": ("Total bilirubin", "mg/dL"), "CREATININE_MG_DL": ("Creatinine", "mg/dL"), "CRP_MG_L": ("C-reactive protein", "mg/L"),
}


def _label(analyte):
    return LABELS.get(analyte, (analyte.replace("_", " ").title(), ""))


def _reference(limits):
    low, high = limits.get("low"), limits.get("high")
    if low is not None and high is not None:
        return f"{low:g}–{high:g}"
    if high is not None:
        return f"up to {high:g}"
    if low is not None:
        return f"{low:g} or more"
    return ""


def _lab_rows(patient, hospital_id, cfg):
    dob, _ = ig.patient_dob_sex(patient)
    own = {"source_hospital_id": hospital_id} if hospital_id is not None else {}
    rows, seen = [], set()
    for lab in LabResult.objects.filter(confirmed_q(), patient=patient, collected_on__isnull=False, value__isnull=False, **own).order_by("collected_on", "pk"):
        if (lab.analyte, lab.collected_on, lab.value) in seen:
            continue                      # a discharge summary quotes the labs of its own lab report: one result is listed once
        seen.add((lab.analyte, lab.collected_on, lab.value))
        judged = evaluate_lab(lab.analyte, lab.value, (lab.collected_on - dob).days, cfg)
        name, unit = _label(lab.analyte)
        rows.append({"analyte": lab.analyte, "label": name, "unit": unit, "date": lab.collected_on, "value": lab.value,
                     "severity": lab.severity, "direction": lab.direction or judged["direction"], "age_band": judged["band"] or lab.age_band,
                     "reference": _reference(judged["limits"]), "document_id": lab.document_id})
    return rows


def lab_trends(patient, hospital_id=None):
    """Every analyte over time with its reference range for the child's age, abnormal ones first."""
    cfg = load_config()
    by_analyte = {}
    for row in _lab_rows(patient, hospital_id, cfg):
        by_analyte.setdefault(row["analyte"], []).append(row)
    out = []
    for analyte, points in by_analyte.items():
        values = [p["value"] for p in points]
        trend = None
        if len(values) > 1:
            trend = "up" if values[-1] > values[-2] else "down" if values[-1] < values[-2] else "flat"
        out.append({"_latest": points[-1]["date"], "analyte": analyte, "label": points[0]["label"], "unit": points[0]["unit"], "latest_severity": points[-1]["severity"],
                    "trend": trend, "ever_abnormal": any(p["severity"] != "NORMAL" for p in points),
                    "points": [{**p, "date": p["date"].isoformat()} for p in points]})
    # the most recently tested first; on the same day the abnormal ones first
    out.sort(key=lambda t: (-t["_latest"].toordinal(), {"CRITICAL": 0, "ABNORMAL": 1, "NORMAL": 2}.get(t["latest_severity"], 2), t["label"]))
    for t in out:
        del t["_latest"]
    return out


def data_gaps(patient, hospital_id=None):
    """What the timeline does not know: reports that could not be read, unconfirmed diagnoses, missing measurements."""
    dob, _ = ig.patient_dob_sex(patient)
    own_doc = {"source_hospital_id": hospital_id} if hospital_id is not None else {}
    docs = MedicalDocument.objects.filter(patient=patient, **own_doc)
    Status = DocumentExtraction.Status
    counts = {s: DocumentExtraction.objects.filter(document__in=docs, status=getattr(Status, s)).count() for s in ("DONE", "PENDING", "FAILED", "SKIPPED")}
    failed = [{"document_id": d.pk, "name": display_name(d)} for d in docs.filter(d_extraction__status=Status.FAILED)[:10]]
    awaiting = docs.filter(awaiting_review_q()).count()
    events = ClinicalEvent.objects.filter(confirmed_q(), patient=patient).exclude(verification_status="rejected")
    unconfirmed = events.filter(is_provisional=True).exclude(verification_status="verified").count()
    undated = events.filter(event_date__isnull=True).count()
    unread_vaccines = ImmunizationRecord.objects.filter(patient=patient, vaccines=[]).count()
    last = GrowthMeasurement.objects.filter(confirmed_q(), patient=patient, is_rejected=False).order_by("-measured_on").values_list("measured_on", flat=True).first()
    months_since = ((date.today() - last).days // 30) if last else None
    items = []
    if counts["FAILED"]:
        items.append({"level": "warning", "text": f"{counts['FAILED']} report(s) could not be read and are missing from this timeline.", "documents": failed})
    if counts["PENDING"]:
        items.append({"level": "info", "text": f"{counts['PENDING']} report(s) are still being read."})
    if awaiting:
        items.append({"level": "info", "text": f"{awaiting} report(s) are waiting for the patient to confirm their type."})
    if unconfirmed:
        items.append({"level": "warning", "text": f"{unconfirmed} diagnosis(es) are unconfirmed and are shown to you only. Verify or reject them."})
    if undated:
        items.append({"level": "warning", "text": f"{undated} diagnosis(es) have no date and are left off the timeline."})
    if unread_vaccines:
        items.append({"level": "info", "text": f"{unread_vaccines} vaccine entry(ies) were not recognised and are not counted."})
    if last is None:
        items.append({"level": "warning", "text": "No weight or height has been recorded."})
    elif months_since and months_since >= 12 and dob and (date.today() - dob).days < 6574:
        items.append({"level": "info", "text": f"No weight or height recorded in the last {months_since} months (last on {last.isoformat()})."})
    if not BirthHistory.objects.filter(patient=patient).exists() and dob and (date.today() - dob).days < 365 * 6:
        items.append({"level": "info", "text": "Birth history (gestation, birth weight, NICU stay) is not on file."})
    return {"reports": counts, "items": items}
