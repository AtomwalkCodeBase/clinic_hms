"""
Pure-Python tests for the rule engine. Run without Django:
    python -m pytest pediatric_health/tests/test_services.py -q
"""
import csv
import json
from datetime import date, timedelta

import pytest

from apps.documents.services import growth
from apps.documents.services.clinical_rules import (
    age_band, classify_condition, evaluate_lab, find_critical_keywords, format_age,
    resolve_analyte)
from apps.documents.services.config import load_config
from apps.documents.services.episodes import EventIn, build_episodes, detect_recurrence
from apps.documents.services.extraction import extract_document, normalise_lab_value
from apps.documents.services.immunization import immunization_status, resolve_vaccines
from apps.documents.services.timeline import build_timeline

CFG = load_config()
DOB = date(2023, 1, 10)


# ----------------------------------------------------------------- rules
def test_age_bands_and_labels():
    assert age_band(10, CFG) == "NEONATE"
    assert age_band(200, CFG) == "INFANT"
    assert age_band(800, CFG) == "TODDLER"
    assert age_band(7000, CFG) == "ADULT"
    assert format_age(12) == "12 days"
    assert format_age(220) == "7 months"
    assert format_age(1000) == "2 y 8 m"
    assert format_age(0) == "Birth" and format_age(42) == "6 weeks" and format_age(98) == "14 weeks"


def test_condition_classification():
    assert classify_condition("J45.909", CFG)["category"] == "CHRONIC"
    assert classify_condition("R56.0", CFG)["group"] == "FEBRILE_SEIZURE"   # not epilepsy
    assert classify_condition("G40.3", CFG)["group"] == "EPILEPSY"
    assert classify_condition("j069", CFG)["group"] == "URTI"               # normalised
    unk = classify_condition("Z99.9", CFG)
    assert unk["category"] == "ACUTE" and unk["known"] is False


def test_age_banded_lab_thresholds():
    # glucose 45 is critical for an infant but only low for a neonate
    assert evaluate_lab("GLUCOSE_MG_DL", 45, 10, CFG)["severity"] == "ABNORMAL"
    assert evaluate_lab("GLUCOSE_MG_DL", 45, 300, CFG)["severity"] == "CRITICAL"
    # bilirubin 15 is abnormal for a neonate, critical for an older child
    assert evaluate_lab("BILIRUBIN_TOTAL_MG_DL", 15, 5, CFG)["severity"] == "ABNORMAL"
    assert evaluate_lab("BILIRUBIN_TOTAL_MG_DL", 15, 2000, CFG)["severity"] == "CRITICAL"
    assert resolve_analyte("S. Bilirubin Total", CFG) == "BILIRUBIN_TOTAL_MG_DL"
    assert resolve_analyte("Platelet Count", CFG) == "PLATELETS_PER_UL"


def test_lab_unit_normalisation():
    assert normalise_lab_value("PLATELETS_PER_UL", "0.18", "lakhs/cumm") == 18000
    assert normalise_lab_value("PLATELETS_PER_UL", 95, "10^3/uL") == 95000
    assert normalise_lab_value("GLUCOSE_MG_DL", 2.5, "mmol/L") == pytest.approx(45.04, 0.01)


def test_critical_keywords_skip_negation():
    assert find_critical_keywords("Shifted to PICU, put on CPAP", CFG) == ["cpap", "picu"]
    assert find_critical_keywords("Child stable, no ICU stay required", CFG) == []


# --------------------------------------------------------------- episodes
def _ev(i, d, icd, sev="NORMAL", prov=False):
    return EventIn(id=i, event_date=d, icd10=icd, severity=sev, is_provisional=prov, document_id=100 + i)


