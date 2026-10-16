"""LLM extraction of pediatric clinical facts from already-OCR'd document text."""

import json
import logging
import re
from datetime import date, datetime
from typing import Callable, Optional

from django.conf import settings

from .clinical_rules import evaluate_lab, is_uncertain, resolve_analyte
from .config import load_config

logger = logging.getLogger(__name__)


MAX_CHUNK_CHARS = 9000
EXTRACTOR_VERSION = "peds-extract-1.0"

DOC_TYPE_HINTS = {
    "PRESCRIPTION": "Usually has weight (for dosing), sometimes height/head circumference, "
                    "a diagnosis line (Dx / Imp / Diagnosis / c/o) and medicines. Vaccines may be noted.",
    "LAB": "Mostly lab values. Extract every result with its unit and collection date. "
           "Diagnoses are rare - only extract if the report states one explicitly.",
    "DISCHARGE_SUMMARY": "Has admission/discharge dates, final diagnosis, course in hospital "
                         "(ICU/PICU/NICU stay, ventilation), and for newborns the birth history.",
    "BILL": "Use only for admission dates and ward type (ICU/PICU/NICU charges). "
            "Do not infer diagnoses from billed items.",
    "VACCINATION_CARD": "A table of vaccines with dates given. Extract every row that has a date.",
    "OTHER": "Extract whatever of the schema is clearly present.",
}

SYSTEM_PROMPT = """You extract structured clinical facts from Indian pediatric medical documents.
Return ONLY one JSON object, no prose, matching exactly this schema:
{
  "document_date": "YYYY-MM-DD or null",
  "birth_history": {"gestation_weeks": number|null, "birth_weight_kg": number|null,
                    "nicu_admission": true|false|null, "nicu_days": number|null,
                    "delivery": "NVD|LSCS|instrumental|null", "notes": "short text or null"} | null,
  "measurements": [{"measured_on": "YYYY-MM-DD|null", "weight": number|null, "weight_unit": "kg|g|lb",
                    "height": number|null, "height_unit": "cm|m|in",
                    "head_circ": number|null, "head_circ_unit": "cm|in"}],
  "diagnoses": [{"condition": "full name", "icd10_guess": "e.g. J06.9 or null",
                 "is_provisional": true|false, "is_current_patient_condition": true|false,
                 "evidence": "<= 12 words copied from the text"}],
  "admission": {"admitted_on": "YYYY-MM-DD|null", "discharged_on": "YYYY-MM-DD|null",
                "ward": "WARD|ICU|PICU|NICU|null", "evidence": "<= 12 words"} | null,
  "labs": [{"test_name": "as written", "value": number, "unit": "as written",
            "collected_on": "YYYY-MM-DD|null"}],
  "vaccines": [{"vaccine_text": "as written incl. dose no.", "given_on": "YYYY-MM-DD|null"}]
}
Rules:
- Indian dates are DD/MM/YYYY. Convert to YYYY-MM-DD.
- Expand abbreviations: URTI, LRTI, AGE (acute gastroenteritis), AOM, WALRI, BA (bronchial asthma),
  UTI, TOF, VSD, ASD, PDA, CP, NS (nephrotic syndrome), FTT, IDA, SAM/MAM, "K/C/O" = known case of.
- Febrile seizure / febrile convulsion is NOT epilepsy. Wheeze / WALRI is NOT asthma unless asthma is written.
- "?", "r/o", "suspected", "probable", "provisional" => is_provisional true.
- EXCLUDE negated findings ("no h/o seizures"), family history ("mother asthmatic") and ruled-out
  conditions - set is_current_patient_condition false if unsure, never invent.
- Do NOT classify chronic/acute or severity. Do NOT add facts not present in the text.
- Use empty arrays / null when absent."""


def build_user_prompt(doc_type: str, text: str, patient_dob: Optional[date]) -> str:
    hint = DOC_TYPE_HINTS.get(doc_type, DOC_TYPE_HINTS["OTHER"])
    dob = patient_dob.isoformat() if patient_dob else "unknown"
    return (f"Document type: {doc_type}\nHint: {hint}\nChild's date of birth: {dob}\n"
            f"--- DOCUMENT TEXT ---\n{text}\n--- END ---")


