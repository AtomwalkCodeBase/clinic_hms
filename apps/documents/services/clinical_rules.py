"""
Deterministic clinical rules: age bands, condition grouping, lab thresholds,
critical-keyword detection. No Django imports - unit-testable on its own.

The LLM only *extracts* facts. Every judgement (chronic vs acute, critical or
not, recurrent or not) is made here from the reviewed config, so the numbers
on the timeline are reproducible and auditable.
"""

import re
from datetime import date
from typing import Optional

from .config import load_config


SEVERITY_ORDER = {"NORMAL": 0, "MILD": 1, "ABNORMAL": 2, "CRITICAL": 3}


# --------------------------------------------------------------------------- age
def age_in_days(dob: date, on: date) -> int:
    return (on - dob).days


def age_in_months(dob: date, on: date) -> float:
    """Fractional months using the WHO convention (30.4375 days per month)."""
    return age_in_days(dob, on) / 30.4375


def age_band(age_days: int, cfg=None) -> str:
    cfg = cfg or load_config()
    for band in cfg["age_bands"]:
        if band["min_days"] <= age_days <= band["max_days"]:
            return band["code"]
    return cfg["age_bands"][-1]["code"]


def format_age(age_days: int) -> str:
    """Human label as pediatricians say it: '12 days', '7 months', '2 y 3 m'."""
    if age_days < 0:
        return "before birth"
    if age_days == 0:
        return "Birth"
    if age_days <= 28:
        return f"{age_days} day{'s' if age_days != 1 else ''}"
    if age_days < 16 * 7 and age_days % 7 == 0:   # vaccine-style "6 weeks", "14 weeks"
        return f"{age_days // 7} weeks"
    months = int(age_days / 30.4375)
    if months < 24:
        return f"{months} month{'s' if months != 1 else ''}"
    years, rem = divmod(months, 12)
    return f"{years} y {rem} m" if rem else f"{years} y"


# ------------------------------------------------------------ condition groups
def _group_items(cfg):
    return {k: v for k, v in cfg["condition_groups"].items() if not k.startswith("_")}


def normalise_icd(code: Optional[str]) -> str:
    if not code:
        return ""
    code = code.strip().upper().replace(" ", "")
    # "J069" -> "J06.9"
    if re.fullmatch(r"[A-Z]\d{3,4}", code):
        code = f"{code[:3]}.{code[3:]}"
    return code


def condition_group_for_icd(icd10: Optional[str], cfg=None) -> Optional[str]:
    """Longest matching ICD prefix wins (so 'K90.0' beats a broader 'K')."""
    cfg = cfg or load_config()
    code = normalise_icd(icd10)
    if not code:
        return None
    best, best_len = None, -1
    for group, spec in _group_items(cfg).items():
        for prefix in spec["icd_prefixes"]:
            p = prefix.upper()
            if code.startswith(p) and len(p) > best_len:
                best, best_len = group, len(p)
    return best


UNCERTAIN = re.compile(r"\?|\br/o\b|rule[ -]?out|suspect|probable|provisional|possible|likely|considered|differential|query", re.I)


def is_uncertain(text: str) -> bool:
    """A condition is provisional only when the report's own words hedge it ("? dengue", "r/o UTI", "suspected"); the LLM's
    own guess at that is not trusted, so the same words always give the same answer."""
    return bool(UNCERTAIN.search(text or ""))


def condition_group_for_text(text: Optional[str], cfg=None) -> Optional[str]:
    """The group whose alias words are in the condition's name (longest alias wins), for when the ICD code is missing or unknown."""
    cfg = cfg or load_config()
    name = (text or "").lower()
    best, best_len = None, 0
    for group, spec in _group_items(cfg).items():
        for alias in spec.get("aliases", []):
            if len(alias) > best_len and re.search(rf"\b{re.escape(alias.lower())}\b", name):
                best, best_len = group, len(alias)
    return best


