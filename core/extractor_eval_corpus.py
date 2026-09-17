"""
core/extractor_eval_corpus.py
-------------------------------
Hand-labeled accuracy corpus for `manage.py eval_extractor`.

Same "no retroactive ground truth exists" reasoning as
core/classifier_eval_corpus.py applies here too, doubly so: there isn't even
an ExtractedLabValue table with any (guess, human-truth) history captured
anywhere in this schema — this corpus is the only ground truth extraction
accuracy can be measured against.

Each Case's `expected_values` is what a careful human reading the text would
write down. `notes` records WHY a case is here — most exist to stress one
specific extractor rule (see core/lab_value_extractor.py's system prompt):
never guess a value, copy the reference range verbatim, skip qualitative
rows rather than hallucinate a number, don't parse an ambiguous multi-clause
range into low/high.

Grow this list as real extraction misses turn up (once Phase 2's review
list exists, or from QA), same as classifier_eval_corpus.py's own note.
"""

from dataclasses import dataclass, field


@dataclass
class ExpectedValue:
    parameter: str
    value: float
    unit: str = ""
    reference_range_text: str | None = None   # None = don't check; "" = expect none printed


@dataclass
class Case:
    name: str
    text: str
    panel_slugs: list = field(default_factory=list)
    expected_values: list = field(default_factory=list)
    notes: str = ""


# ── clean, unambiguous reports — no excuse to miss or misread these ─────────

CBC_CLEAN = Case(
    name="cbc_clean",
    panel_slugs=["cbc"],
    text="""
        SRL DIAGNOSTICS PVT LTD          NABL Accredited
        Patient: Meera Nair              Age/Sex: 41 Y / F
        COMPLETE BLOOD COUNT (CBC)
        Test Name                 Result   Unit      Biological Reference Interval
        Haemoglobin               13.4     g/dL      12.0 - 15.0
        Total Leucocyte Count     7200     /cu.mm    4000 - 10000
        Platelet Count            2.55     lakh/cu.mm 1.5 - 4.1
    """,
    expected_values=[
        ExpectedValue("Haemoglobin", 13.4, "g/dL", "12.0 - 15.0"),
        ExpectedValue("Total Leucocyte Count", 7200, "/cu.mm", "4000 - 10000"),
        ExpectedValue("Platelet Count", 2.55, "lakh/cu.mm", "1.5 - 4.1"),
    ],
)

LIPID_CLEAN = Case(
    name="lipid_clean",
    panel_slugs=["lipid"],
    text="""
        Dr Lal PathLabs                  Reporting Date: 02-Sep-2026
        LIPID PROFILE, SERUM
        Investigation           Result   Units     Reference Range
        Total Cholesterol       196      mg/dL     < 200
        HDL Cholesterol         48       mg/dL     > 40
        LDL Cholesterol         118      mg/dL     < 100
        Triglycerides           150      mg/dL     < 150
    """,
    expected_values=[
        ExpectedValue("Total Cholesterol", 196, "mg/dL", "< 200"),
        ExpectedValue("HDL Cholesterol", 48, "mg/dL", "> 40"),
        ExpectedValue("LDL Cholesterol", 118, "mg/dL", "< 100"),
        ExpectedValue("Triglycerides", 150, "mg/dL", "< 150"),
    ],
)

LFT_CLEAN = Case(
    name="lft_clean",
    panel_slugs=["lft"],
    text="""
        METROPOLIS HEALTHCARE
        LIVER FUNCTION TEST (LFT)
        Bilirubin Total           0.8   mg/dL   0.3 - 1.2
        SGPT (ALT)                32    U/L     0 - 45
        SGOT (AST)                29    U/L     0 - 40
        Total Protein             7.2   g/dL    6.4 - 8.3
        Serum Albumin             4.3   g/dL    3.5 - 5.2
    """,
    expected_values=[
        ExpectedValue("Bilirubin Total", 0.8, "mg/dL", "0.3 - 1.2"),
        ExpectedValue("SGPT", 32, "U/L", "0 - 45"),
        ExpectedValue("SGOT", 29, "U/L", "0 - 40"),
        ExpectedValue("Total Protein", 7.2, "g/dL", "6.4 - 8.3"),
        ExpectedValue("Serum Albumin", 4.3, "g/dL", "3.5 - 5.2"),
    ],
)

KFT_CLEAN = Case(
    name="kft_clean",
    panel_slugs=["kft"],
    text="""
        Apollo Diagnostics
        KIDNEY FUNCTION TEST / RENAL PANEL
        Serum Creatinine        0.9   mg/dL   0.6 - 1.1
        Blood Urea              24    mg/dL   15 - 40
        Uric Acid               4.8   mg/dL   2.6 - 6.0
    """,
    expected_values=[
        ExpectedValue("Serum Creatinine", 0.9, "mg/dL", "0.6 - 1.1"),
        ExpectedValue("Blood Urea", 24, "mg/dL", "15 - 40"),
        ExpectedValue("Uric Acid", 4.8, "mg/dL", "2.6 - 6.0"),
    ],
)


