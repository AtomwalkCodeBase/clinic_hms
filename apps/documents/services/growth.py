"""
Growth z-scores, percentiles, flags and faltering detection (LMS method).

Reference data
--------------
LMS tables live in config/growth_reference/ as CSV: age_months,L,M,S
File naming:  {indicator}_{sex}_{source}.csv
  indicator : wfa (weight-for-age), lhfa (length/height-for-age),
              hcfa (head-circumference-for-age), bfa (BMI-for-age)
  sex       : male | female
  source    : who (0-60 months)  |  iap (60-216 months)

Get them from:
  * WHO Child Growth Standards 2006 "expanded tables" (who.int/tools/child-growth-standards)
  * IAP 2015 growth charts for 5-18 year Indian children (LMS values published by IAP)
Convert with:  python manage.py load_growth_reference <file> --indicator wfa --sex male --source who

Note: IAP 5-18 charts have no head-circumference reference; HC is plotted to 5 y only.
"""

import csv
import math
from bisect import bisect_left
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from .clinical_rules import age_in_months
from .config import GROWTH_REFERENCE_DIR, load_config


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