def test_chronic_is_single_episode_and_acute_merges():
    evs = [
        _ev(1, date(2024, 1, 1), "J45.9"),
        _ev(2, date(2024, 6, 1), "J45.9", "CRITICAL"),
        _ev(3, date(2025, 2, 1), "J45.9"),
        _ev(4, date(2024, 3, 1), "J06.9"),
        _ev(5, date(2024, 3, 6), "J06.9"),     # follow-up visit -> same episode
        _ev(6, date(2024, 4, 20), "J06.9"),    # new cold
    ]
    eps = build_episodes(evs, CFG)
    asthma = [e for e in eps if e.group == "ASTHMA"]
    urti = [e for e in eps if e.group == "URTI"]
    assert len(asthma) == 1 and asthma[0].event_count == 3
    assert asthma[0].end is None and asthma[0].peak_severity == "CRITICAL"
    assert len(urti) == 2 and urti[0].event_count == 2


def test_provisional_chronic_onset_moves_to_confirmed_date():
    evs = [_ev(1, date(2024, 1, 1), "E10.9", prov=True), _ev(2, date(2024, 2, 1), "E10.9")]
    ep = build_episodes(evs, CFG)[0]
    assert ep.start == date(2024, 2, 1) and not ep.is_provisional


def test_recurrent_otitis_media_detected():
    starts = [date(2024, 1, 5), date(2024, 3, 1), date(2024, 5, 20)]   # 3 in < 6 months
    evs = [_ev(i, d, "H66.9") for i, d in enumerate(starts, 1)]
    rec = detect_recurrence(build_episodes(evs, CFG), DOB, date(2024, 8, 1), CFG)
    om = next(r for r in rec if r["group"] == "OTITIS_MEDIA")
    assert om["is_recurrent"] and om["triggered_on"] == "2024-05-20"
    assert om["rule"] == {"min_count": 3, "window_months": 6}


def test_wheeze_rule_respects_age_limit():
    older = date(2015, 1, 1)  # > 5 y at these dates
    starts = [date(2024, 1, 5), date(2024, 4, 1), date(2024, 8, 1)]
    evs = [_ev(i, d, "R06.2") for i, d in enumerate(starts, 1)]
    eps = build_episodes(evs, CFG)
    assert detect_recurrence(eps, DOB, date(2024, 12, 1), CFG)[0]["is_recurrent"]
    assert not detect_recurrence(eps, older, date(2024, 12, 1), CFG)[0]["is_recurrent"]


def test_urti_typical_for_age_context():
    starts = [date(2024, m, 3) for m in (1, 3, 5, 7, 9, 11)]
    evs = [_ev(i, d, "J06.9") for i, d in enumerate(starts, 1)]
    rec = detect_recurrence(build_episodes(evs, CFG), DOB, date(2024, 12, 1), CFG)[0]
    assert not rec["is_recurrent"] and rec["context"] == "typical for age"


def test_provisional_episodes_excluded_from_recurrence():
    starts = [date(2024, 1, 5), date(2024, 3, 1), date(2024, 5, 20)]
    evs = [_ev(i, d, "H66.9", prov=True) for i, d in enumerate(starts, 1)]
    assert detect_recurrence(build_episodes(evs, CFG), DOB, date(2024, 8, 1), CFG) == []


