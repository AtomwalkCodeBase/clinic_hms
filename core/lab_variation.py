"""
core/lab_variation.py
-----------------------
Pure logic, no I/O beyond one ORM query — turns a patient's stored
ExtractedLabValue history (core.lab_value_extractor's output, via
`manage.py extract_lab_values`) into a list of "this changed a lot since
last time" flags for the Health Insights tab.

Deliberately separate from lab_value_extractor: that module is a labeller
(reads a document, never compares or computes); this module is a comparator
(reads what's already stored, never talks to an LLM). Keeping "what did the
report say" and "does that matter" as two different files means a mistake in
one can't corrupt what the other already safely stored.

Design, per what the user asked for + what was agreed while scoping this
(see the "Round 2" section of the health-insights-feature project memory):
  - Both directions matter — a value can flag for going up OR down.
  - A confidence gate applies BEFORE any comparison: only values with
    confidence >= CONFIDENCE_GATE are ever compared, and a flag's baseline
    is the most recent EARLIER value that itself cleared the gate too (a
    shaky extraction never becomes the thing a real reading is compared
    against).
  - When the report itself printed an unambiguous reference range,
    flagging is based on "did the new value fall outside it" — more
    clinically honest than a flat percentage, and needs no separately
    maintained reference-range database, just what the report already
    printed (see ExtractedLabValue.reference_low/high — only populated for
    a single unambiguous clause, never a multi-clause sex/age-specific one).
    Otherwise, falls back to a flat 20% delta (the simpler option the user
    picked over building a clinical reference-range database).
  - Units are never silently reconciled beyond a short, explicit,
    deterministic table (glucose, the cholesterol family) — anything else
    with mismatched units is skipped rather than risking a wrong comparison.
  - Message wording is direction-aware for a modest list of common analytes
    (PARAMETER_DIRECTION) and falls back to neutral "changed by X%" wording
    for anything not in that list — never guesses whether a rise or fall in
    an unfamiliar analyte is the concerning direction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

CONFIDENCE_GATE = 0.7
PERCENT_THRESHOLD = 20.0  # flat delta fallback, in percent


# ── canonicalization ─────────────────────────────────────────────────────
# Maps a printed/extracted parameter label to a stable slug so "Hb" on one
# report and "Haemoglobin" on another are recognised as the same test. This
# is genuinely new work, not something core.report_types already gives for
# free — that module's marker lists are a substring vocabulary for scoring
# *which panel* a document belongs to, not a canonical analyte-name map.
#
# Keys are checked as normalized substrings (see _normalize) against the
# extracted label, longest-alias-first so e.g. "total cholesterol" doesn't
# get shadowed by a bare "cholesterol" entry. Grow this table as real
# extracted labels turn up that don't already map cleanly.
_ALIASES: dict[str, tuple[str, ...]] = {
    "hemoglobin":        ("hemoglobin", "haemoglobin", "hb", "hgb"),
    "wbc_count":         ("wbc count", "total leucocyte count", "total leukocyte count",
                           "tlc", "wbc", "total wbc count", "leucocyte count"),
    "rbc_count":         ("rbc count", "red blood cell count", "rbc"),
    "platelet_count":    ("platelet count", "platelets"),
    "hematocrit":        ("hematocrit", "haematocrit", "pcv", "packed cell volume"),
    "neutrophils":       ("neutrophils",),
    "lymphocytes":       ("lymphocytes",),
    "eosinophils":       ("eosinophils",),
    "monocytes":         ("monocytes",),
    "basophils":         ("basophils",),
    "esr":               ("esr", "erythrocyte sedimentation rate"),

    "total_cholesterol": ("total cholesterol",),
    "hdl_cholesterol":   ("hdl cholesterol", "hdl"),
    "ldl_cholesterol":   ("ldl cholesterol", "ldl"),
    "triglycerides":     ("triglycerides",),
    "vldl":              ("vldl",),
    # A derived RATIO, not the same measurement as HDL itself — must be
    # checked before the bare "hdl"/"ldl" aliases above (longest-alias-first
    # sorting handles that), or "Chol / HDL Ratio" silently collapses onto
    # the same slug as a raw HDL Cholesterol reading. Caught during the
    # Phase 1->2 backfill: it did exactly that on real extracted data.
    "cholesterol_hdl_ratio": ("chol hdl ratio", "cholesterol hdl ratio",
                              "total cholesterol hdl ratio"),

    "sgpt_alt":          ("sgpt", "alt", "alanine aminotransferase"),
    "sgot_ast":          ("sgot", "ast", "aspartate aminotransferase"),
    "bilirubin_total":   ("bilirubin total", "total bilirubin"),
    "total_protein":     ("total protein",),
    "serum_albumin":     ("serum albumin", "albumin"),
    "alkaline_phosphatase": ("alkaline phosphatase", "alp"),

    "creatinine":        ("creatinine", "serum creatinine"),
    "urea":              ("urea", "blood urea"),
    "uric_acid":         ("uric acid",),
    "egfr":              ("egfr",),

    "sodium":            ("sodium",),
    "potassium":         ("potassium",),
    "chloride":          ("chloride",),
    "bicarbonate":       ("bicarbonate",),
    "calcium":           ("calcium",),

    "tsh":               ("tsh", "thyroid stimulating hormone"),
    "free_t4":           ("free t4", "ft4"),
    "free_t3":           ("free t3", "ft3"),
    "lh":                ("lh", "luteinizing hormone"),

    "troponin_i":        ("troponin i", "troponin-i", "troponinl", "cardiac troponin i"),
    # "troponinl" is a real, repeated OCR misread — the Roman numeral "I"
    # merges with no space into a trailing lowercase "l" ("Troponin I" ->
    # "Troponinl"). Mapping it here rather than "fixing" the OCR: this
    # module only canonicalizes what core.lab_value_extractor already
    # extracted, it never re-reads the document.
    "ck_mb":             ("ck-mb", "ck mb", "creatine kinase mb", "creatine kinase-mb"),

    "hba1c":             ("hba1c", "glycated haemoglobin", "glycated hemoglobin",
                           "glycosylated haemoglobin"),
    "fasting_glucose":   ("fasting blood sugar", "fasting glucose", "fbs"),
    "pp_glucose":        ("postprandial blood sugar", "post prandial blood sugar", "ppbs"),
    "random_glucose":    ("random blood sugar", "rbs"),

    "vitamin_d":         ("vitamin d", "25-oh vitamin d", "25-hydroxy vitamin d"),
    "vitamin_b12":       ("vitamin b12", "vitamin b-12", "cobalamin"),
    "ferritin":          ("ferritin", "serum ferritin"),

    "crp":               ("crp", "c-reactive protein"),
    "ph":                ("ph",),
    "specific_gravity":  ("specific gravity",),
}
_ALIAS_LOOKUP: list[tuple[str, str]] = sorted(
    ((alias, slug) for slug, aliases in _ALIASES.items() for alias in aliases),
    key=lambda pair: -len(pair[0]),   # longest alias first so specific beats generic
)


def _normalize(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()


def parameter_slug(parameter_label: str) -> str:
    """Canonical key for a printed/extracted analyte name. Falls back to a
    deterministic slug of the label itself (same shape as
    extract_lab_values.py's old placeholder) when nothing in _ALIASES
    matches — an unmapped analyte still gets a STABLE key across documents
    that print it identically, it just won't match a differently-worded
    version of the same test until it's added to _ALIASES."""
    norm = _normalize(parameter_label)
    for alias, slug in _ALIAS_LOOKUP:
        if alias in norm:
            return slug
    fallback = re.sub(r"[^a-z0-9]+", "_", norm).strip("_")
    return fallback[:60] or "unknown"


# ── direction (message wording only — never gates anything) ─────────────
# "higher_is_concern" / "lower_is_concern" / "neutral". Deliberately a short
# list of well-established analytes; everything else (including plenty of
# real tests) stays "neutral" rather than guessing a polarity.
PARAMETER_DIRECTION: dict[str, str] = {
    "hemoglobin":        "lower_is_concern",
    "hematocrit":        "lower_is_concern",
    "ldl_cholesterol":   "higher_is_concern",
    "total_cholesterol": "higher_is_concern",
    "triglycerides":     "higher_is_concern",
    "hdl_cholesterol":   "lower_is_concern",   # inverted vs. the rest of the cholesterol family — HIGH HDL is good
    "creatinine":        "higher_is_concern",
    "urea":              "higher_is_concern",
    "uric_acid":         "higher_is_concern",
    "hba1c":             "higher_is_concern",
    "fasting_glucose":   "higher_is_concern",
    "pp_glucose":        "higher_is_concern",
    "random_glucose":    "higher_is_concern",
    "sgpt_alt":          "higher_is_concern",
    "sgot_ast":          "higher_is_concern",
    "bilirubin_total":   "higher_is_concern",
    "vitamin_d":         "lower_is_concern",
    "vitamin_b12":       "lower_is_concern",
    "crp":               "higher_is_concern",
    # Deliberately NEUTRAL — both directions are clinically meaningful, a
    # forced polarity would misinform as often as it'd help:
    "platelet_count":    "neutral",
    "wbc_count":         "neutral",
    "tsh":               "neutral",
    "sodium":            "neutral",
    "potassium":         "neutral",
    "ferritin":          "neutral",
}


# ── unit conversion — narrow and explicit, never inferred by the LLM ─────
# (value_in_unit_a, unit_a, unit_b) -> value_in_unit_b. Only the handful of
# pairs a real Indian lab report is likely to mix; anything else with
# mismatched units is skipped rather than guessed.
def _mgdl_to_mmoll_glucose(v: float) -> float: return v / 18.0182
def _mmoll_to_mgdl_glucose(v: float) -> float: return v * 18.0182
def _mgdl_to_mmoll_cholesterol(v: float) -> float: return v / 38.67
def _mmoll_to_mgdl_cholesterol(v: float) -> float: return v * 38.67

_GLUCOSE_SLUGS = {"fasting_glucose", "pp_glucose", "random_glucose"}
_CHOLESTEROL_SLUGS = {"total_cholesterol", "hdl_cholesterol", "ldl_cholesterol", "triglycerides"}


def _to_common_unit(slug: str, value: float, unit: str) -> tuple[float, str] | None:
    """Best-effort normalize to a common unit for THIS slug so two readings
    in different (but known-convertible) units can still be compared.
    Returns None if the unit is unrecognized for this slug — the caller
    must then skip the comparison rather than assume equality."""
    u = (unit or "").strip().lower().replace(" ", "")
    if slug in _GLUCOSE_SLUGS:
        if u in ("mg/dl", "mgdl"):
            return value, "mg/dl"
        if u in ("mmol/l", "mmoll"):
            return _mmoll_to_mgdl_glucose(value), "mg/dl"
        return None
    if slug in _CHOLESTEROL_SLUGS:
        if u in ("mg/dl", "mgdl"):
            return value, "mg/dl"
        if u in ("mmol/l", "mmoll"):
            return _mmoll_to_mgdl_cholesterol(value), "mg/dl"
        return None
    # Everything else: only comparable when the printed units already match
    # exactly (case/space-insensitive) — no conversion table for it.
    return value, u


def to_common_unit(slug: str, value: float, unit: str) -> tuple[float, str] | None:
    """Public wrapper around _to_common_unit — for callers outside this
    module (the trends/report-detail endpoints) that need the same
    unit-normalization table without duplicating it or reaching into a
    "private" name."""
    return _to_common_unit(slug, value, unit)


def status_for(value: float, reference_low: float | None, reference_high: float | None) -> str | None:
    """"high" / "low" / "normal" against a report's own printed reference
    range, or None when no range was available to judge against (an
    unparsed multi-clause range, or an analyte with none printed at all —
    see ExtractedLabValue's docstring for why reference_low/high are often
    unpopulated even when reference_range_text is not)."""
    if reference_low is not None and value < reference_low:
        return "low"
    if reference_high is not None and value > reference_high:
        return "high"
    if reference_low is not None or reference_high is not None:
        return "normal"
    return None


@dataclass
class Flag:
    parameter_slug: str
    parameter_label: str
    document_id: int
    previous_document_id: int
    document_date: object          # date | None — the printed/extracted date of the current reading
    previous_document_date: object # date | None — same, for the baseline reading
    current_value: float
    previous_value: float
    unit: str
    pct_delta: float
    direction: str          # "up" | "down"
    concern: str            # "higher_is_concern" | "lower_is_concern" | "neutral"
    basis: str              # "reference_range" | "percent_delta"
    message: str


def _message(label: str, current: float, previous: float, unit: str,
             pct_delta: float, direction: str, concern: str, basis: str) -> str:
    verb = "rose" if direction == "up" else "dropped"
    pct_txt = f"{abs(pct_delta):.0f}%"
    base = f"Your {label} {verb} {pct_txt} since your last reading ({previous:g}{unit} → {current:g}{unit})."
    if basis == "reference_range":
        base = f"Your {label} is now outside its usual range ({previous:g}{unit} → {current:g}{unit})."
    if concern == "neutral" or (concern == "higher_is_concern" and direction == "down") \
            or (concern == "lower_is_concern" and direction == "up"):
        return base + " Worth mentioning at your next visit."
    return base + " This may be worth discussing with your doctor."


def build_trend_parameters(awpid: str, cutoff, min_points: int = 2) -> list[dict]:
    """Per-analyte time series over `awpid`'s ExtractedLabValue history —
    shared by PortalLabTrendsView (GET, every parameter) and
    PortalHealthInsightNarrativeView (POST, one parameter's narrative) so
    the confidence gate / unit-normalization / status logic lives in
    exactly one place rather than being copied into each view.

    cutoff: a date, or None for "all time" — points older than this are
    dropped before the "does this parameter even have >=min_points points"
    check, same as compute_flags' range handling.

    min_points: the default (2) is "a single reading has nothing to trend
    against" — the right threshold for anything that's about to draw a
    chart. Callers building a browsable catalogue of every analyte the
    patient has ANY confident reading for (e.g. the mobile app's parameter
    picker, so a test with only one reading so far still shows up as
    selectable with a "needs one more reading" state) pass min_points=1
    instead — same gate/normalization logic either way, just a different
    "is this worth listing" bar.

    Returns a list of {"slug", "label", "unit", "latest_value",
    "latest_status", "concern", "points": [...]} dicts, sorted by most
    points first (the one with the longest history is the most useful
    default to show). Each parameter also carries "panels" — the report
    panel(s) (slug + label) of its most recent contributing document, e.g.
    [{"slug": "cbc", "label": "Complete Blood Count"}] — for a mobile/web
    picker that wants to filter "everything I'm tracking" by category
    instead of only searching by name. Sourced straight from
    SharedDocument.report_categories (already set by classification), never
    guessed from the parameter name itself.
    """
    from apps.registry.models import ExtractedLabValue
    from core.report_types import label_for

    rows = list(
        ExtractedLabValue.objects.using("default")
        .filter(awpid=awpid, confidence__gte=CONFIDENCE_GATE)
        .order_by("parameter_slug", "document_date")
        .values("document_id", "parameter_slug", "parameter_label", "value_numeric",
                 "unit", "reference_low", "reference_high", "document_date",
                 "document__report_categories")
    )

    by_param: dict[str, list[dict]] = {}
    for r in rows:
        by_param.setdefault(r["parameter_slug"], []).append(r)

    parameters = []
    for slug, series in by_param.items():
        series.sort(key=lambda r: r["document_date"] or date.min)
        if cutoff is not None:
            series = [r for r in series if r["document_date"] and r["document_date"] >= cutoff]
        if len(series) < min_points:
            continue

        points = []
        common_unit = None
        for r in series:
            conv = to_common_unit(slug, r["value_numeric"], r["unit"])
            if conv is None:
                continue
            value, unit = conv
            if common_unit is None:
                common_unit = unit
            elif unit != common_unit:
                continue  # a differently-unitted reading we can't reconcile — skip, never guess
            points.append({
                "document_id": r["document_id"],
                "date": r["document_date"],
                "value": value,
                "reference_low": r["reference_low"],
                "reference_high": r["reference_high"],
                "status": status_for(value, r["reference_low"], r["reference_high"]),
            })
        if len(points) < min_points:
            continue

        latest_panel_slugs = series[-1]["document__report_categories"] or []
        parameters.append({
            "slug": slug,
            "label": series[-1]["parameter_label"],
            "unit": common_unit or "",
            "latest_value": points[-1]["value"],
            "latest_status": points[-1]["status"],
            "concern": PARAMETER_DIRECTION.get(slug, "neutral"),
            "panels": [{"slug": s, "label": label_for(s)} for s in latest_panel_slugs],
            "points": points,
        })

    parameters.sort(key=lambda p: (-len(p["points"]), p["label"]))
    return parameters


def compute_flags(awpid: str, range_cutoff) -> list[dict]:
    """range_cutoff: a date, or None for "all time" — only the NEWEST value
    in a flagged pair needs to fall on/after this cutoff; its baseline's
    date is context and isn't itself range-gated (comparing "since your
    last CBC" shouldn't disappear just because that last CBC happened to
    sit outside the currently-selected range).

    Never touches the network — pure query + comparison over already-stored
    ExtractedLabValue rows. Returns plain dicts (not core.lab_variation.Flag
    instances) so the caller (PortalHealthInsightsView) can hand them
    straight to core.response.success() without a second serialization step.
    """
    from apps.registry.models import ExtractedLabValue

    rows = list(
        ExtractedLabValue.objects.using("default")
        .filter(awpid=awpid, confidence__gte=CONFIDENCE_GATE)
        .order_by("parameter_slug", "document_date")
        .values("document_id", "parameter_slug", "parameter_label", "value_numeric",
                 "unit", "reference_low", "reference_high", "document_date")
    )

    by_param: dict[str, list[dict]] = {}
    for r in rows:
        by_param.setdefault(r["parameter_slug"], []).append(r)

    flags: list[Flag] = []
    for slug, series in by_param.items():
        if len(series) < 2:
            continue
        series.sort(key=lambda r: r["document_date"] or r["document_date"])
        current, previous = series[-1], series[-2]

        if range_cutoff is not None:
            cd = current["document_date"]
            if cd is None or cd < range_cutoff:
                continue

        conv_cur = _to_common_unit(slug, current["value_numeric"], current["unit"])
        conv_prev = _to_common_unit(slug, previous["value_numeric"], previous["unit"])
        if conv_cur is None or conv_prev is None or conv_cur[1] != conv_prev[1]:
            continue  # mismatched/unrecognized units — never guess, just skip
        cur_val, unit = conv_cur
        prev_val, _ = conv_prev
        if prev_val == 0:
            continue

        basis = None
        if current["reference_low"] is not None and current["reference_high"] is not None:
            if cur_val < current["reference_low"] or cur_val > current["reference_high"]:
                basis = "reference_range"
        pct_delta = (cur_val - prev_val) / abs(prev_val) * 100.0
        if basis is None and abs(pct_delta) >= PERCENT_THRESHOLD:
            basis = "percent_delta"
        if basis is None:
            continue

        direction = "up" if cur_val > prev_val else "down"
        concern = PARAMETER_DIRECTION.get(slug, "neutral")
        label = current["parameter_label"]
        flags.append(Flag(
            parameter_slug=slug, parameter_label=label,
            document_id=current["document_id"], previous_document_id=previous["document_id"],
            document_date=current["document_date"], previous_document_date=previous["document_date"],
            current_value=cur_val, previous_value=prev_val, unit=unit,
            pct_delta=round(pct_delta, 1), direction=direction, concern=concern, basis=basis,
            message=_message(label, cur_val, prev_val, unit, pct_delta, direction, concern, basis),
        ))

    flags.sort(key=lambda f: abs(f.pct_delta), reverse=True)
    return [f.__dict__ for f in flags]
