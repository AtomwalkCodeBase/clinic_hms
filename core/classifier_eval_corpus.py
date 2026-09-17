"""
core/classifier_eval_corpus.py
-------------------------------
Hand-labeled accuracy corpus for `manage.py eval_classifier`.

This is NOT ground truth pulled from real patient uploads — no retroactive
ground truth exists in the SharedDocument table (corrections overwrite
doc_type in place with no history kept; see the eval command's docstring).
It's a synthetic, hand-labeled corpus in the same spirit as the fixtures in
core/tests_doc_classifier.py, but scored for precision/recall instead of
pass/fail, and deliberately weighted toward the cases that actually stress
the confidence gates: OCR noise, stray keywords from the wrong category,
weak/ambiguous signal, and near-miss non-medical documents.

Each Case carries the answer key a human reviewer would give:
  * doc_type          expected kind
  * categories        expected panel slug(s), primary first (lab_report only)
  * should_autofile   would a careful human say "yes, file this without
                       asking"? False means the case is *supposed* to be
                       ambiguous/unclear and land in the review tray.
  * non_medical       expected res.non_medical

Grow this list as real misclassifications turn up (in QA, in the review
tray, in support tickets) — every case here should trace to something that
either already went wrong or plausibly could.
"""

from dataclasses import dataclass, field


@dataclass
class Case:
    name: str
    text: str
    doc_type: str
    categories: list = field(default_factory=list)
    should_autofile: bool = True
    non_medical: bool = False
    notes: str = ""


# ── clean, unambiguous documents — the pipeline has no excuse to miss these ──
CBC_CLEAN = """
    SRL DIAGNOSTICS PVT LTD          NABL Accredited
    Patient: Meera Nair              Age/Sex: 41 Y / F
    Sample Collected On : 11/09/2026 08:40 AM
    Reported On         : 12/09/2026 06:30 PM
    COMPLETE BLOOD COUNT (CBC)
    Test Name                 Result   Unit      Biological Reference Interval
    Haemoglobin               13.4     g/dL      12.0 - 15.0
    Total Leucocyte Count     7200     /cu.mm    4000 - 10000
    Platelet Count            2.55     lakh/cu.mm 1.5 - 4.1
    Differential Count : Neutrophils 58%  Lymphocytes 34%
    Verified by Dr. S. Menon, MD Pathology
"""

LIPID_CLEAN = """
    Dr Lal PathLabs                  Reporting Date: 02-Sep-2026
    LIPID PROFILE, SERUM
    Investigation           Result   Units     Reference Range
    Total Cholesterol       196      mg/dL     < 200
    HDL Cholesterol         48       mg/dL     > 40
    LDL Cholesterol         118      mg/dL     < 100
    Triglycerides           150      mg/dL     < 150
"""

LFT_CLEAN = """
    METROPOLIS HEALTHCARE
    Sample Collected On: 21/08/2026     Reported On: 22/08/2026
    LIVER FUNCTION TEST (LFT)
    Bilirubin Total           0.8   mg/dL   0.3 - 1.2
    SGPT (ALT)                32    U/L     0 - 45
    SGOT (AST)                29    U/L     0 - 40
    Total Protein             7.2   g/dL    6.4 - 8.3
    Serum Albumin             4.3   g/dL    3.5 - 5.2
"""

KFT_CLEAN = """
    Apollo Diagnostics       Collected On : 17-07-2026     Reported : 18-07-2026
    KIDNEY FUNCTION TEST / RENAL PANEL
    Serum Creatinine        0.9   mg/dL   0.6 - 1.1
    Blood Urea              24    mg/dL   15 - 40
    Uric Acid               4.8   mg/dL   2.6 - 6.0
    eGFR                    92    mL/min/1.73m2
"""

THYROID_CLEAN = """
    Thyrocare Technologies
    THYROID PROFILE - TOTAL
    Sample Drawn: 03/09/2026
    Total T3 (Triiodothyronine)  1.1       ng/mL      0.6 - 1.9
    Total T4 (Thyroxine)         8.4       ug/dL      4.5 - 12.6
    TSH (Thyroid Stimulating Hormone) 2.30 uIU/mL     0.3 - 5.5
"""

