"""
The pediatric health timeline's rules, in plain Python (no database): the LLM only reads facts out of a document's text; everything
that judges them (chronic or acute, severity, episodes, recurrence, growth flags, vaccine status) is computed here from
health_config.json, so the same documents and the same config always give the same timeline.
"""
import csv
import json
import logging
import math
import re
from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, List, Optional

from django.conf import settings

logger = logging.getLogger(__name__)


# ── Configuration ───────────────────────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG_PATH = Path(__file__).with_name("health_config.json")
GROWTH_REFERENCE_DIR = Path(__file__).with_name("growth_reference")


def _resolve_path(path=None):
    return Path(path or getattr(settings, "PEDIATRIC_HEALTH_CONFIG", None) or DEFAULT_CONFIG_PATH)


def load_config(path=None):
    return _read_config(str(_resolve_path(path)))


@lru_cache(maxsize=4)
def _read_config(path):
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    _validate(cfg)
    return cfg


def _validate(cfg):
    required = ["age_bands", "lab_thresholds", "condition_groups",
                "recurrence_rules", "growth", "immunization_schedule"]
    missing = [k for k in required if k not in cfg]
    if missing:
        raise ValueError(f"pediatric_health_config missing keys: {missing}")
    groups = {k for k in cfg["condition_groups"] if not k.startswith("_")}
    unknown = [k for k in cfg["recurrence_rules"] if not k.startswith("_") and k not in groups]
    if unknown:
        raise ValueError(f"recurrence_rules reference unknown condition groups: {unknown}")


# ── Clinical rules: age bands, condition groups, lab limits, critical words ─────────────────────────────

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


# ── Episodes and recurrence ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EventIn:
    id: int
    event_date: date
    icd10: Optional[str]
    condition_text: str = ""
    severity: str = "NORMAL"
    is_provisional: bool = False
    document_id: Optional[int] = None
    event_type: str = "DIAGNOSIS"


@dataclass
class Episode:
    key: str
    group: str
    label: str
    category: str
    start: date
    end: Optional[date]
    last_seen: date
    peak_severity: str
    event_ids: List[int] = field(default_factory=list)
    document_ids: List[int] = field(default_factory=list)
    is_provisional: bool = True
    known_group: bool = True

    @property
    def event_count(self):
        return len(self.event_ids)

    def as_dict(self):
        return {
            "key": self.key, "group": self.group, "label": self.label,
            "category": self.category, "start": self.start.isoformat(),
            "end": self.end.isoformat() if self.end else None,
            "last_seen": self.last_seen.isoformat(),
            "peak_severity": self.peak_severity, "event_count": self.event_count,
            "event_ids": self.event_ids,
            "document_ids": sorted(set(d for d in self.document_ids if d)),
            "is_provisional": self.is_provisional, "known_group": self.known_group,
        }


def _absorb(ep: Episode, ev: EventIn):
    ep.event_ids.append(ev.id)
    if ev.document_id:
        ep.document_ids.append(ev.document_id)
    ep.last_seen = max(ep.last_seen, ev.event_date)
    ep.peak_severity = max_severity(ep.peak_severity, ev.severity)
    if not ev.is_provisional:
        ep.is_provisional = False


def build_episodes(events: List[EventIn], cfg=None) -> List[Episode]:
    cfg = cfg or load_config()
    events = sorted(events, key=lambda e: (e.event_date, e.id))
    chronic: dict = {}
    open_acute: dict = {}
    episodes: List[Episode] = []

    for ev in events:
        cls = classify_condition(ev.icd10, cfg, ev.condition_text)
        group = cls["group"]
        label = cls["label"] or ev.condition_text or group

        if cls["category"] == "CHRONIC":
            ep = chronic.get(group)
            if ep is None:
                ep = Episode(key=f"{group}", group=group, label=label, category="CHRONIC",
                             start=ev.event_date, end=None, last_seen=ev.event_date,
                             peak_severity="NORMAL", known_group=cls["known"])
                chronic[group] = ep
                episodes.append(ep)
            # A provisional first mention shouldn't fix the onset date once
            # a confirmed mention arrives.
            if ep.is_provisional and not ev.is_provisional:
                ep.start = ev.event_date
            _absorb(ep, ev)
            continue

        ep = open_acute.get(group)
        gap = (ev.event_date - ep.last_seen).days if ep else None
        if ep is None or gap > cls["merge_days"]:
            ep = Episode(key=f"{group}:{ev.event_date.isoformat()}", group=group, label=label,
                         category="ACUTE", start=ev.event_date, end=ev.event_date,
                         last_seen=ev.event_date, peak_severity="NORMAL",
                         known_group=cls["known"])
            open_acute[group] = ep
            episodes.append(ep)
        _absorb(ep, ev)
        ep.end = ep.last_seen

    return sorted(episodes, key=lambda e: (e.start, e.group))


