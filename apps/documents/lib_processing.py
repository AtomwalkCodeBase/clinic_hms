"""
The database side of the pediatric health timeline: services.py judges, this saves and reads.

    process_document(document)    the LLM's facts from one document -> events, measurements, vaccines, labs, birth history
    rebuild_patient(patient_id)   episodes, recurrence flags and growth z-scores recomputed from the patient's rows
    build_timeline_payload(...)   the rows -> the timeline the API returns

Running a document again is safe: what it extracted before is replaced, while a row a person verified, rejected or
entered is never touched.
"""
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.documents import lib_integration as ig
from apps.documents.models import (
    BirthHistory,
    ClinicalEvent,
    DocumentExtraction,
    GrowthMeasurement,
    HealthEpisode,
    ImmunizationRecord,
    LabResult,
    RecurrenceFlag,
)
from apps.documents.services import (
    EXTRACTOR_VERSION,
    EventIn,
    age_band,
    build_episodes,
    build_timeline,
    classify_condition,
    detect_faltering,
    detect_recurrence,
    evaluate_lab,
    extract_document,
    find_critical_keywords,
    immunization_status,
    is_uncertain,
    load_config,
    resolve_vaccines,
    score_measurement,
)
from apps.patients.models import Patient

CORRECTED_AGE_UNTIL_MONTHS = 24
ICU_WARDS = ("ICU", "PICU", "NICU")
DELIVERY = {"NVD": "normal", "LSCS": "c_section", "INSTRUMENTAL": "assisted"}
SHOWN_VACCINES = (ImmunizationRecord.STATUS_VERIFIED, ImmunizationRecord.STATUS_PENDING)
GROWTH_COLUMNS = (("weight_kg", "weight_z", "weight_pct"), ("height_cm", "height_z", "height_pct"),
                  ("head_circumference_cm", "head_circ_z", "head_circ_pct"))
SCORED_AS = {"head_circumference_cm": "head_circ_cm"}


def growth_dob(dob, birth_history):
    """A baby born early is plotted on its corrected age until 24 months: the date of birth moves forward by the weeks
    it was early. Vaccines keep the chronological age."""
    weeks = birth_history.gestational_age_weeks if birth_history else None
    return dob + timedelta(weeks=40 - weeks) if weeks and weeks < 37 else dob


def _growth_dob_on(on, dob, corrected):
    return corrected if (on - dob).days < CORRECTED_AGE_UNTIL_MONTHS * 30.4375 else dob


def _measures(row):
    return {SCORED_AS.get(name, name): float(getattr(row, name)) if getattr(row, name) is not None else None
            for name, _, _ in GROWTH_COLUMNS}


def _jsonable(obj):
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    return obj.isoformat() if isinstance(obj, date) else obj


def _event_in(row):
    return EventIn(id=row.pk, event_date=row.event_date, icd10=row.icd10, condition_text=row.condition_text, severity=row.severity,
                   is_provisional=row.is_provisional and not row.is_verified, document_id=row.document_id)


# ── one document ───────────────────────────────────────────────────────────────

def process_document(document, llm=None, force=False):
    cfg = load_config()
    patient = document.patient
    dob, _sex = ig.patient_dob_sex(patient)
    extraction, _ = DocumentExtraction.objects.get_or_create(document=document)
    if extraction.status == DocumentExtraction.Status.DONE and extraction.normalised.get("extractor_version") == EXTRACTOR_VERSION and not force:
        return {"status": "SKIPPED", "reason": "already processed"}

    text = ig.doc_text(document)
    reason = ("no date of birth" if dob is None else "outside pediatric age scope" if (date.today() - dob).days > ig.MAX_AGE_DAYS
              else "no extracted text" if len(text.strip()) < 20 else "")
    if reason:
        extraction.status, extraction.normalised = DocumentExtraction.Status.SKIPPED, {"extractor_version": EXTRACTOR_VERSION, "skipped": reason}
        extraction.save()
        return {"status": "SKIPPED", "reason": reason}

    dtype = ig.doc_type(document)
    result = extract_document(text, dtype, dob, ig.doc_date(document), llm=llm, cfg=cfg)
    counts = persist_extraction(document, dob, dtype, text, result, cfg)
    extraction.status = DocumentExtraction.Status.DONE
    extraction.normalised = {**_jsonable(result), "doc_type": dtype, "extractor_version": EXTRACTOR_VERSION}
    extraction.processed_at = timezone.now()
    extraction.save()
    return {"status": "DONE", "patient_id": patient.pk, "counts": counts, "warnings": result["warnings"]}