HBA1C_CLEAN = """
    Metropolis      Collected On: 31/08/2026    Reported On: 01/09/2026
    HbA1c (Glycated Haemoglobin)
    HbA1c                        6.4    %      Non-diabetic < 5.7
    Estimated Average Glucose    137    mg/dL
    Fasting Blood Sugar          104    mg/dL
"""

URINE_CLEAN = """
    City Lab       URINE ROUTINE AND MICROSCOPY
    Collected On: 05/09/2026
    Colour           Pale Yellow      Appearance       Clear
    Albumin          Nil       Glucose   Nil     Ketone Bodies  Nil
    Pus Cells        2-3 /hpf  Epithelial Cells 1-2 /hpf
"""

HEALTH_PACKAGE = """
    FULL BODY HEALTH CHECKUP - COMPREHENSIVE
    Sample Collected On: 08/09/2026    Reported On: 09/09/2026
    COMPLETE BLOOD COUNT
    Haemoglobin 13.1 g/dL   Total Leucocyte Count 6800 /cu.mm  Platelet Count 2.4 lakh
    Differential Count: Neutrophils 60%
    LIPID PROFILE
    Total Cholesterol 205 mg/dL   HDL Cholesterol 44   LDL Cholesterol 130   Triglycerides 160
    LIVER FUNCTION TEST
    SGPT (ALT) 30 U/L   SGOT (AST) 27 U/L   Bilirubin Total 0.7   Serum Albumin 4.2 g/dL
    KIDNEY FUNCTION TEST
    Serum Creatinine 0.8 mg/dL   Blood Urea 22   Uric Acid 4.5   eGFR 95
"""

PRESCRIPTION_CLEAN = """
    Dr. Arjun Mehta, M.B.B.S., M.D. (General Medicine)
    Lakeview Clinic     Reg. No. KMC-33219      Date: 03/09/2026
    Chief Complaint: fever, body ache x 3 days
    Diagnosis: Viral fever
    Rx
    1. Tab. Paracetamol 650 mg   1-1-1  x 3 days  after food
    2. Cap. Amoxicillin 500 mg   1-0-1  x 5 days
    3. Syp. Cough Linctus        2 tsp at bedtime  sos
    Advice: plenty of oral fluids, rest
    Review after 3 days
"""

IMAGING_CLEAN = """
    NOVACARE HOSPITAL - DEPARTMENT OF RADIOLOGY
    Date of Study: 15/06/2026
    CHEST X-RAY PA VIEW
    Findings: Both lung fields are clear. No focal consolidation or mass lesion.
    IMPRESSION: No significant abnormality detected.
    Dr. R. Iyer, Consultant Radiologist
"""

DISCHARGE_CLEAN = """
    NOVACARE HOSPITAL          DISCHARGE SUMMARY
    IP No: 2026/44821          Ward: 3B   Bed No: 12
    Date of Admission: 10/05/2026     Date of Discharge: 14/05/2026
    Final Diagnosis: Acute gastroenteritis with mild dehydration
    Hospital Course: The patient was admitted with vomiting and loose stools,
    managed conservatively with IV fluids.
    Condition at Discharge: Stable, afebrile.
    Discharge Medications: Tab. ORS sachets, Tab. Pantoprazole 40 mg OD
    Advice on Discharge: follow up in OPD after 1 week
"""

# ── OCR-noisy variants of the same documents — robustness under real photos ──
CBC_OCR_NOISE = """
    SRL DlAGN0STlCS PVT LTD  NABL Accredited
    Samp|e C0||ected 0n : 11/O9/2O26
    C0MPL3TE BL00D C0UNT (CBC)
    Test Name          Resu|t  Unit    Bi0|0gica| Reference |nterva|
    Haem0g|obin        13.4    g/dL    12.0 - 15.0
    T0ta| Leuc0cyte C0unt 72OO /cu.mm  4OOO - 1OOOO
    P|ate|et C0unt     2.55    |akh/cu.mm 1.5 - 4.1
"""

PRESCRIPTION_OCR_NOISE = """
    Dr. Arjun Mehta MBBS  Lakeview C|inic  Date: O3/O9/2O26
    Chief C0mp|aint: fever x 3 days
    Rx
    1. Tab. Paracetam0| 65O mg  1-1-1  x 3 days  after f00d
    2. Cap. Am0xici||in 5OO mg  1-O-1  x 5 days
    Advice: p|enty of ora| f|uids, rest
"""