def classify_condition(icd10: Optional[str], cfg=None, text: str = "") -> dict:
    """
    -> {"group": "ASTHMA", "label": "Asthma", "category": "CHRONIC", "merge_days": None}
    The group comes from the ICD code, else from the words of the condition's name. Unknown ones default to ACUTE
    with their own ICD 3-char stem as the group, so they still get episode grouping; they are surfaced for config review.
    """
    cfg = cfg or load_config()
    group = condition_group_for_icd(icd10, cfg) or condition_group_for_text(text, cfg)
    if group:
        spec = cfg["condition_groups"][group]
        return {
            "group": group,
            "label": spec["label"],
            "category": spec["category"],
            "merge_days": spec.get("merge_days", cfg.get("default_acute_merge_days", 14)),
            "known": True,
        }
    stem = normalise_icd(icd10)[:3] or "UNCODED"
    return {
        "group": f"ICD_{stem}",
        "label": None,
        "category": "ACUTE",
        "merge_days": cfg.get("default_acute_merge_days", 14),
        "known": False,
    }


# ------------------------------------------------------------------ lab values
def resolve_analyte(test_name: str, cfg=None) -> Optional[str]:
    cfg = cfg or load_config()
    name = re.sub(r"[^a-z0-9 .\-]", "", (test_name or "").lower()).strip()
    if not name:
        return None
    best, best_len = None, 0
    for analyte, spec in cfg["lab_thresholds"].items():
        if analyte.startswith("_"):
            continue
        for alias in spec.get("aliases", []):
            a = alias.lower()
            # whole-word match; longest alias wins ("total bilirubin" over "bilirubin")
            if re.search(rf"(^|\b){re.escape(a)}(\b|$)", name) and len(a) > best_len:
                best, best_len = analyte, len(a)
    return best


def evaluate_lab(analyte: str, value: float, age_days: int, cfg=None) -> dict:
    """
    -> {"severity": "CRITICAL"|"ABNORMAL"|"NORMAL", "direction": "LOW"|"HIGH"|None,
        "band": "INFANT", "limits": {...}}
    """
    cfg = cfg or load_config()
    spec = cfg["lab_thresholds"].get(analyte)
    if spec is None or value is None:
        return {"severity": "NORMAL", "direction": None, "band": None, "limits": {}}
    band = age_band(age_days, cfg)
    limits = spec.get(band) or spec.get("DEFAULT") or {}
    sev, direction = "NORMAL", None
    if "critical_low" in limits and value < limits["critical_low"]:
        sev, direction = "CRITICAL", "LOW"
    elif "critical_high" in limits and value > limits["critical_high"]:
        sev, direction = "CRITICAL", "HIGH"
    elif "low" in limits and value < limits["low"]:
        sev, direction = "ABNORMAL", "LOW"
    elif "high" in limits and value > limits["high"]:
        sev, direction = "ABNORMAL", "HIGH"
    return {"severity": sev, "direction": direction, "band": band, "limits": limits}


# ----------------------------------------------------------- critical keywords
def find_critical_keywords(text: str, cfg=None) -> list:
    """Whole-word, case-insensitive. Skips negated mentions ('no ICU stay', 'not intubated')."""
    cfg = cfg or load_config()
    if not text:
        return []
    lowered = text.lower()
    hits = []
    for term in cfg["critical_keywords"]["terms"]:
        for m in re.finditer(rf"\b{re.escape(term.lower())}\b", lowered):
            window = lowered[max(0, m.start() - 25):m.start()]
            if re.search(r"\b(no|not|without|nil|denies|never)\b[^.;]*$", window):
                continue
            hits.append(term)
            break
    return sorted(set(hits))


def max_severity(*severities) -> str:
    vals = [s for s in severities if s]
    return max(vals, key=lambda s: SEVERITY_ORDER.get(s, 0)) if vals else "NORMAL"