# ------------------------------------------------------------------ growth
@pytest.fixture
def ref_dir(tmp_path):
    # synthetic LMS table: M grows linearly, constant L/S - enough to test the maths
    for ind, m0, slope in (("wfa", 3.3, 0.3), ("lhfa", 50.0, 1.5), ("hcfa", 34.5, 0.5)):
        for sex in ("male", "female"):
            with open(tmp_path / f"{ind}_{sex}_who.csv", "w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["age_months", "L", "M", "S"])
                for a in range(0, 61):
                    w.writerow([a, 0.2, m0 + slope * a, 0.1])
    growth.get_table.cache_clear()
    return str(tmp_path)


def test_lms_round_trip(ref_dir):
    L, M, S = 0.2, 10.0, 0.1
    for z in (-3, -2, 0, 1.5, 2.5):
        assert growth.lms_z(growth.lms_value(L, M, S, z), L, M, S) == pytest.approx(z, abs=1e-6)
    assert growth.z_to_percentile(0) == pytest.approx(50)
    assert growth.z_to_percentile(-2) == pytest.approx(2.28, abs=0.01)


def test_score_measurement_flags_low_weight(ref_dir):
    on = DOB + timedelta(days=365)
    age_m = 365 / 30.4375
    m = 3.3 + 0.3 * age_m
    low = growth.lms_value(0.2, m, 0.1, -2.5)
    r = growth.score_measurement(DOB, "male", on, {"weight_kg": low, "height_cm": 50 + 1.5 * age_m},
                                 CFG, ref_dir)
    assert r["weight_kg"]["flag"] == "LOW"
    assert r["height_cm"]["z"] == pytest.approx(0, abs=0.01)


def test_faltering_detected(ref_dir):
    pts = []
    for months, z in ((6, 0.5), (8, 0.1), (10, -0.6)):
        on = DOB + timedelta(days=int(months * 30.4375))
        m = 3.3 + 0.3 * months
        r = growth.score_measurement(DOB, "male", on, {"weight_kg": growth.lms_value(0.2, m, 0.1, z)},
                                     CFG, ref_dir)
        r["measured_on"] = on
        pts.append(r)
    alerts = growth.detect_faltering(pts, CFG)
    assert len(alerts) == 1 and alerts[0]["drop"] >= 1.0


# ------------------------------------------------------------ immunization
def test_vaccine_resolution():
    assert resolve_vaccines("Hexaxim 2", CFG) == ["DTwP/DTaP", "Hepatitis B", "Hib", "IPV"]
    assert resolve_vaccines("Rotavac-1", CFG) == ["Rotavirus"]
    assert resolve_vaccines("MMR 1st dose", CFG) == ["MMR"]


def test_immunization_status():
    given = [
        {"vaccine_text": "BCG", "given_on": DOB, "document_id": 1},
        {"vaccine_text": "Hep B birth dose", "given_on": DOB, "document_id": 1},
        {"vaccine_text": "OPV 0", "given_on": DOB, "document_id": 1},
        {"vaccine_text": "Hexaxim 1", "given_on": DOB + timedelta(days=44), "document_id": 2},
        {"vaccine_text": "Rotavac 1", "given_on": DOB + timedelta(days=44), "document_id": 2},
        {"vaccine_text": "PCV 1", "given_on": DOB + timedelta(days=44), "document_id": 2},
        {"vaccine_text": "something illegible", "given_on": DOB + timedelta(days=44)},
    ]
    st = immunization_status(DOB, given, as_of=DOB + timedelta(days=150), cfg=CFG)
    rows = {r["code"]: r for r in st["rows"]}
    assert rows["BCG"]["status"] == "GIVEN"
    assert rows["IPV1"]["status"] == "GIVEN"        # from the hexavalent shot
    assert rows["HEPB2"]["status"] == "GIVEN"
    assert rows["DTP2"]["status"] == "OVERDUE"      # due day 70, grace 28
    assert rows["FLU1"]["status"] == "UPCOMING"
    assert st["unresolved"][0]["vaccine_text"] == "something illegible"
    assert st["summary"]["overdue"] > 0


# --------------------------------------------------------------- extraction
def test_extraction_normalises_llm_output():
    fake = {
        "document_date": "14/03/2024",
        "measurements": [{"weight": 8950, "weight_unit": "g", "height": 72, "height_unit": "cm",
                          "head_circ": 44.5, "head_circ_unit": "cm"}],
        "diagnoses": [
            {"condition": "Acute otitis media", "icd10_guess": "H66.9", "is_provisional": False,
             "is_current_patient_condition": True, "evidence": "Imp: AOM left"},
            {"condition": "Asthma", "icd10_guess": "J45", "is_provisional": False,
             "is_current_patient_condition": False, "evidence": "mother asthmatic"}],
        "labs": [{"test_name": "Platelet count", "value": "1.5", "unit": "lakhs/cumm"}],
        "vaccines": [{"vaccine_text": "MMR-1", "given_on": "10/10/2023"}],
    }
    llm = lambda s, u: "<think>reasoning...</think>" + json.dumps(fake)  # noqa: E731
    out = extract_document("...", "PRESCRIPTION", DOB, date(2024, 4, 1), llm=llm, cfg=CFG)
    assert out["document_date"] == date(2024, 3, 14) and out["date_source"] == "DOCUMENT"
    assert out["measurements"][0]["weight_kg"] == 8.95
    assert [d["icd10"] for d in out["diagnoses"]] == ["H66.9"]      # family history dropped
    assert out["labs"][0]["value"] == 150000
    assert out["vaccines"][0]["given_on"] == date(2023, 10, 10)


# ---------------------------------------------------------------- timeline
def test_timeline_payload_shape():
    evs = [_ev(1, date(2024, 1, 5), "H66.9"), _ev(2, date(2024, 3, 1), "H66.9"),
           _ev(3, date(2024, 5, 20), "H66.9"), _ev(4, date(2024, 2, 1), "J45.9")]
    eps = build_episodes(evs, CFG)
    rec = detect_recurrence(eps, DOB, date(2024, 8, 1), CFG)
    events_by_id = {e.id: {"date": e.event_date, "severity": e.severity,
                           "document_id": e.document_id, "condition_text": ""} for e in evs}
    imm = immunization_status(DOB, [], date(2024, 8, 1), CFG)
    payload = build_timeline(
        dob=DOB, sex="male", p_from=date(2024, 1, 1), p_to=date(2024, 8, 1),
        episodes=eps, events_by_id=events_by_id, recurrence=rec, growth_points=[],
        growth_alerts=[], immunization=imm,
        admissions=[{"admitted_on": date(2024, 3, 2), "discharged_on": date(2024, 3, 6),
                     "ward": "PICU", "is_critical": True, "document_id": 9}],
        critical_labs=[], birth_history={"gestation_weeks": 34}, cfg=CFG)
    s = payload["summary"]
    assert s["chronic_conditions"] == 1 and s["acute_episodes"] == 3
    assert s["recurrent_conditions"] == 1 and s["critical_events"] == 1
    lane_ids = [l["id"] for l in payload["lanes"]]
    assert lane_ids[0] == "birth" and "acute:OTITIS_MEDIA" in lane_ids
    om = next(l for l in payload["lanes"] if l["id"] == "acute:OTITIS_MEDIA")
    assert om["is_recurrent"] and om["category_label"] == "Happens often"


def test_doctor_audience_adds_clinical_fields_only_for_doctor():
    evs = [_ev(1, date(2024, 1, 5), "H66.9"), _ev(2, date(2024, 3, 1), "J45.9", prov=True)]
    eps = build_episodes(evs, CFG)
    events_by_id = {e.id: {"date": e.event_date, "severity": e.severity, "document_id": e.document_id,
                           "condition_text": "AOM", "icd10": e.icd10, "evidence": "Imp: AOM",
                           "is_provisional": e.is_provisional} for e in evs}
    common = dict(dob=DOB, sex="male", p_from=date(2024, 1, 1), p_to=date(2024, 8, 1), episodes=eps,
                  events_by_id=events_by_id, recurrence=[], growth_points=[], growth_alerts=[],
                  immunization={"rows": [], "summary": {}}, admissions=[], critical_labs=[],
                  birth_history=None, cfg=CFG)
    guardian = build_timeline(audience="guardian", **common)
    doctor = build_timeline(audience="doctor", **common)
    g_ev = next(l for l in guardian["lanes"] if l["type"] == "acute")["episodes"][0]["events"][0]
    assert "icd10" not in g_ev and "id" not in g_ev
    assert not any(l["type"] == "chronic" for l in guardian["lanes"])        # provisional hidden
    d_acute = next(l for l in doctor["lanes"] if l["type"] == "acute")["episodes"][0]
    assert d_acute["icd10_codes"] == ["H66.9"]
    assert d_acute["events"][0]["id"] == 1 and d_acute["events"][0]["evidence"] == "Imp: AOM"
    d_chronic = next(l for l in doctor["lanes"] if l["type"] == "chronic")["episode"]
    assert d_chronic["is_provisional"] and d_chronic["events"][0]["is_provisional"]
    assert d_chronic["peak_severity_label"] == "NORMAL"      # doctors get raw codes, not parent wording