LIPID_LOWERCASE_NOSPACE = (
    "dr lal pathlabs reporting date 02-sep-2026 lipid profile serum "
    "investigation result units reference range total cholesterol 196 mg/dl "
    "hdl cholesterol 48 mg/dl ldl cholesterol 118 mg/dl triglycerides 150 mg/dl"
)

# ── non-medical documents — must be skipped, not filed as "other" clutter ──
SHOP_INVOICE = (
    "RELIANCE DIGITAL TAX INVOICE  Invoice No RD/88213  GSTIN 27AAACR "
    "HSN Code 8517  Sub Total 24999  CGST 2249  Grand Total 29498  "
    "Mode of Payment UPI  Transaction ID 4429  Amount Paid 29498"
)

AADHAAR = (
    "GOVERNMENT OF INDIA  Aadhaar  UIDAI  Unique Identification Authority "
    "Permanent Account Number ABCDE1234F  Income Tax Department"
)

BOARDING_PASS = "INDIGO BOARDING PASS  PNR X8K2QP  Seat No 14C  DEL BLR  e-ticket"

SALARY_SLIP = (
    "ACME PVT LTD SALARY SLIP  Employee Meera Nair  Net Amount 78500  "
    "Mode of Payment Bank Transfer  Pay Slip August 2026"
)

ELECTRICITY_BILL = (
    "STATE ELECTRICITY BOARD  Electricity Bill  Consumer No 44821  "
    "Billing Address 12 MG Road  Units Consumed 210  Amount Payable 1840  "
    "Due Date 20/09/2026"
)

BANK_STATEMENT = (
    "HDFC BANK  Statement of Account  Account No XXXX4821  "
    "Opening Balance 45200.00  Closing Balance 51840.00  "
    "Transaction ID UPI/2609/4821"
)

# The trap: a pharmacy bill lists drug names + dosage-shaped lines (the exact
# _RX_HINTS vocabulary), which is exactly the kind of thing that could
# false-positive into "prescription" if the non-medical check isn't strict.
PHARMACY_PURCHASE_INVOICE = """
    APOLLO PHARMACY          TAX INVOICE   Bill No: PH/9931
    GSTIN: 07AABCS1234M1Z5   Date: 12/09/2026
    Tab. Paracetamol 650mg  x 10  ................ 45.00
    Cap. Amoxicillin 500mg  x 15  ................ 120.00
    Syp. Cough Linctus 100ml x 1  ................ 85.00
    Sub Total .................................... 250.00
    CGST 6.25  SGST 6.25  Grand Total ............ 262.50
    Amount Paid: 262.50   Mode of Payment: UPI
"""

# A real medical record that happens to mention one billing word — must NOT
# be skipped as non-medical (this is the false-reject risk in the other
# direction: dropping a genuine record because of one stray word).
CBC_WITH_STRAY_BILLING_WORD = CBC_CLEAN + "\n    Amount Paid: 350.00"

# ── ambiguous / should-ask cases — the pipeline should NOT be confident here ──
AMBIGUOUS_SHORT_NOTE = "Dr. Arjun Mehta MBBS. Patient advised the following. Signature."

WEAK_LAB_SIGNAL = "Report. Result: Normal. Sample received. Method : standard."

LAB_REPORT_AMBIGUOUS_PANEL = """
    Metropolis Health   Sample Collected On: 04/09/2026
    Test Name          Result   Unit    Reference Range
    Glucose (Random)   104      mg/dL   70 - 140
    Creatinine         0.9      mg/dL   0.6 - 1.1
"""

TOO_SHORT = "Meera Nair"

# Discharge summary that quotes a couple of lab values in passing — must stay
# discharge_summary, not flip to lab_report on the reference-range hint.
DISCHARGE_WITH_LABS_MENTIONED = """
    NOVACARE HOSPITAL          DISCHARGE SUMMARY
    IP No: 2026/44821          Ward: 3B   Bed No: 12
    Date of Admission: 10/05/2026     Date of Discharge: 14/05/2026
    Final Diagnosis: Acute gastroenteritis with mild dehydration
    Hospital Course: Admitted with vomiting and loose stools. Haemoglobin was
    12.8 g/dL (reference range 12.0-15.0) on admission, within normal limits.
    Condition at Discharge: Stable, afebrile.
    Discharge Medications: Tab. ORS sachets, Tab. Pantoprazole 40 mg OD
"""

