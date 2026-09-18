"""
apps/registry/growth_reference.py
-----------------------------------
WHO Child Growth Standards (2006) reference tables + LMS percentile/z-score
engine, used to render percentile bands on PatientGrowthView / the parent
portal's growth chart for pediatric patients (see growth_vaccination_views.
PatientGrowthView, apps.patients.portal_views.PortalGrowthView).

IMPORTANT — same caveat as apps/registry/vaccine_schedule.py's
DEFAULT_VACCINE_SCHEDULE: the LMS (Lambda-Mu-Sigma) coefficients below are a
reasonable approximation of the published WHO Child Growth Standards tables
at a set of checkpoint ages, meant to get the percentile-band feature working
end-to-end. Before this is relied on for real clinical guidance, the exact
coefficients must be verified against WHO's own published LMS tables
(https://www.who.int/tools/child-growth-standards) — a hospital's clinical
team should review and, if needed, replace REFERENCE_TABLES with the exact
published values before this is used for real patient care decisions.

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
                (0, 0.3487, 3.3, 0.146), (1, 0.2297, 4.5, 0.161), (2, 0.1970, 5.6, 0.148),
                (3, 0.1738, 6.4, 0.140), (6, 0.1329, 7.9, 0.129), (9, 0.0888, 8.9, 0.129),
                (12, 0.0503, 9.6, 0.130), (18, -0.0017, 10.9, 0.132), (24, -0.0370, 12.2, 0.135),
                (36, -0.0918, 14.3, 0.140), (48, -0.1600, 16.3, 0.146), (60, -0.2000, 18.3, 0.152),
            ],
            "F": [
                (0, 0.3809, 3.2, 0.146), (1, 0.1714, 4.2, 0.162), (2, 0.0962, 5.1, 0.154),
                (3, 0.0402, 5.8, 0.147), (6, -0.0756, 7.3, 0.137), (9, -0.1435, 8.2, 0.134),
                (12, -0.1912, 8.9, 0.135), (18, -0.2491, 10.2, 0.137), (24, -0.2778, 11.5, 0.140),
                (36, -0.3040, 13.9, 0.146), (48, -0.3210, 16.1, 0.152), (60, -0.3350, 18.2, 0.159),
            ],
        },
        "height": {
            "M": [
                (0, 1, 49.9, 0.0379), (1, 1, 54.7, 0.0357), (2, 1, 58.4, 0.0349),
                (3, 1, 61.4, 0.0346), (6, 1, 67.6, 0.0338), (9, 1, 72.0, 0.0335),
                (12, 1, 75.7, 0.0336), (18, 1, 82.3, 0.0347), (24, 1, 87.1, 0.0357),
                (36, 1, 96.1, 0.0379), (48, 1, 103.3, 0.0394), (60, 1, 110.0, 0.0408),
            ],
            "F": [
                (0, 1, 49.1, 0.0379), (1, 1, 53.7, 0.0364), (2, 1, 57.1, 0.0358),
                (3, 1, 59.8, 0.0356), (6, 1, 65.7, 0.0350), (9, 1, 70.1, 0.0347),
                (12, 1, 74.0, 0.0349), (18, 1, 80.7, 0.0361), (24, 1, 85.7, 0.0372),
                (36, 1, 95.1, 0.0394), (48, 1, 102.7, 0.0409), (60, 1, 109.4, 0.0421),
            ],
        },
        "head_circumference": {
            "M": [
                (0, 1, 34.5, 0.0369), (1, 1, 37.3, 0.0334), (2, 1, 39.1, 0.0318),
                (3, 1, 40.5, 0.0309), (6, 1, 43.3, 0.0293), (9, 1, 45.0, 0.0286),
                (12, 1, 46.1, 0.0284), (18, 1, 47.4, 0.0284), (24, 1, 48.3, 0.0286),
                (36, 1, 49.6, 0.0290), (48, 1, 50.5, 0.0294), (60, 1, 51.2, 0.0298),
            ],
            "F": [
                (0, 1, 33.9, 0.0364), (1, 1, 36.2, 0.0332), (2, 1, 38.3, 0.0317),
                (3, 1, 39.5, 0.0308), (6, 1, 42.2, 0.0292), (9, 1, 43.8, 0.0285),
                (12, 1, 44.9, 0.0283), (18, 1, 46.2, 0.0284), (24, 1, 47.2, 0.0286),
                (36, 1, 48.5, 0.0291), (48, 1, 49.4, 0.0296), (60, 1, 50.0, 0.0300),
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
