"""
apps/patients/pediatrics/growth_reference.py
--------------------------------------------
WHO Child Growth Standards (2006), birth to 5 years, and the maths that turns a measurement into a percentile.

DATA: the LMS (Lambda-Mu-Sigma) coefficients are copied as published from WHO's "Birth to 5 years (z-scores)" tables
(https://www.who.int/tools/child-growth-standards), one row per checkpoint age: weight-for-age, length/height-for-age
and head-circumference-for-age, for boys (M) and girls (F). Height uses one continuous curve across 24 months, where WHO
switches from lying length to standing height, because Vitals.height_cm doesn't record the posture. To update the
figures, re-extract the L/M/S columns from the same WHO files rather than editing by hand.

METHOD: z = ((X / M) ** L - 1) / (L * S), or ln(X / M) / S when L is 0, where X is the measurement and L, M, S are the
coefficients for the child's sex and age. The percentile is the normal curve's value at z. Ages between two checkpoints
are linearly interpolated.
"""
import math
from datetime import date

# measurement -> sex -> [(age_months, L, M, S), ...] sorted by age
REFERENCE_TABLES = {
    "weight": {
        "M": [
            (0, 0.3487, 3.3464, 0.1460), (1, 0.2297, 4.4709, 0.1340), (2, 0.1970, 5.5675, 0.1239),
            (3, 0.1738, 6.3762, 0.1173), (6, 0.1257, 7.9340, 0.1096), (9, 0.0917, 8.9014, 0.1088),
            (12, 0.0644, 9.6479, 0.1092), (18, 0.0211, 10.9385, 0.1112), (24, -0.0137, 12.1515, 0.1143),
            (36, -0.0689, 14.3429, 0.1212), (48, -0.1131, 16.3489, 0.1276), (60, -0.1506, 18.3366, 0.1352),
        ],
        "F": [
            (0, 0.3809, 3.2322, 0.1417), (1, 0.1714, 4.1873, 0.1372), (2, 0.0962, 5.1282, 0.1300),
            (3, 0.0402, 5.8458, 0.1262), (6, -0.0756, 7.2970, 0.1220), (9, -0.1507, 8.2254, 0.1220),
            (12, -0.2024, 8.9481, 0.1227), (18, -0.2637, 10.2315, 0.1231), (24, -0.2941, 11.4775, 0.1239),
            (36, -0.3201, 13.8503, 0.1292), (48, -0.3361, 16.0697, 0.1388), (60, -0.3518, 18.2193, 0.1482),
        ],
    },
    # 0-24mo from the length-for-age (recumbent) table, 24-60mo from the
    # height-for-age (standing) table — see module docstring for why.
    "height": {
        "M": [
            (0, 1, 49.8842, 0.0379), (1, 1, 54.7244, 0.0356), (2, 1, 58.4249, 0.0342),
            (3, 1, 61.4292, 0.0333), (6, 1, 67.6236, 0.0316), (9, 1, 71.9687, 0.0312),
            (12, 1, 75.7488, 0.0314), (18, 1, 82.2587, 0.0328), (24, 1, 87.8161, 0.0348),
            (36, 1, 96.0835, 0.0386), (48, 1, 103.3273, 0.0406), (60, 1, 109.9638, 0.0421),
        ],
        "F": [
            (0, 1, 49.1477, 0.0379), (1, 1, 53.6872, 0.0364), (2, 1, 57.0673, 0.0357),
            (3, 1, 59.8029, 0.0352), (6, 1, 65.7311, 0.0345), (9, 1, 70.1435, 0.0344),
            (12, 1, 74.0150, 0.0348), (18, 1, 80.7079, 0.0360), (24, 1, 86.4153, 0.0373),
            (36, 1, 95.0515, 0.0401), (48, 1, 102.7312, 0.0419), (60, 1, 109.4233, 0.0435),
        ],
    },
    "head_circumference": {
        "M": [
            (0, 1, 34.4618, 0.0369), (1, 1, 37.2759, 0.0313), (2, 1, 39.1285, 0.0300),
            (3, 1, 40.5135, 0.0292), (6, 1, 43.3306, 0.0282), (9, 1, 44.9998, 0.0279),
            (12, 1, 46.0661, 0.0279), (18, 1, 47.3711, 0.0280), (24, 1, 48.2515, 0.0282),
            (36, 1, 49.4612, 0.0287), (48, 1, 50.2115, 0.0291), (60, 1, 50.7375, 0.0295),
        ],
        "F": [
            (0, 1, 33.8787, 0.0350), (1, 1, 36.5463, 0.0321), (2, 1, 38.2521, 0.0317),
            (3, 1, 39.5328, 0.0314), (6, 1, 42.1995, 0.0309), (9, 1, 43.8300, 0.0305),
            (12, 1, 44.8965, 0.0303), (18, 1, 46.2424, 0.0299), (24, 1, 47.1822, 0.0296),
            (36, 1, 48.5099, 0.0291), (48, 1, 49.3321, 0.0288), (60, 1, 49.9229, 0.0285),
        ],
    },
}

MEASUREMENTS = ("weight", "height", "head_circumference")


def _lms(measurement, sex, age_months):
    """The (L, M, S) coefficients for this child, or None when the table doesn't cover them (WHO covers 0-60 months, M or F)."""
    table = REFERENCE_TABLES.get(measurement, {}).get(sex)
    if not table or age_months is None or not 0 <= age_months <= 60:
        return None
    for (a0, *c0), (a1, *c1) in zip(table, table[1:]):
        if a0 <= age_months <= a1:
            frac = (age_months - a0) / (a1 - a0)
            return tuple(x0 + frac * (x1 - x0) for x0, x1 in zip(c0, c1))
    return tuple(table[-1][1:])


def get_percentile(measurement, sex, age_months, value):
    """
    {"z_score", "percentile" (0-100)} for one measurement, or None when it can't be scored (no value, age outside
    0-60 months, sex not M or F). measurement: "weight" (kg), "height" or "head_circumference" (cm).
    """
    lms = _lms(measurement, sex, age_months)
    if value is None or lms is None:
        return None
    L, M, S = lms
    value = float(value)
    z = (((value / M) ** L) - 1) / (L * S) if L != 0 else math.log(value / M) / S
    z = max(-5, min(5, z))                         # a wildly out-of-range reading shouldn't blow up the percentile
    return {"z_score": round(z, 2), "percentile": round(0.5 * (1 + math.erf(z / math.sqrt(2))) * 100, 1)}


_MEASURED = {"weight": "weight_kg", "height": "height_cm", "head_circumference": "head_circumference_cm"}


def add_percentiles(series, gender, date_of_birth, *, only_source=None):
    """
    Add a "percentiles" dict to each reading in `series` (dicts with "date" as YYYY-MM-DD, weight_kg, height_cm,
    head_circumference_cm, "source") taken before the child turned 5. `only_source` limits it to readings from that
    source. Returns whether any reading got a percentile.
    """
    if gender not in ("M", "F") or not date_of_birth:
        return False
    found = False
    for point in series:
        if only_source and point["source"] != only_source:
            continue
        taken = date.fromisoformat(point["date"])
        months = (taken.year - date_of_birth.year) * 12 + (taken.month - date_of_birth.month)
        if not 0 <= months <= 60:
            continue
        point["percentiles"] = {}
        for name in MEASUREMENTS:
            result = get_percentile(name, gender, months, point[_MEASURED[name]])
            if result:
                point["percentiles"][name] = result
                found = True
    return found