# Prescription that orders labs — "Investigations advised: CBC, LFT" must not
# flip it to lab_report.
PRESCRIPTION_ADVISING_LABS = PRESCRIPTION_CLEAN + \
    "\n    Investigations advised: CBC, LFT, Thyroid Profile\n    Follow up with reports"


CASES = [
    # clean, unambiguous
    Case("cbc_clean", CBC_CLEAN, "lab_report", ["cbc"], True),
    Case("lipid_clean", LIPID_CLEAN, "lab_report", ["lipid"], True),
    Case("lft_clean", LFT_CLEAN, "lab_report", ["lft"], True),
    Case("kft_clean", KFT_CLEAN, "lab_report", ["kft"], True),
    Case("thyroid_clean", THYROID_CLEAN, "lab_report", ["thyroid"], True),
    Case("hba1c_clean", HBA1C_CLEAN, "lab_report", ["diabetes"], True),
    Case("urine_clean", URINE_CLEAN, "lab_report", ["urine"], True),
    Case("health_package", HEALTH_PACKAGE, "lab_report", ["cbc", "lipid", "lft", "kft"], True,
         notes="multi-panel; only the primary slug order is checked strictly"),
    Case("prescription_clean", PRESCRIPTION_CLEAN, "prescription", [], True),
    Case("imaging_clean", IMAGING_CLEAN, "scan", [], True),
    Case("discharge_clean", DISCHARGE_CLEAN, "discharge_summary", [], True),

    # OCR noise — same ground truth, garbled input
    Case("cbc_ocr_noise", CBC_OCR_NOISE, "lab_report", ["cbc"], True,
         notes="digit-for-letter OCR substitutions (0/O, l/I)"),
    Case("prescription_ocr_noise", PRESCRIPTION_OCR_NOISE, "prescription", [], True),
    Case("lipid_lowercase_nospace", LIPID_LOWERCASE_NOSPACE, "lab_report", ["lipid"], True),

    # non-medical — must be skipped
    Case("shop_invoice", SHOP_INVOICE, "other", [], False, non_medical=True),
    Case("aadhaar", AADHAAR, "other", [], False, non_medical=True),
    Case("boarding_pass", BOARDING_PASS, "other", [], False, non_medical=True),
    Case("salary_slip", SALARY_SLIP, "other", [], False, non_medical=True),
    Case("electricity_bill", ELECTRICITY_BILL, "other", [], False, non_medical=True),
    Case("bank_statement", BANK_STATEMENT, "other", [], False, non_medical=True),
    Case("pharmacy_purchase_invoice", PHARMACY_PURCHASE_INVOICE, "other", [], False, non_medical=True,
         notes="drug names + dosage lines inside a bill - the real false-positive risk"),
    Case("cbc_with_stray_billing_word", CBC_WITH_STRAY_BILLING_WORD, "lab_report", ["cbc"], True,
         non_medical=False, notes="one billing word must not drop a real record"),

    # ambiguous — pipeline should ask, not guess
    Case("ambiguous_short_note", AMBIGUOUS_SHORT_NOTE, "other", [], False,
         notes="no real doc-type signal; must not be auto-filed as anything"),
    Case("weak_lab_signal", WEAK_LAB_SIGNAL, "other", [], False,
         notes="too few markers to safely commit to lab_report"),
    Case("lab_report_ambiguous_panel", LAB_REPORT_AMBIGUOUS_PANEL, "lab_report", [], False,
         notes="kind is clear-ish but panel markers are too thin to name a panel confidently"),
    Case("too_short", TOO_SHORT, "other", [], False),

    # near-miss traps — signal that could plausibly flip the verdict
    Case("discharge_with_labs_mentioned", DISCHARGE_WITH_LABS_MENTIONED, "discharge_summary", [], True,
         notes="quotes one lab value; must not flip to lab_report"),
    Case("prescription_advising_labs", PRESCRIPTION_ADVISING_LABS, "prescription", [], True,
         notes="orders CBC/LFT by name; must not flip to lab_report"),
]