@transaction.atomic
def persist_extraction(document, dob, dtype, text, result, cfg):
    patient, hospital_id, doc_date = document.patient, document.source_hospital_id, result["document_date"]
    ClinicalEvent.objects.filter(document=document, source="EXTRACTED", is_verified=False, is_rejected=False).delete()
    GrowthMeasurement.objects.filter(document=document, source="extracted", is_rejected=False).delete()
    ImmunizationRecord.objects.filter(document=document, source=ImmunizationRecord.SOURCE_EXTRACTED,
                                      verification_status=ImmunizationRecord.STATUS_PENDING).delete()
    LabResult.objects.filter(document=document, delivered_at__isnull=True).delete()
    here = {"patient": patient, "document": document, "source_hospital_id": hospital_id}

    severity, admission = "NORMAL", result.get("admission")
    critical_terms = find_critical_keywords(text, cfg) if dtype in ("DISCHARGE_SUMMARY", "BILL") else []
    if admission or critical_terms:
        is_critical = bool(critical_terms) or bool(admission and admission["ward"] in ICU_WARDS)
        severity = "CRITICAL" if is_critical else "ABNORMAL"
        first = next((d["condition_text"] for d in result["diagnoses"] if not d["is_provisional"]), "")
        ClinicalEvent.objects.create(
            **here, event_type="ADMISSION", event_date=(admission or {}).get("admitted_on") or doc_date,
            discharged_on=(admission or {}).get("discharged_on"), ward=(admission or {}).get("ward") or ("ICU" if is_critical else "WARD"),
            is_critical=is_critical, critical_terms=critical_terms, reason=first[:255], severity=severity, source="EXTRACTED")

    kept = set(ClinicalEvent.objects.filter(document=document).values_list("icd10", "event_date"))
    events = 0
    for d in [] if dtype == "BILL" else result["diagnoses"]:
        if (d["icd10"] or "", doc_date) in kept:
            continue
        cls = classify_condition(d["icd10"], cfg, d["condition_text"])
        ClinicalEvent.objects.create(
            **here, event_date=doc_date, event_type="DIAGNOSIS", condition_text=d["condition_text"], icd10=d["icd10"] or "",
            condition_group=cls["group"], category=cls["category"], severity=severity, is_provisional=d["is_provisional"],
            evidence=d["evidence"], source="EXTRACTED")
        events += 1

    for m in result["measurements"]:
        GrowthMeasurement.objects.create(**here, source="extracted", measured_on=m["measured_on"], weight_kg=m["weight_kg"],
                                         height_cm=m["height_cm"], head_circumference_cm=m["head_circ_cm"])

    for v in result["vaccines"]:
        ImmunizationRecord.objects.create(
            **here, vaccine_name=v["vaccine_text"], vaccines=resolve_vaccines(v["vaccine_text"], cfg), administered_date=v["given_on"],
            source=ImmunizationRecord.SOURCE_EXTRACTED, verification_status=ImmunizationRecord.STATUS_PENDING)

    for lab in result["labs"]:
        judged = evaluate_lab(lab["analyte"], lab["value"], (lab["collected_on"] - dob).days, cfg)
        LabResult.objects.create(**here, analyte=lab["analyte"], test_name=lab["test_name"], value=lab["value"], unit_raw=lab["unit_raw"],
                                 collected_on=lab["collected_on"], age_band=judged["band"] or "", severity=judged["severity"],
                                 direction=judged["direction"] or "")

    birth = result.get("birth_history")
    if birth:
        existing = BirthHistory.objects.filter(patient=patient).first()
        if not existing or existing.source == "EXTRACTED":
            weeks = birth["gestation_weeks"]
            BirthHistory.objects.update_or_create(patient=patient, defaults={
                "document": document, "source": "EXTRACTED", "source_hospital_id": hospital_id,
                "gestational_age_weeks": round(weeks) if weeks else None, "birth_weight_kg": birth["birth_weight_kg"],
                "delivery_mode": DELIVERY.get((birth["delivery"] or "").upper(), "unknown") if birth["delivery"] else "",
                "nicu_admission": bool(birth["nicu_admission"]), "nicu_days": birth["nicu_days"], "notes": birth["notes"] or ""})

    return {"events": events, "measurements": len(result["measurements"]), "vaccines": len(result["vaccines"]),
            "labs": len(result["labs"]), "admission": bool(admission or critical_terms), "birth_history": bool(birth)}