# ── OCR noise — digit confusion, broken alignment ────────────────────────────

CBC_OCR_NOISY = Case(
    name="cbc_ocr_noisy",
    panel_slugs=["cbc"],
    text="""
        COMPLETE BL0OD C0UNT
        Haemog1obin        1O.2   g/dL     12.0-16.0
        Tota1 Leucocyte    75OO   /cumm    4000-11000
        Platelet Count     2.1    lakh/cumm 1.5-4.5
    """,
    expected_values=[
        ExpectedValue("Haemoglobin", 10.2, "g/dL", "12.0-16.0"),
        ExpectedValue("Total Leucocyte", 7500, "/cumm", "4000-11000"),
        ExpectedValue("Platelet Count", 2.1, "lakh/cumm", "1.5-4.5"),
    ],
    notes="Digit/letter confusion typical of a shaky OCR pass — 1O.2 for 10.2, "
          "75OO for 7500. A model that can't confidently disambiguate should "
          "score these low, not silently 'correct' them to a rounder number.",
)


# ── multi-clause reference range — must NOT be auto-parsed ──────────────────

CBC_SEX_SPECIFIC_RANGE = Case(
    name="cbc_sex_specific_range",
    panel_slugs=["cbc"],
    text="""
        COMPLETE BLOOD COUNT
        Haemoglobin    14.1   g/dL   Male: 13.0-17.0, Female: 12.0-15.0
    """,
    expected_values=[
        ExpectedValue("Haemoglobin", 14.1, "g/dL",
                       reference_range_text="Male: 13.0-17.0, Female: 12.0-15.0"),
    ],
    notes="The eval command checks this reference_range_text is captured "
          "verbatim, but that ExtractedLabValue.reference_low/high stay NULL "
          "for it — a two-clause range must never be silently resolved to "
          "one, since that requires knowing the patient's sex and this "
          "extractor has no patient context at all.",
)


# ── no printed range at all ──────────────────────────────────────────────────

HBA1C_NO_RANGE = Case(
    name="hba1c_no_range",
    panel_slugs=["diabetes"],
    text="""
        DIABETIC PROFILE
        HbA1c (Glycated Haemoglobin)     6.8    %
        Fasting Blood Sugar              118    mg/dL
    """,
    expected_values=[
        ExpectedValue("HbA1c", 6.8, "%", reference_range_text=""),
        ExpectedValue("Fasting Blood Sugar", 118, "mg/dL", reference_range_text=""),
    ],
    notes="No reference interval column at all — reference_range_text must "
          "come back empty, never invented from general medical knowledge.",
)


# ── numeric + qualitative mixed — qualitative rows must be skipped ──────────

URINE_MIXED = Case(
    name="urine_mixed",
    panel_slugs=["urine"],
    text="""
        URINE ROUTINE & MICROSCOPY
        Colour              Pale Yellow
        Appearance          Clear
        pH                  6.0
        Specific Gravity    1.020
        Protein             Nil
        Glucose             Nil
        Pus Cells           2-4       /hpf     0-5
        Epithelial Cells    Occasional
    """,
    expected_values=[
        ExpectedValue("pH", 6.0, unit=""),
        ExpectedValue("Specific Gravity", 1.020, unit=""),
        ExpectedValue("Pus Cells", 4, "/hpf", "0-5"),  # "2-4" is itself a range, not a point value — see notes
    ],
    notes="Colour/Appearance/Protein/Glucose/Epithelial Cells are qualitative "
          "and must be OMITTED, not hallucinated into a fake number. Pus "
          "Cells prints as a range ('2-4') rather than a point value — "
          "accepting either bound (this corpus expects the upper, 4) is "
          "reasonable; inventing an average (3) is not, since nothing "
          "printed says 'average of the range'.",
)

COVID_QUALITATIVE_ONLY = Case(
    name="covid_qualitative_only",
    panel_slugs=["infection"],
    text="""
        COVID-19 RT-PCR REPORT
        SARS-CoV-2 RNA          NOT DETECTED
        Result                  NEGATIVE
    """,
    expected_values=[],
    notes="Entirely qualitative — the correct extraction is ZERO values, not "
          "a hallucinated Ct number the report never printed. Mirrors the "
          "real seed-data COVID RT-PCR document that correctly extracted "
          "nothing during this session's manual verification pass.",
)


# ── multi-panel health package ───────────────────────────────────────────────