# ------------------------------------------------------------------ LLM call
def ask_llm(system: str, user: str, timeout: int = 180) -> str:
    """The same prompt to the company LLM api (settings.LLM_API_URL, token auth, {"user_prompt": ...} in, the answer text"""
    import requests

    prompt = f"{system}\n\n{user}"
    if settings.LLM_API_STYLE == "ollama":
        resp = requests.post(
            settings.LLM_API_URL,
            json={"model": settings.LLM_API_MODEL, "messages": [{"role": "user", "content": prompt}], "stream": False, "format": "json"},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]
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


def _parse_json(raw: str) -> dict:
    raw = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.S).strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("LLM returned no JSON object")
    return json.loads(raw[start:end + 1])


def _chunks(text: str, size: int = MAX_CHUNK_CHARS):
    if len(text) <= size:
        return [text]
    parts, buf = [], ""
    for para in re.split(r"\n\s*\n", text):
        if len(buf) + len(para) > size and buf:
            parts.append(buf)
            buf = ""
        buf += para + "\n\n"
    if buf.strip():
        parts.append(buf)
    return parts


def _merge(results):
    merged = {"document_date": None, "birth_history": None, "measurements": [],
              "diagnoses": [], "admission": None, "labs": [], "vaccines": []}
    for r in results:
        merged["document_date"] = merged["document_date"] or r.get("document_date")
        merged["birth_history"] = merged["birth_history"] or r.get("birth_history")
        merged["admission"] = merged["admission"] or r.get("admission")
        for k in ("measurements", "diagnoses", "labs", "vaccines"):
            merged[k].extend(r.get(k) or [])
    return merged


# ------------------------------------------------------------ normalisation
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%b-%Y", "%d %b %Y")


def parse_date(value) -> Optional[date]:
    if not value or not isinstance(value, str):
        return None
    v = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


def _num(v) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"-?\d+(\.\d+)?", str(v).replace(",", ""))
    return float(m.group()) if m else None


def normalise_weight(value, unit) -> Optional[float]:
    v = _num(value)
    if v is None:
        return None
    unit = (unit or "kg").lower()
    if unit.startswith("g") or v > 200:          # 3250 -> grams
        v = v / 1000
    elif unit.startswith("lb"):
        v = v * 0.45359237
    return round(v, 3)


def normalise_length(value, unit) -> Optional[float]:
    v = _num(value)
    if v is None:
        return None
    unit = (unit or "cm").lower()
    if unit in ("m", "mtr", "metre", "meter") or (v < 2.5 and unit != "in"):
        v = v * 100
    elif unit in ("in", "inch", "inches"):
        v = v * 2.54
    return round(v, 1)


def normalise_lab_value(analyte: str, value, unit: str) -> Optional[float]:
    v = _num(value)
    if v is None:
        return None
    u = (unit or "").lower().replace(" ", "")
    if analyte in ("PLATELETS_PER_UL", "WBC_PER_UL"):
        if "lakh" in u:
            v *= 100000
        elif any(t in u for t in ("10^3", "10³", "x10e3", "thou", "k/")) or (v < 1000 and analyte == "PLATELETS_PER_UL"):
            v *= 1000
    elif analyte == "HEMOGLOBIN_G_DL" and ("g/l" in u and "dl" not in u):
        v /= 10
    elif analyte == "GLUCOSE_MG_DL" and "mmol" in u:
        v *= 18.016
    return round(v, 2)


def _in_range(v, rng):
    return v is not None and rng[0] <= v <= rng[1]