# ── one patient ────────────────────────────────────────────────────────────────

@transaction.atomic
def rebuild_patient(patient_id):
    cfg = load_config()
    patient = Patient.objects.get(pk=patient_id)
    dob, sex = ig.patient_dob_sex(patient)
    if dob is None:
        return {"episodes": 0, "recurrent": [], "growth_points": 0}

    rows = list(ClinicalEvent.objects.filter(patient=patient, event_type="DIAGNOSIS", is_rejected=False, event_date__isnull=False))
    for row in rows:
        cls = classify_condition(row.icd10, cfg, row.condition_text)
        row.condition_group, row.category = cls["group"], cls["category"]
        if row.source == "EXTRACTED" and not row.is_verified:
            row.is_provisional = is_uncertain(f"{row.condition_text} {row.evidence}")
    episodes = build_episodes([_event_in(r) for r in rows], cfg)

    HealthEpisode.objects.filter(patient=patient).delete()
    episode_of = {}
    for ep in episodes:
        saved = HealthEpisode.objects.create(
            patient=patient, key=ep.key, condition_group=ep.group, label=ep.label[:255], category=ep.category, start_date=ep.start,
            end_date=ep.end, last_seen=ep.last_seen, peak_severity=ep.peak_severity, event_count=ep.event_count,
            is_provisional=ep.is_provisional, known_group=ep.known_group)
        episode_of.update({event_id: saved for event_id in ep.event_ids})
    for row in rows:
        row.episode = episode_of.get(row.pk)
    ClinicalEvent.objects.bulk_update(rows, ["episode", "condition_group", "category", "is_provisional"])

    recurrent = {r["group"]: r for r in detect_recurrence(episodes, dob, date.today(), cfg) if r["is_recurrent"]}
    RecurrenceFlag.objects.filter(patient=patient).exclude(condition_group__in=recurrent).delete()
    for group, r in recurrent.items():
        RecurrenceFlag.objects.update_or_create(patient=patient, condition_group=group, defaults={
            "label": r["label"][:255], "triggered_on": r["triggered_on"], "rule": r["rule"],
            "episodes_last_12m": r["episodes_last_12m"], "clinical_hint": r["clinical_hint"] or ""})

    corrected = growth_dob(dob, BirthHistory.objects.filter(patient=patient).first())
    measurements = list(GrowthMeasurement.objects.filter(patient=patient, is_rejected=False))
    for g in measurements:
        scored = score_measurement(_growth_dob_on(g.measured_on, dob, corrected), sex, g.measured_on, _measures(g), cfg)
        g.flags = {}
        for column, z_column, pct_column in GROWTH_COLUMNS:
            m = scored.get(SCORED_AS.get(column, column)) or {}
            setattr(g, z_column, m.get("z"))
            setattr(g, pct_column, m.get("percentile"))
            if m.get("flag"):
                g.flags[column] = m["flag"]
            if m.get("source"):
                g.reference_source = m["source"]
    GrowthMeasurement.objects.bulk_update(measurements, ["weight_z", "height_z", "head_circ_z", "weight_pct", "height_pct",
                                                         "head_circ_pct", "flags", "reference_source"])
    return {"episodes": len(episodes), "recurrent": list(recurrent), "growth_points": len(measurements)}