HEALTH_PACKAGE = Case(
    name="health_package_multi_panel",
    panel_slugs=["cbc", "lipid", "diabetes"],
    text="""
        FULL BODY HEALTH CHECKUP PACKAGE
        -- COMPLETE BLOOD COUNT --
        Haemoglobin            12.8   g/dL    12.0-15.0
        -- LIPID PROFILE --
        Total Cholesterol      210    mg/dL   <200
        -- DIABETIC PROFILE --
        Fasting Blood Sugar    102    mg/dL   70-100
    """,
    expected_values=[
        ExpectedValue("Haemoglobin", 12.8, "g/dL", "12.0-15.0"),
        ExpectedValue("Total Cholesterol", 210, "mg/dL", "<200"),
        ExpectedValue("Fasting Blood Sugar", 102, "mg/dL", "70-100"),
    ],
    notes="One document, three panels — all three result rows must be found, "
          "not just the first section.",
)


# ── unusual layout ────────────────────────────────────────────────────────────

KFT_COLON_LAYOUT = Case(
    name="kft_colon_layout",
    panel_slugs=["kft"],
    text="""
        RENAL FUNCTION PANEL
        Creatinine: 1.4 mg/dL (Normal 0.7-1.3)
        Urea: 45 mg/dL (Normal 15-45)
        Sodium: 138 mEq/L (Normal 135-145)
        Potassium: 4.2 mEq/L (Normal 3.5-5.1)
    """,
    expected_values=[
        ExpectedValue("Creatinine", 1.4, "mg/dL", "0.7-1.3"),
        ExpectedValue("Urea", 45, "mg/dL", "15-45"),
        ExpectedValue("Sodium", 138, "mEq/L", "135-145"),
        ExpectedValue("Potassium", 4.2, "mEq/L", "3.5-5.1"),
    ],
    notes="Colon-separated inline layout with the range in parentheses "
          "rather than a table column — tests the extractor isn't only "
          "tuned to the tabular CBC/lipid style.",
)


# ── adversarial ───────────────────────────────────────────────────────────────

WRAPPED_ROWS = Case(
    name="wrapped_rows",
    panel_slugs=["thyroid"],
    text="""
        THYROID PROFILE
        Test Name              Result
        Unit                   Reference Range
        TSH (Thyroid Stimulating
        Hormone)                3.2
        uIU/mL                 0.4 - 4.0
        Free T4                 1.1
        ng/dL                   0.8 - 1.8
    """,
    expected_values=[
        ExpectedValue("TSH", 3.2, "uIU/mL", "0.4 - 4.0"),
        ExpectedValue("Free T4", 1.1, "ng/dL", "0.8 - 1.8"),
    ],
    notes="A row's parameter name, value, unit and range each landed on "
          "their own OCR line (word-wrap from a narrow PDF column) — tests "
          "the extractor reassembles a row across line breaks rather than "
          "only reading single-line 'name value unit range' patterns.",
)

AMBIGUOUS_UNITS = Case(
    name="ambiguous_units",
    panel_slugs=["cbc"],
    text="""
        CBC
        Total WBC Count      9.8    10^3/uL   4.0-11.0
        Platelet Count       310    10^3/uL   150-450
    """,
    expected_values=[
        ExpectedValue("Total WBC Count", 9.8, "10^3/uL", "4.0-11.0"),
        ExpectedValue("Platelet Count", 310, "10^3/uL", "150-450"),
    ],
    notes="Scientific-notation unit (10^3/uL) rather than the more common "
          "/cu.mm or /uL spelled out — the unit must be copied as printed, "
          "not silently converted to a different (even if equivalent) form.",
)

NEAR_MISS_NON_LAB = Case(
    name="near_miss_prescription_with_numbers",
    panel_slugs=[],
    text="""
        Dr. R. Kapoor, MD
        Rx
        Tab. Metformin 500mg  -- 1-0-1 after food, 30 days
        Tab. Atorvastatin 10mg -- 0-0-1 at night, 30 days
        Follow up after 30 days
    """,
    expected_values=[],
    notes="A prescription, not a lab report — dosage numbers (500, 10, 30) "
          "must never be extracted as if they were test results. This "
          "shouldn't reach the extractor at all in production (doc_type != "
          "lab_report gates it), but the extractor itself should still not "
          "hallucinate values if it's ever pointed at the wrong document type.",
)


CASES = [
    CBC_CLEAN, LIPID_CLEAN, LFT_CLEAN, KFT_CLEAN,
    CBC_OCR_NOISY, CBC_SEX_SPECIFIC_RANGE, HBA1C_NO_RANGE,
    URINE_MIXED, COVID_QUALITATIVE_ONLY, HEALTH_PACKAGE,
    KFT_COLON_LAYOUT, WRAPPED_ROWS, AMBIGUOUS_UNITS, NEAR_MISS_NON_LAB,
]