# ------------------------------------------------------------------ recurrence
def _add_months(d: date, months: int) -> date:
    # month arithmetic without dateutil
    y, m = divmod(d.month - 1 + months, 12)
    y += d.year
    m += 1
    day = min(d.day, [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
    return date(y, m, day)


def detect_recurrence(episodes: List[Episode], dob: date, as_of: date, cfg=None) -> List[dict]:
    """
    Returns one entry per condition group that has an episode or a rule:
    {
      "group", "label", "is_recurrent", "triggered_on", "rule": {"min_count","window_months"},
      "episodes_last_12m", "expected_per_year", "context": "typical for age" | ...,
      "clinical_hint", "episode_keys": [...]
    }
    Only groups with at least one confirmed acute episode are returned.
    """
    cfg = cfg or load_config()
    rules = {k: v for k, v in cfg["recurrence_rules"].items() if not k.startswith("_")}
    by_group: dict = {}
    for ep in episodes:
        if ep.category != "ACUTE" or ep.is_provisional:
            continue
        by_group.setdefault(ep.group, []).append(ep)

    one_year_ago = as_of - timedelta(days=365)
    out = []
    for group, eps in by_group.items():
        eps.sort(key=lambda e: e.start)
        rule = rules.get(group, {})
        age_max = rule.get("age_max_days")
        considered = [e for e in eps
                      if age_max is None or age_in_days(dob, e.start) <= age_max]
        starts = [e.start for e in considered]

        triggered_on, trig_rule, trig_keys = None, None, []
        for win in rule.get("windows", []):
            n, months = win["min_count"], win["window_months"]
            for i, s in enumerate(starts):
                window_end = _add_months(s, months)
                j = bisect_left(starts, window_end)  # episodes with start < window_end
                if j - i >= n:
                    hit_date = starts[i + n - 1]  # the episode that completed the count
                    if triggered_on is None or hit_date < triggered_on:
                        triggered_on, trig_rule = hit_date, win
                        trig_keys = [e.key for e in considered[i:i + n]]
                    break

        last_12m = sum(1 for e in eps if e.start >= one_year_ago)
        expected = None
        if "expected_per_year" in rule:
            age_now_days = age_in_days(dob, as_of)
            exp = rule["expected_per_year"]
            expected = exp["under_5y"] if age_now_days < 1826 else exp["over_5y"]

        if triggered_on:
            context = "recurrent"
        elif expected is not None and last_12m <= expected:
            context = "typical for age"
        else:
            context = None

        out.append({
            "group": group,
            "label": eps[0].label,
            "is_recurrent": triggered_on is not None,
            "triggered_on": triggered_on.isoformat() if triggered_on else None,
            "rule": trig_rule,
            "episodes_total": len(eps),
            "episodes_last_12m": last_12m,
            "expected_per_year": expected,
            "context": context,
            "clinical_hint": rule.get("clinical_hint") if triggered_on else None,
            "episode_keys": trig_keys,
        })
    return sorted(out, key=lambda r: (not r["is_recurrent"], r["group"]))


# ── Growth: z-scores, percentiles, flags ────────────────────────────────────────────────────────────────

INDICATORS = {"weight_kg": "wfa", "height_cm": "lhfa", "head_circ_cm": "hcfa"}


@dataclass
class LMSTable:
    ages: List[float]
    L: List[float]
    M: List[float]
    S: List[float]

    def at(self, age_m: float):
        """Linear interpolation of L, M, S at a fractional age in months."""
        if age_m < self.ages[0] or age_m > self.ages[-1]:
            return None
        i = bisect_left(self.ages, age_m)
        if self.ages[i] == age_m or i == 0:
            return self.L[i], self.M[i], self.S[i]
        a0, a1 = self.ages[i - 1], self.ages[i]
        t = (age_m - a0) / (a1 - a0)
        lerp = lambda arr: arr[i - 1] + t * (arr[i] - arr[i - 1])  # noqa: E731
        return lerp(self.L), lerp(self.M), lerp(self.S)


def load_lms_csv(path: Path) -> LMSTable:
    ages, L, M, S = [], [], [], []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            ages.append(float(row["age_months"]))
            L.append(float(row["L"]))
            M.append(float(row["M"]))
            S.append(float(row["S"]))
    order = sorted(range(len(ages)), key=ages.__getitem__)
    return LMSTable([ages[i] for i in order], [L[i] for i in order],
                    [M[i] for i in order], [S[i] for i in order])


@lru_cache(maxsize=32)
def get_table(indicator: str, sex: str, source: str, ref_dir: str = None) -> Optional[LMSTable]:
    base = Path(ref_dir) if ref_dir else GROWTH_REFERENCE_DIR
    path = base / f"{indicator}_{sex}_{source}.csv"
    return load_lms_csv(path) if path.exists() else None


def table_for(indicator: str, sex: str, age_m: float, cfg=None, ref_dir=None):
    cfg = cfg or load_config()
    source = "who" if age_m <= cfg["growth"]["who_max_months"] else "iap"
    return get_table(indicator, sex, source, ref_dir), source


# ----------------------------------------------------------------- LMS maths
def lms_value(L: float, M: float, S: float, z: float) -> float:
    """Measurement value at a given z (used for drawing reference curves)."""
    if abs(L) < 1e-9:
        return M * math.exp(S * z)
    return M * (1 + L * S * z) ** (1 / L)


def lms_z(x: float, L: float, M: float, S: float, restricted: bool = False) -> float:
    if abs(L) < 1e-9:
        z = math.log(x / M) / S
    else:
        z = ((x / M) ** L - 1) / (L * S)
    if restricted and abs(z) > 3:
        # WHO restricted application for weight-based indicators: beyond +/-3 the
        # distance is measured in units of the SD between z=2 and z=3.
        sd3 = lms_value(L, M, S, 3 if z > 0 else -3)
        sd2 = lms_value(L, M, S, 2 if z > 0 else -2)
        sd23 = abs(sd3 - sd2)
        z = (3 + (x - sd3) / sd23) if z > 0 else (-3 + (x - sd3) / sd23)
    return z


def z_to_percentile(z: float) -> float:
    return 50 * (1 + math.erf(z / math.sqrt(2)))


def flag_for_z(z: Optional[float], cfg=None) -> Optional[str]:
    if z is None:
        return None
    flags = (cfg or load_config())["growth"]["flags"]
    if z <= flags["SEVERE_LOW"]["z_max"]:
        return "SEVERE_LOW"
    if z <= flags["LOW"]["z_max"]:
        return "LOW"
    if z >= flags["SEVERE_HIGH"]["z_min"]:
        return "SEVERE_HIGH"
    if z >= flags["HIGH"]["z_min"]:
        return "HIGH"
    return None


# --------------------------------------------------------------- per reading
def score_measurement(dob: date, sex: str, measured_on: date, values: Dict[str, Optional[float]],
                      cfg=None, ref_dir=None) -> dict:
    """
    values: {"weight_kg": 9.1, "height_cm": 74.0, "head_circ_cm": 45.2}
    -> {"age_months": 9.4, "weight_kg": {"value", "z", "percentile", "flag", "source"}, ...}
    """
    cfg = cfg or load_config()
    age_m = age_in_months(dob, measured_on)
    out = {"age_months": round(age_m, 2)}
    for field_name, indicator in INDICATORS.items():
        x = values.get(field_name)
        if x is None:
            continue
        table, source = table_for(indicator, sex, age_m, cfg, ref_dir)
        lms = table.at(age_m) if table else None
        if lms is None:
            out[field_name] = {"value": x, "z": None, "percentile": None, "flag": None,
                               "source": None}
            continue
        z = lms_z(x, *lms, restricted=(indicator == "wfa"))
        out[field_name] = {
            "value": x, "z": round(z, 2), "percentile": round(z_to_percentile(z), 1),
            "flag": flag_for_z(z, cfg), "source": source,
        }
    return out


def detect_faltering(scored: List[dict], cfg=None) -> List[dict]:
    """
    scored: chronologically sorted [{"measured_on": date, "weight_kg": {"z": ...}}, ...]
    A drop of >= faltering_drop_z in weight-for-age z within faltering_window_months
    between any two readings is reported once per starting reading.
    """
    cfg = cfg or load_config()
    drop = cfg["growth"]["faltering_drop_z"]
    window_m = cfg["growth"]["faltering_window_months"]
    pts = [(r["measured_on"], r["age_months"], r["weight_kg"]["z"])
           for r in scored if r.get("weight_kg") and r["weight_kg"].get("z") is not None]
    alerts, last_alert_end = [], None
    for i, (d0, a0, z0) in enumerate(pts):
        if last_alert_end and d0 < last_alert_end:
            continue
        for d1, a1, z1 in pts[i + 1:]:
            if a1 - a0 > window_m:
                break
            if z0 - z1 >= drop:
                alerts.append({"from": d0.isoformat(), "to": d1.isoformat(),
                               "z_from": z0, "z_to": z1, "drop": round(z0 - z1, 2)})
                last_alert_end = d1
                break
    return alerts


# ----------------------------------------------------------- reference curves
def reference_curves(indicator: str, sex: str, max_months: float,
                     zs=(-3, -2, 0, 2, 3), step: float = 1.0, cfg=None, ref_dir=None) -> dict:
    """Points for drawing WHO/IAP bands under the child's own line."""
    cfg = cfg or load_config()
    curves = {str(z): [] for z in zs}
    age = 0.0
    while age <= max_months + 1e-9:
        table, _ = table_for(indicator, sex, age, cfg, ref_dir)
        lms = table.at(age) if table else None
        if lms:
            for z in zs:
                curves[str(z)].append([round(age, 2), round(lms_value(*lms, z), 2)])
        age += step
    return curves


# ── Immunization status ─────────────────────────────────────────────────────────────────────────────────

UPCOMING_WINDOW_DAYS = 60
EARLY_TOLERANCE_DAYS = 4  # IAP allows a short grace before the minimum age


def resolve_vaccines(text: str, cfg=None) -> List[str]:
    """'Pentavalent-2' -> ['DTwP/DTaP', 'Hib', 'Hepatitis B']"""
    cfg = cfg or load_config()
    sched = cfg["immunization_schedule"]
    name = (text or "").lower()
    found = set()
    for combo, parts in sched.get("combination_vaccines", {}).items():
        if combo.startswith("_"):
            continue
        if re.search(rf"\b{re.escape(combo)}\b", name):
            found.update(parts)
    for vaccine, aliases in sched["vaccine_aliases"].items():
        for alias in aliases:
            if re.search(rf"(^|[^a-z]){re.escape(alias)}([^a-z]|$)", name):
                found.add(vaccine)
                break
    return sorted(found)


def immunization_status(dob: date, given: List[dict], as_of: date, cfg=None) -> dict:
    """
    given: [{"vaccine_text": "Penta 1", "given_on": date, "document_id": 12, "id": 5}, ...]
    -> {
         "rows": [{code, vaccine, dose, due_on, due_age, status, given_on, delay_days, document_id}],
         "extra_doses": [...], "unresolved": [...],
         "summary": {"given", "overdue", "due", "upcoming", "coverage_pct"}
       }
    """
    cfg = cfg or load_config()
    doses = sorted(cfg["immunization_schedule"]["doses"], key=lambda d: (d["vaccine"], d["due_days"]))

    # vaccine -> sorted unique [(date, record)]
    shots: dict = {}
    unresolved = []
    for rec in given:
        vaccines = resolve_vaccines(rec.get("vaccine_text", ""), cfg)
        if not vaccines or not rec.get("given_on"):
            unresolved.append(rec)
            continue
        for v in vaccines:
            shots.setdefault(v, {})[rec["given_on"]] = rec
    shots = {v: sorted(d.items()) for v, d in shots.items()}

    rows, extra = [], []
    by_vaccine: dict = {}
    for d in doses:
        by_vaccine.setdefault(d["vaccine"], []).append(d)

    for vaccine, sched_doses in by_vaccine.items():
        queue = list(shots.get(vaccine, []))
        for d in sched_doses:
            due_on = dob + timedelta(days=d["due_days"])
            overdue_on = due_on + timedelta(days=d["grace_days"])
            row = {
                "code": d["code"], "vaccine": vaccine, "dose": d["dose"],
                "due_on": due_on.isoformat(), "due_age": format_age(d["due_days"]),
                "status": None, "given_on": None, "delay_days": None,
                "document_id": None, "early": False, "late": False,
            }
            # skip shots clearly given before this dose's window (they belong to an earlier dose
            # that is not in the schedule, e.g. pulse-polio OPV)
            while queue and (queue[0][0] - due_on).days < -EARLY_TOLERANCE_DAYS - 28:
                extra.append({"vaccine": vaccine, "given_on": queue[0][0].isoformat()})
                queue.pop(0)
            if queue:
                g_date, rec = queue.pop(0)
                row.update(status="GIVEN", given_on=g_date.isoformat(),
                           delay_days=max(0, (g_date - due_on).days),
                           late=g_date > overdue_on,
                           document_id=rec.get("document_id"),
                           early=(g_date - due_on).days < -EARLY_TOLERANCE_DAYS)
            elif as_of > overdue_on:
                row["status"] = "OVERDUE"
                row["delay_days"] = (as_of - due_on).days
            elif as_of >= due_on:
                row["status"] = "DUE"
            elif (due_on - as_of).days <= UPCOMING_WINDOW_DAYS:
                row["status"] = "UPCOMING"
            else:
                row["status"] = "SCHEDULED"
            rows.append(row)
        for g_date, _ in queue:
            extra.append({"vaccine": vaccine, "given_on": g_date.isoformat()})

    rows.sort(key=lambda r: (r["due_on"], r["vaccine"]))
    count = lambda s: sum(1 for r in rows if r["status"] == s)  # noqa: E731
    due_so_far = sum(1 for r in rows if date.fromisoformat(r["due_on"]) <= as_of)
    given_of_due = sum(1 for r in rows if r["status"] == "GIVEN"
                       and date.fromisoformat(r["due_on"]) <= as_of)
    return {
        "source": cfg["immunization_schedule"].get("source"),
        "rows": rows,
        "extra_doses": extra,
        "unresolved": [{"vaccine_text": u.get("vaccine_text"), "id": u.get("id")} for u in unresolved],
        "summary": {
            "given": count("GIVEN"), "overdue": count("OVERDUE"), "due": count("DUE"),
            "upcoming": count("UPCOMING"),
            "coverage_pct": round(100 * given_of_due / due_so_far, 1) if due_so_far else None,
        },
    }


def next_due(status: dict) -> Optional[dict]:
    pending = [r for r in status["rows"] if r["status"] in ("OVERDUE", "DUE", "UPCOMING")]
    return pending[0] if pending else None


# ── Timeline payload ────────────────────────────────────────────────────────────────────────────────────

def _overlaps(start: date, end: Optional[date], p_from: date, p_to: date) -> bool:
    return start <= p_to and (end or p_to) >= p_from


def _age_fields(dob: date, d: date) -> dict:
    days = age_in_days(dob, d)
    return {"age_days": days, "age_label": format_age(days)}


def build_timeline(*, dob: date, sex: str, p_from: date, p_to: date,
                   episodes: List[Episode], events_by_id: dict, recurrence: List[dict],
                   growth_points: List[dict], growth_alerts: List[dict],
                   immunization: dict, admissions: List[dict], critical_labs: List[dict],
                   birth_history: Optional[dict], audience: str = "guardian",
                   cfg=None) -> dict:
    """
    events_by_id: {event_id: {"date": date, "severity": str, "document_id": int,
                              "condition_text": str, "is_verified": bool}}
    growth_points: [{"measured_on": date, "age_months", "weight_kg": {...}, "height_cm": {...},
                     "head_circ_cm": {...}, "document_id"}]
    admissions: [{"admitted_on": date, "discharged_on": date|None, "ward": str, "document_id",
                  "reason": str|None, "is_critical": bool}]
    critical_labs: [{"date": date, "analyte", "value", "direction", "severity", "document_id"}]
    """
    cfg = cfg or load_config()
    labels = cfg.get("patient_labels", {})
    lbl = (lambda code: labels.get(code, code)) if audience == "guardian" else (lambda code: code)
    recurrent_groups = {r["group"]: r for r in recurrence}
    in_period = lambda d: p_from <= d <= p_to  # noqa: E731

    lanes = []

    # 1. birth baseline (always shown, regardless of period)
    if birth_history:
        lanes.append({"id": "birth", "type": "birth", "label": "Birth",
                      "items": [{"date": dob.isoformat(), **birth_history}]})

    # 2. growth
    pts = [p for p in growth_points if in_period(p["measured_on"])]
    if pts:
        series = {"weight_kg": [], "height_cm": [], "head_circ_cm": []}
        for p in pts:
            for k in series:
                m = p.get(k)
                if m and m.get("value") is not None:
                    series[k].append({"date": p["measured_on"].isoformat(),
                                      "age_months": p["age_months"], "value": m["value"],
                                      "z": m["z"], "percentile": m["percentile"],
                                      "flag": m["flag"], "document_id": p.get("document_id")})
        lanes.append({"id": "growth", "type": "growth", "label": "Growth", "series": series,
                      "alerts": [a for a in growth_alerts
                                 if p_from.isoformat() <= a["to"] <= p_to.isoformat()]})

    # 3. immunization
    imm_items = []
    for r in immunization.get("rows", []):
        d = date.fromisoformat(r["given_on"] or r["due_on"])
        if in_period(d) or r["status"] in ("OVERDUE", "DUE"):
            imm_items.append({**r, "date": d.isoformat(), "status_label": lbl(r["status"])})
    if imm_items:
        lanes.append({"id": "immunization", "type": "immunization", "label": "Vaccines",
                      "items": imm_items, "summary": immunization.get("summary")})

    # 4. conditions - chronic first, then acute groups (recurrent ones first)
    def episode_events(ep):
        evs = []
        for eid in ep.event_ids:
            e = events_by_id.get(eid)
            if e and in_period(e["date"]):
                evs.append({"id": eid, "date": e["date"].isoformat(), "severity": e["severity"],
                            "severity_label": lbl(e["severity"]), "document_id": e.get("document_id"),
                            "text": e.get("condition_text"), "verified": e.get("is_verified", False),
                            **_age_fields(dob, e["date"])})
        return evs

    chronic_lanes, acute_by_group = [], {}
    for ep in episodes:
        if ep.is_provisional and audience == "guardian":
            continue
        if not _overlaps(ep.start, ep.end, p_from, p_to):
            continue
        item = {**ep.as_dict(), "events": episode_events(ep),
                "onset_age": format_age(age_in_days(dob, ep.start)),
                "peak_severity_label": lbl(ep.peak_severity)}
        if ep.category == "CHRONIC":
            chronic_lanes.append({"id": f"chronic:{ep.group}", "type": "chronic", "label": ep.label,
                                  "category_label": lbl("CHRONIC"), "episode": item})
        else:
            acute_by_group.setdefault(ep.group, {"label": ep.label, "episodes": []})["episodes"].append(item)

    lanes.extend(chronic_lanes)
    acute_lanes = []
    for group, data in acute_by_group.items():
        rec = recurrent_groups.get(group, {})
        acute_lanes.append({
            "id": f"acute:{group}", "type": "acute", "label": data["label"],
            "is_recurrent": rec.get("is_recurrent", False),
            "recurrence": rec or None,
            "category_label": lbl("RECURRENT") if rec.get("is_recurrent") else lbl("ACUTE"),
            "episodes": data["episodes"],
        })
    acute_lanes.sort(key=lambda l: (not l["is_recurrent"], -len(l["episodes"]), l["label"]))
    lanes.extend(acute_lanes)

    # 5. hospital stays + critical labs
    stays = [a for a in admissions
             if _overlaps(a["admitted_on"], a.get("discharged_on"), p_from, p_to)]
    crit = [c for c in critical_labs if in_period(c["date"])]
    if stays or crit:
        items = [{"kind": "ADMISSION", "start": a["admitted_on"].isoformat(),
                  "end": a["discharged_on"].isoformat() if a.get("discharged_on") else None,
                  "ward": a["ward"], "reason": a.get("reason"), "is_critical": a["is_critical"],
                  "label": lbl("CRITICAL") if a["is_critical"] else "Hospital stay",
                  "document_id": a.get("document_id"), **_age_fields(dob, a["admitted_on"])}
                 for a in stays]
        items += [{"kind": "LAB", "start": c["date"].isoformat(), "end": None,
                   "analyte": c["analyte"], "value": c["value"], "direction": c["direction"],
                   "label": lbl("CRITICAL_LAB"), "is_critical": True,
                   "document_id": c.get("document_id"), **_age_fields(dob, c["date"])}
                  for c in crit]
        lanes.append({"id": "hospital", "type": "hospital", "label": "Hospital & critical",
                      "items": sorted(items, key=lambda i: i["start"])})

    # summary for the count cards
    confirmed = [e for e in episodes if not e.is_provisional
                 and _overlaps(e.start, e.end, p_from, p_to)]
    summary = {
        "chronic_conditions": sum(1 for e in confirmed if e.category == "CHRONIC"),
        "acute_episodes": sum(1 for e in confirmed if e.category == "ACUTE"),
        "recurrent_conditions": sum(1 for r in recurrence if r["is_recurrent"]),
        "hospital_stays": len(stays),
        "critical_events": sum(1 for a in stays if a["is_critical"]) + len(crit),
        "growth_flags": sum(1 for p in pts for k in ("weight_kg", "height_cm", "head_circ_cm")
                            if p.get(k) and p[k].get("flag")),
        "vaccines_overdue": immunization.get("summary", {}).get("overdue", 0),
        "vaccine_coverage_pct": immunization.get("summary", {}).get("coverage_pct"),
    }
    # reassurance notes for parents: only worth saying when the count looks high
    typical = [r for r in recurrence
               if r.get("context") == "typical for age" and r["episodes_last_12m"] >= 3]
    notes = [f"{r['episodes_last_12m']} episodes of {r['label'].lower()} in the last year "
             f"- this is typical for the child's age" for r in typical]

    return {
        "patient": {"dob": dob.isoformat(), "sex": sex,
                    "age_label": format_age(age_in_days(dob, p_to))},
        "period": {"from": p_from.isoformat(), "to": p_to.isoformat()},
        "audience": audience,
        "summary": summary,
        "notes": notes,
        "lanes": lanes,
    }


# ── Extraction of facts from a document's text (LLM) and their clean-up ─────────────────────────────────

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
    """The same prompt to the company LLM api (settings.LLM_API_URL, token auth, {"user_prompt": ...} in, the answer text
    out) or, for local testing with LLM_API_STYLE=ollama, to a local Ollama (/api/chat, no token). The api takes one
    prompt, so the instructions go in front of the document. A 503 from the company api means its GPU is off."""
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
