"""
apps/registry/growth_reference.py
-----------------------------------
WHO Child Growth Standards (2006) reference tables + LMS percentile/z-score
engine, used to render percentile bands on PatientGrowthView / the parent
portal's growth chart for pediatric patients (see growth_vaccination_views.
PatientGrowthView, apps.patients.portal_views.PortalGrowthView).

DATA SOURCE — the LMS (Lambda-Mu-Sigma) coefficients below are transcribed
directly from WHO's own published "Birth to 5 years (z-scores)" Excel tables
(https://www.who.int/tools/child-growth-standards), one checkpoint age per
row, exactly as WHO publishes them — not approximated or interpolated by
this codebase. Source files, fetched from cdn.who.int:
  weight-for-age:            wfa_{boys,girls}_0-to-5-years_zscores.xlsx
  length-for-age (0-24mo):   lhfa_{boys,girls}_0-to-2-years_zscores.xlsx
  height-for-age (24-60mo):  lhfa_{boys,girls}_2-to-5-years_zscores.xlsx
  head-circumference-for-age: hcfa_{boys,girls}_0-5-zscores.xlsx
height-for-age switches source table at 24 months, matching WHO's own
convention (recumbent length vs standing height are measured differently
and have slightly different reference curves — e.g. boys at 24mo: 87.82cm
lying down vs 87.12cm standing — this is a real, documented WHO artifact of
measurement technique, not a data error). Vitals.height_cm in this system
doesn't record which technique was used, so — same tradeoff WHO's own
combined growth charts make — one continuous curve is used across the
switch rather than asking staff to record measurement posture.
If a hospital's clinical team prefers to re-verify or replace these figures
in the future, the safest path is re-fetching the same WHO Excel files above
and re-extracting the L/M/S columns at these ages, rather than transcribing
by hand.

Standard scope (per product decision — see the "Both, WHO first" build
decision): only the WHO standard ships in this iteration. Every table below
is keyed by a `standard` field ("who") specifically so a second standard
(e.g. IAP — the Indian Academy of Pediatrics growth charts many Indian
pediatricians prefer) can be added later as REFERENCE_TABLES["iap"][...]
without any schema or call-site change — see get_percentile()'s `standard`
kwarg, already threaded through end-to-end.

LMS METHOD — the standard way population growth references convert a raw
measurement into a percentile:
    Z = ((X / M) ** L - 1) / (L * S)   when L != 0
    Z = ln(X / M) / S                   when L == 0
  X = the child's measured value, M/L/S = the age-and-sex-matched reference
  coefficients (M = median, S = coefficient of variation, L = Box-Cox power
  to correct skew). Z is then converted to a percentile via the standard
  normal CDF. This is the exact method WHO's own growth chart software uses.

Ages are stored in whole months, 0-60 (WHO's 0-5-years standard). Values
between two known ages are linearly interpolated per-coefficient — a minor
approximation, and correct behavior at the checkpoint ages themselves, which
is where WHO publishes its own values anyway.
"""

import math

# measurement -> sex -> [(age_months, L, M, S), ...] sorted by age_months.
# "weight" = weight-for-age, "height" = length/height-for-age (recumbent
# length to 24mo, standing height after, per WHO convention — this table
# does not distinguish the two measurement techniques, matching how Vitals.
# height_cm is recorded regardless of the child's age), "head_circumference"
# = head-circumference-for-age (WHO publishes this to 5 years; clinically
# most useful in the first 2 years, when the fontanelles are still open).
REFERENCE_TABLES = {
    "who": {
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
    },
}

MEASUREMENTS = ("weight", "height", "head_circumference")


def _interp_lms(points, age_months):
    """points: [(age, L, M, S), ...] sorted by age. Linear-interpolates
    each coefficient independently; clamps to the nearest endpoint outside
    the table's own range (0-60mo) rather than extrapolating."""
    if age_months <= points[0][0]:
        return points[0][1:]
    if age_months >= points[-1][0]:
        return points[-1][1:]
    for (a0, l0, m0, s0), (a1, l1, m1, s1) in zip(points, points[1:]):
        if a0 <= age_months <= a1:
            if a1 == a0:
                return (l0, m0, s0)
            frac = (age_months - a0) / (a1 - a0)
            return (
                l0 + frac * (l1 - l0),
                m0 + frac * (m1 - m0),
                s0 + frac * (s1 - s0),
            )
    return points[-1][1:]  # unreachable given the clamps above


def _normal_cdf(z):
    """Standard normal CDF via math.erf — no scipy dependency needed."""
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def get_percentile(measurement, sex, age_months, value, *, standard="who"):
    """
    Returns {"z_score": float, "percentile": float (0-100)} for a single
    measurement, or None if out of scope (measurement/sex/standard not
    covered, age outside 0-60 months, or no value to score).

    measurement — "weight" | "height" | "head_circumference"
    sex         — "M" | "F" (Patient.GENDER_CHOICES; "O"/blank -> None, no
                  WHO reference table is sex-neutral)
    age_months  — child's age in whole months at the time of the reading
    value       — the raw measured value (kg for weight, cm for height/HC)
    """
    if value is None or age_months is None or age_months < 0 or age_months > 60:
        return None
    if sex not in ("M", "F"):
        return None
    table = REFERENCE_TABLES.get(standard, {}).get(measurement, {}).get(sex)
    if not table:
        return None

    L, M, S = _interp_lms(table, age_months)
    value = float(value)
    if L != 0:
        z = (((value / M) ** L) - 1) / (L * S)
    else:
        z = math.log(value / M) / S
    z = max(-5, min(5, z))  # clamp — a wildly out-of-range reading shouldn't blow up the percentile
    percentile = round(_normal_cdf(z) * 100, 1)
    return {"z_score": round(z, 2), "percentile": percentile}


def percentile_band(measurement, sex, age_months, *, standard="who"):
    """
    Returns the reference median (M) plus the values at a fixed set of
    percentile bands (3rd/15th/50th/85th/97th — the same bands WHO's own
    printed growth charts plot) for one age point, for drawing a percentile
    curve/band on a chart. None under the same conditions as get_percentile.
    """
    if age_months is None or age_months < 0 or age_months > 60 or sex not in ("M", "F"):
        return None
    table = REFERENCE_TABLES.get(standard, {}).get(measurement, {}).get(sex)
    if not table:
        return None
    L, M, S = _interp_lms(table, age_months)
    # z-scores for the standard WHO chart bands (3rd/15th/50th/85th/97th pctl)
    z_for_band = {"p3": -1.881, "p15": -1.036, "p50": 0.0, "p85": 1.036, "p97": 1.881}
    band = {}
    for label, z in z_for_band.items():
        if L != 0:
            band[label] = round(M * ((z * L * S) + 1) ** (1 / L), 2)
        else:
            band[label] = round(M * math.exp(z * S), 2)
    return band