# ── the timeline ───────────────────────────────────────────────────────────────

def build_timeline_payload(patient, p_from, p_to, audience="guardian", hospital_id=None):
    """`hospital_id`: only what that hospital wrote or read (for a patient who has not agreed to share across hospitals)."""
    cfg = load_config()
    dob, sex = ig.patient_dob_sex(patient)
    own = {"source_hospital_id": hospital_id} if hospital_id is not None else {}

    event_rows = list(ClinicalEvent.objects.filter(patient=patient, event_type="DIAGNOSIS", is_rejected=False, event_date__isnull=False, **own))
    episodes = build_episodes([_event_in(r) for r in event_rows], cfg)
    events_by_id = {r.pk: {"date": r.event_date, "severity": r.severity, "document_id": r.document_id,
                           "condition_text": r.condition_text, "is_verified": r.is_verified} for r in event_rows}
    recurrence = detect_recurrence(episodes, dob, min(p_to, date.today()), cfg)
    flag_ids = dict(RecurrenceFlag.objects.filter(patient=patient).values_list("condition_group", "pk"))
    for r in recurrence:
        r["id"] = flag_ids.get(r["group"])

    birth_row = BirthHistory.objects.filter(patient=patient).first()
    corrected = growth_dob(dob, birth_row)
    growth_points = []
    for g in GrowthMeasurement.objects.filter(patient=patient, is_rejected=False, **own).order_by("measured_on"):
        scored = score_measurement(_growth_dob_on(g.measured_on, dob, corrected), sex, g.measured_on, _measures(g), cfg)
        scored.update(measured_on=g.measured_on, document_id=g.document_id)
        growth_points.append(scored)

    given = [{"vaccine_text": v.vaccine_name, "given_on": v.administered_date, "document_id": v.document_id, "id": v.pk}
            for v in ImmunizationRecord.objects.filter(patient=patient, verification_status__in=SHOWN_VACCINES,
                                                       administered_date__isnull=False, **own)]
    admissions = [{"admitted_on": a.event_date, "discharged_on": a.discharged_on, "ward": a.ward, "is_critical": a.is_critical,
                   "reason": a.reason, "document_id": a.document_id}
                  for a in ClinicalEvent.objects.filter(patient=patient, event_type="ADMISSION", is_rejected=False, event_date__isnull=False, **own)]
    critical_labs = [{"date": lab.collected_on, "analyte": lab.analyte, "value": lab.value, "direction": lab.direction,
                      "severity": lab.severity, "document_id": lab.document_id}
                     for lab in LabResult.objects.filter(patient=patient, severity="CRITICAL", collected_on__isnull=False, **own)]
    birth = None
    if birth_row:
        weeks = birth_row.gestational_age_weeks
        birth = {"gestation_weeks": weeks, "birth_weight_kg": float(birth_row.birth_weight_kg) if birth_row.birth_weight_kg else None,
                 "nicu_admission": birth_row.nicu_admission, "nicu_days": birth_row.nicu_days, "delivery": birth_row.delivery_mode,
                 "preterm": bool(weeks and weeks < 37),
                 "low_birth_weight": bool(birth_row.birth_weight_kg and birth_row.birth_weight_kg < 2.5), "document_id": birth_row.document_id}

    payload = build_timeline(
        dob=dob, sex=sex, p_from=p_from, p_to=p_to, episodes=episodes, events_by_id=events_by_id, recurrence=recurrence,
        growth_points=growth_points, growth_alerts=detect_faltering(growth_points, cfg),
        immunization=immunization_status(dob, given, date.today(), cfg), admissions=admissions, critical_labs=critical_labs,
        birth_history=birth, audience=audience, cfg=cfg)
    payload["patient"]["uses_corrected_age"] = corrected != dob
    payload["patient"]["age_band"] = age_band((date.today() - dob).days, cfg)
    payload["pending_documents"] = DocumentExtraction.objects.filter(document__patient=patient, status=DocumentExtraction.Status.PENDING).count()
    return payload