def normalise(raw: dict, dob: Optional[date], upload_date: date, cfg=None) -> dict:
    """Clean LLM output. Drops implausible values and records why in `warnings`."""
    cfg = cfg or load_config()
    ranges = cfg["growth"]["plausible_ranges"]
    warnings = []
    today = date.today()

    def valid_date(d):
        if d is None:
            return None
        if d > today or (dob and d < dob):
            warnings.append(f"date out of range: {d}")
            return None
        return d

    doc_date = valid_date(parse_date(raw.get("document_date")))
    date_source = "DOCUMENT" if doc_date else "UPLOAD"
    doc_date = doc_date or upload_date

    out = {"document_date": doc_date, "date_source": date_source, "birth_history": None,
           "measurements": [], "diagnoses": [], "admission": None, "labs": [],
           "vaccines": [], "warnings": warnings}

    bh = raw.get("birth_history") or None
    if bh and (any(bh.get(k) is not None for k in ("gestation_weeks", "birth_weight_kg")) or bh.get("nicu_admission") is True):
        gw = _num(bh.get("gestation_weeks"))
        bw = normalise_weight(bh.get("birth_weight_kg"), "kg")
        out["birth_history"] = {
            "gestation_weeks": gw if gw and 22 <= gw <= 44 else None,
            "birth_weight_kg": bw if bw and 0.4 <= bw <= 6.5 else None,
            "nicu_admission": bh.get("nicu_admission"),
            "nicu_days": int(_num(bh.get("nicu_days"))) if _num(bh.get("nicu_days")) is not None else None,
            "delivery": bh.get("delivery"),
            "notes": (bh.get("notes") or "")[:250] or None,
        }

    for m in raw.get("measurements") or []:
        rec = {
            "measured_on": valid_date(parse_date(m.get("measured_on"))) or doc_date,
            "weight_kg": normalise_weight(m.get("weight"), m.get("weight_unit")),
            "height_cm": normalise_length(m.get("height"), m.get("height_unit")),
            "head_circ_cm": normalise_length(m.get("head_circ"), m.get("head_circ_unit")),
        }
        for k in ("weight_kg", "height_cm", "head_circ_cm"):
            if rec[k] is not None and not _in_range(rec[k], ranges[k]):
                warnings.append(f"implausible {k}={rec[k]} dropped")
                rec[k] = None
        if any(rec[k] is not None for k in ("weight_kg", "height_cm", "head_circ_cm")):
            out["measurements"].append(rec)

    for d in raw.get("diagnoses") or []:
        if not d.get("is_current_patient_condition", True):
            continue
        cond = (d.get("condition") or "").strip()
        if not cond:
            continue
        out["diagnoses"].append({
            "condition_text": cond[:255],
            "icd10": (d.get("icd10_guess") or "").strip().upper()[:10] or None,
            "is_provisional": is_uncertain(f"{cond} {d.get('evidence') or ''}"),
            "evidence": (d.get("evidence") or "")[:255],
        })

    adm = raw.get("admission") or None
    if adm and (adm.get("admitted_on") or adm.get("ward")):
        out["admission"] = {
            "admitted_on": valid_date(parse_date(adm.get("admitted_on"))) or doc_date,
            "discharged_on": valid_date(parse_date(adm.get("discharged_on"))),
            "ward": (adm.get("ward") or "WARD").upper(),
            "evidence": (adm.get("evidence") or "")[:255],
        }

    for lab in raw.get("labs") or []:
        analyte = resolve_analyte(lab.get("test_name", ""), cfg)
        if not analyte:
            continue  # only configured analytes matter for the timeline
        val = normalise_lab_value(analyte, lab.get("value"), lab.get("unit"))
        if val is None:
            continue
        out["labs"].append({
            "analyte": analyte, "test_name": (lab.get("test_name") or "")[:100],
            "value": val, "unit_raw": (lab.get("unit") or "")[:30],
            "collected_on": valid_date(parse_date(lab.get("collected_on"))) or doc_date,
        })

    for v in raw.get("vaccines") or []:
        given = valid_date(parse_date(v.get("given_on")))
        if v.get("vaccine_text") and given:
            out["vaccines"].append({"vaccine_text": v["vaccine_text"][:100], "given_on": given})

    return out


def extract_document(text: str, doc_type: str, dob: Optional[date], upload_date: date,
                     llm: Optional[Callable[[str, str], str]] = None, cfg=None) -> dict:
    cfg = cfg or load_config()
    llm = llm or ask_llm
    results = []
    for chunk in _chunks(text or ""):
        raw = llm(SYSTEM_PROMPT, build_user_prompt(doc_type, chunk, dob))
        try:
            results.append(_parse_json(raw))
        except (ValueError, json.JSONDecodeError) as exc:
            logger.warning("extraction JSON parse failed: %s", exc)
    if not results:
        raise ValueError("no parseable extraction output")
    return normalise(_merge(results), dob, upload_date, cfg)


def lab_severity(lab: dict, dob: date, cfg=None) -> dict:
    age_days = (lab["collected_on"] - dob).days
    return evaluate_lab(lab["analyte"], lab["value"], age_days, cfg)
