"""
core/tests_doc_classifier.py
----------------------------
DB-independent tests for the outside-document classifier:
  * kind         (prescription / lab report / imaging / discharge / other)
  * panel        (CBC / Lipid / LFT / KFT / Thyroid / diabetes / urine ...)
  * date         (labelled-priority extraction, day-first parsing)
  * multi-panel  (a health-package PDF -> categories[])
  * image gate   (blur / dark / tiny -> unreadable)

The sample text mimics what pypdf / Tesseract would hand back for a real
Indian lab report or prescription — headers, analyte names, "Sample
Collected On" lines. No real patient data.

    python manage.py test core.tests_doc_classifier
"""

import io
from datetime import date

from django.test import SimpleTestCase, override_settings


# The keyword/date/panel layers are deterministic - pin the AI fallbacks OFF
# so these tests never make a network call. The LLM/vision merge is covered
# separately in LayerMergeTests with a stubbed labeller.
from core import doc_classifier, doc_dates, image_quality, ocr, report_types


@override_settings(DOC_CLASSIFIER_LLM="", DOC_CLASSIFIER_VISION_MODEL="")
class _Det(SimpleTestCase):
    pass


# ── sample documents ────────────────────────────────────────────────────
CBC = """
    SRL DIAGNOSTICS PVT LTD          NABL Accredited
    Patient: Meera Nair              Age/Sex: 41 Y / F
    Ref. By: Dr. Anil Kumar          Lab No: 25091234
    Sample Collected On : 11/09/2026 08:40 AM
    Sample Received On  : 11/09/2026 10:15 AM
    Reported On         : 12/09/2026 06:30 PM

    COMPLETE BLOOD COUNT (CBC)
    Test Name                 Result   Unit      Biological Reference Interval
    Haemoglobin               13.4     g/dL      12.0 - 15.0
    Total Leucocyte Count     7200     /cu.mm    4000 - 10000
    RBC Count                 4.6      mill/cu.mm 3.8 - 4.8
    Platelet Count            2.55     lakh/cu.mm 1.5 - 4.1
    Packed Cell Volume (PCV)  40.2     %         36 - 46
    MCV                       84.1     fL        83 - 101
    MCH                       28.0     pg        27 - 32
    Differential Count : Neutrophils 58%  Lymphocytes 34%  Monocytes 6%  Eosinophils 2%
    Verified by Dr. S. Menon, MD Pathology
"""

LIPID = """
    Dr Lal PathLabs                  Reporting Date: 02-Sep-2026
    LIPID PROFILE, SERUM
    Investigation           Result   Units     Reference Range
    Total Cholesterol       196      mg/dL     < 200
    HDL Cholesterol         48       mg/dL     > 40
    LDL Cholesterol         118      mg/dL     < 100
    Triglycerides           150      mg/dL     < 150
    VLDL Cholesterol        30       mg/dL     < 30
    Non-HDL Cholesterol     148      mg/dL     < 130
    CHOL/HDL Ratio          4.1
"""

LFT = """
    METROPOLIS HEALTHCARE
    Sample Collected On: 21/08/2026     Reported On: 22/08/2026
    LIVER FUNCTION TEST (LFT)
    Bilirubin Total           0.8   mg/dL   0.3 - 1.2
    Bilirubin Direct          0.2   mg/dL   0.0 - 0.3
    SGPT (ALT)                32    U/L     0 - 45
    SGOT (AST)                29    U/L     0 - 40
    Alkaline Phosphatase      88    U/L     40 - 129
    Total Protein             7.2   g/dL    6.4 - 8.3
    Serum Albumin             4.3   g/dL    3.5 - 5.2
    A/G Ratio                 1.4
    GGT                       24    U/L
"""

KFT = """
    Apollo Diagnostics       Collected On : 17-07-2026     Reported : 18-07-2026
    KIDNEY FUNCTION TEST / RENAL PANEL
    Serum Creatinine        0.9   mg/dL   0.6 - 1.1
    Blood Urea              24    mg/dL   15 - 40
    Blood Urea Nitrogen     11.2  mg/dL
    Uric Acid               4.8   mg/dL   2.6 - 6.0
    eGFR                    92    mL/min/1.73m2
    Serum Sodium            139   mmol/L
    Serum Potassium         4.2   mmol/L
"""

THYROID = """
    Thyrocare Technologies
    THYROID PROFILE - TOTAL
    Sample Drawn: 03/09/2026
    Test                         Result    Unit       Reference
    Total T3 (Triiodothyronine)  1.1       ng/mL      0.6 - 1.9
    Total T4 (Thyroxine)         8.4       ug/dL      4.5 - 12.6
    TSH (Thyroid Stimulating Hormone) 2.30 uIU/mL     0.3 - 5.5
"""

HBA1C = """
    Metropolis      Collected On: 31/08/2026    Reported On: 01/09/2026
    HbA1c (Glycated Haemoglobin)
    HbA1c                        6.4    %      Non-diabetic < 5.7
    Estimated Average Glucose    137    mg/dL
    Fasting Blood Sugar          104    mg/dL
"""

URINE = """
    City Lab       URINE ROUTINE AND MICROSCOPY
    Collected On: 05/09/2026
    PHYSICAL EXAMINATION
    Colour           Pale Yellow
    Appearance       Clear
    Specific Gravity 1.015
    CHEMICAL EXAMINATION
    Albumin          Nil       Glucose   Nil     Ketone Bodies  Nil
    MICROSCOPIC EXAMINATION
    Pus Cells        2-3 /hpf
    Epithelial Cells 1-2 /hpf
    RBCs             Nil
    Casts            Absent    Crystals  Absent
"""

HEALTH_PACKAGE = """
    FULL BODY HEALTH CHECKUP - COMPREHENSIVE
    Sample Collected On: 08/09/2026    Reported On: 09/09/2026

    COMPLETE BLOOD COUNT
    Haemoglobin 13.1 g/dL   Total Leucocyte Count 6800 /cu.mm  Platelet Count 2.4 lakh
    MCV 85 fL   MCH 29 pg   Differential Count: Neutrophils 60%

    LIPID PROFILE
    Total Cholesterol 205 mg/dL   HDL Cholesterol 44   LDL Cholesterol 130   Triglycerides 160  VLDL 26

    LIVER FUNCTION TEST
    SGPT (ALT) 30 U/L   SGOT (AST) 27 U/L   Bilirubin Total 0.7   Serum Albumin 4.2 g/dL  Alkaline Phosphatase 80

    KIDNEY FUNCTION TEST
    Serum Creatinine 0.8 mg/dL   Blood Urea 22   Uric Acid 4.5   eGFR 95
"""

PRESCRIPTION = """
    Dr. Arjun Mehta, M.B.B.S., M.D. (General Medicine)
    Lakeview Clinic     Reg. No. KMC-33219
    Date: 03/09/2026

    Chief Complaint: fever, body ache x 3 days
    Diagnosis: Viral fever

    Rx
    1. Tab. Paracetamol 650 mg   1-1-1  x 3 days  after food
    2. Cap. Amoxicillin 500 mg   1-0-1  x 5 days
    3. Syp. Cough Linctus        2 tsp at bedtime  sos

    Advice: plenty of oral fluids, rest
    Investigations advised: CBC, CRP
    Review after 3 days
"""

IMAGING = """
    NOVACARE HOSPITAL - DEPARTMENT OF RADIOLOGY
    Date of Study: 15/06/2026
    CHEST X-RAY PA VIEW
    Findings:
    Both lung fields are clear. No focal consolidation or mass lesion.
    Cardiac silhouette is normal in size. Costophrenic angles are clear.
    IMPRESSION: No significant abnormality detected.
    Dr. R. Iyer, Consultant Radiologist
"""

DISCHARGE = """
    NOVACARE HOSPITAL          DISCHARGE SUMMARY
    IP No: 2026/44821          Ward: 3B   Bed No: 12
    Date of Admission: 10/05/2026     Date of Discharge: 14/05/2026
    Final Diagnosis: Acute gastroenteritis with mild dehydration
    Hospital Course: The patient was admitted with... managed conservatively...
    Condition at Discharge: Stable, afebrile.
    Discharge Medications: Tab. ORS sachets, Tab. Pantoprazole 40 mg OD
    Advice on Discharge: follow up in OPD after 1 week
"""

INVOICE = """
    SRL DIAGNOSTICS         TAX INVOICE
    Invoice No: INV/2026/9931       GSTIN: 07AABCS1234M1Z5
    Bill No: 5541      Date: 12/09/2026
    Complete Blood Count ................ 350.00
    Lipid Profile ...................... 600.00
    Grand Total .................. 950.00
    Amount Paid: 950.00      Balance Due: 0.00
    Payment Received - Thank You
"""

DATE_PRIORITY = """
    Sample Collected On : 04/09/2026
    Sample Received On  : 05/09/2026
    Reported On         : 06/09/2026
    Printed On          : 07/09/2026
"""


class KindTests(_Det):
    def _kind(self, text):
        return doc_classifier.classify_text(text)

    def test_cbc_is_lab_report(self):
        r = self._kind(CBC)
        self.assertEqual(r.doc_type, "lab_report")
        self.assertTrue(r.confident, r)

    def test_prescription(self):
        r = self._kind(PRESCRIPTION)
        self.assertEqual(r.doc_type, "prescription")
        self.assertTrue(r.confident, r)

    def test_imaging_is_scan(self):
        r = self._kind(IMAGING)
        self.assertEqual(r.doc_type, "scan")

    def test_discharge_summary(self):
        r = self._kind(DISCHARGE)
        self.assertEqual(r.doc_type, "discharge_summary")

    def test_invoice_is_other_not_lab(self):
        r = self._kind(INVOICE)
        self.assertEqual(r.doc_type, "other")

    def test_non_medical_docs_are_flagged_for_skipping(self):
        for label, text in (
            ("shop invoice",
             "RELIANCE DIGITAL TAX INVOICE  Invoice No RD/88213  GSTIN 27AAACR "
             "HSN Code 8517  Sub Total 24999  CGST 2249  Grand Total 29498  "
             "Mode of Payment UPI  Transaction ID 4429  Amount Paid 29498"),
            ("aadhaar / PAN",
             "GOVERNMENT OF INDIA  Aadhaar  UIDAI  Unique Identification Authority "
             "Permanent Account Number ABCDE1234F  Income Tax Department"),
            ("boarding pass",
             "INDIGO BOARDING PASS  PNR X8K2QP  Seat No 14C  DEL BLR  e-ticket"),
            ("salary slip",
             "ACME PVT LTD SALARY SLIP  Employee Meera Nair  Net Amount 78500  "
             "Mode of Payment Bank Transfer  Pay Slip August 2026"),
        ):
            r = self._kind(text)
            self.assertTrue(r.non_medical, f"{label}: {r}")
            self.assertEqual(r.doc_type, "other")

    def test_medical_doc_with_one_stray_billing_word_is_kept(self):
        # a real report that happens to mention "amount paid" once must NOT be skipped
        r = self._kind(CBC + "\n    Amount Paid: 350.00")
        self.assertFalse(r.non_medical, r)
        self.assertEqual(r.doc_type, "lab_report")

    def test_prescription_ordering_labs_is_not_a_lab_report(self):
        # "Investigations advised: CBC, CRP" must not flip it to lab_report
        r = self._kind(PRESCRIPTION)
        self.assertEqual(r.doc_type, "prescription")

    def test_too_short_text_is_other(self):
        r = self._kind("Meera Nair")
        self.assertEqual(r.doc_type, "other")
        self.assertFalse(r.confident)


class PanelTests(_Det):
    def _cats(self, text):
        return doc_classifier.classify_text(text).categories

    def test_cbc(self):
        self.assertEqual(self._cats(CBC)[:1], ["cbc"])

    def test_lipid(self):
        self.assertEqual(self._cats(LIPID)[:1], ["lipid"])

    def test_lft(self):
        self.assertEqual(self._cats(LFT)[:1], ["lft"])

    def test_kft(self):
        self.assertEqual(self._cats(KFT)[:1], ["kft"])

    def test_thyroid(self):
        self.assertEqual(self._cats(THYROID)[:1], ["thyroid"])

    def test_hba1c(self):
        self.assertEqual(self._cats(HBA1C)[:1], ["diabetes"])

    def test_urine(self):
        self.assertEqual(self._cats(URINE)[:1], ["urine"])

    def test_panels_confident_enough_to_autofile(self):
        for name, text in (("cbc", CBC), ("lipid", LIPID), ("lft", LFT),
                           ("kft", KFT), ("thyroid", THYROID), ("hba1c", HBA1C), ("urine", URINE)):
            r = doc_classifier.classify_text(text)
            self.assertGreaterEqual(r.category_confidence, report_types.CONFIDENT,
                                    f"{name}: {r.category_confidence} {r.categories}")

    def test_health_package_is_multi(self):
        r = doc_classifier.classify_text(HEALTH_PACKAGE)
        self.assertTrue(r.multi, r.categories)
        for slug in ("cbc", "lipid", "lft", "kft"):
            self.assertIn(slug, r.categories, r.categories)

    def test_prescription_has_no_category(self):
        r = doc_classifier.classify_text(PRESCRIPTION)
        self.assertEqual(r.categories, [])


class DateTests(_Det):
    def test_prefers_collection_over_report_over_print(self):
        d = doc_dates.extract(DATE_PRIORITY)
        self.assertEqual(d.report_date, date(2026, 9, 4))
        self.assertEqual(d.source, "collection")
        self.assertGreaterEqual(d.confidence, 0.9)

    def test_keeps_collection_separately_when_report_is_primary(self):
        text = "Reported On: 22/08/2026\nSample Collected On: 21/08/2026"
        d = doc_dates.extract(text)
        # collection wins as primary; nothing left to store separately
        self.assertEqual(d.report_date, date(2026, 8, 21))

    def test_report_only(self):
        d = doc_dates.extract("Reporting Date: 02-Sep-2026")
        self.assertEqual(d.report_date, date(2026, 9, 2))
        self.assertEqual(d.source, "report")

    def test_day_first_parsing(self):
        d = doc_dates.extract("Collected On: 04/09/2026")
        self.assertEqual(d.report_date, date(2026, 9, 4))  # 4 Sep, not 9 Apr

    def test_iso_date(self):
        d = doc_dates.extract("Reported On 2026-08-04")
        self.assertEqual(d.report_date, date(2026, 8, 4))

    def test_month_name_forms(self):
        self.assertEqual(doc_dates.extract("Date: 12 Aug 2026").report_date, date(2026, 8, 12))
        self.assertEqual(doc_dates.extract("Date: Aug 12, 2026").report_date, date(2026, 8, 12))
        self.assertEqual(doc_dates.extract("Date: 12-Aug-2026").report_date, date(2026, 8, 12))

    def test_future_date_rejected(self):
        d = doc_dates.extract("Reported On: 04/09/2099")
        self.assertIsNone(d.report_date)

    def test_no_date(self):
        d = doc_dates.extract("Complete Blood Count\nHaemoglobin 13.4")
        self.assertIsNone(d.report_date)
        self.assertEqual(d.confidence, 0.0)

    def test_cbc_sample_date_is_collection(self):
        r = doc_classifier.classify_text(CBC)
        self.assertEqual(r.doc_date, date(2026, 9, 11))
        self.assertEqual(r.date_source, "collection")


class NeedsGateTests(_Det):
    def test_clean_lab_report_needs_nothing(self):
        r = doc_classifier.classify_text(CBC)
        self.assertEqual(r.needs, [])
        self.assertTrue(r.fully_confident)

    def test_clean_prescription_needs_nothing(self):
        r = doc_classifier.classify_text(PRESCRIPTION)
        self.assertEqual(r.needs, [])

    def test_lab_report_with_no_date_asks_for_date(self):
        text = CBC.replace("Sample Collected On : 11/09/2026 08:40 AM", "") \
                  .replace("Sample Received On  : 11/09/2026 10:15 AM", "") \
                  .replace("Reported On         : 12/09/2026 06:30 PM", "")
        r = doc_classifier.classify_text(text)
        self.assertIn("date", r.needs)
        self.assertNotIn("kind", r.needs)

    def test_ambiguous_kind_asks_for_kind(self):
        text = "Dr. Arjun Mehta MBBS. Patient advised the following. Signature."
        r = doc_classifier.classify_text(text)
        self.assertIn("kind", r.needs)


# ── image quality gate ─────────────────────────────────────────────────
def _png(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class ImageQualityTests(SimpleTestCase):
    def setUp(self):
        try:
            from PIL import Image, ImageDraw, ImageFilter  # noqa
        except Exception:
            self.skipTest("Pillow not available")

    def _sharp_page(self):
        """A dense, text-like page: many short strokes at varied positions,
        the way real body copy fills the Laplacian response."""
        import random
        from PIL import Image, ImageDraw
        rng = random.Random(42)
        img = Image.new("L", (1240, 1750), 250)
        d = ImageDraw.Draw(img)
        for line in range(58):
            y = 60 + line * 29
            x = 90
            while x < 1150:
                w = rng.randint(6, 22)
                d.rectangle([x, y, x + w, y + 12], fill=rng.choice((10, 20, 35)))
                x += w + rng.randint(3, 7)
        return img

    def test_sharp_page_passes(self):
        r = image_quality.assess(_png(self._sharp_page()), "image/png")
        self.assertTrue(r.ok, r.detail)

    def test_blurred_page_flagged(self):
        from PIL import ImageFilter
        blurred = self._sharp_page().filter(ImageFilter.GaussianBlur(8))
        r = image_quality.assess(_png(blurred), "image/png")
        self.assertFalse(r.ok, r.detail)
        self.assertEqual(r.reason, "blurry")

    def test_blur_metric_decreases_with_blur(self):
        from PIL import ImageFilter
        sharp = image_quality.assess(_png(self._sharp_page()), "image/png").detail["blur_var"]
        soft = image_quality.assess(_png(self._sharp_page().filter(ImageFilter.GaussianBlur(3))),
                                    "image/png").detail
        # a lightly-softened page still passes but scores lower
        self.assertLess(soft.get("blur_var", 1e9), sharp)

    def test_tiny_image_flagged(self):
        from PIL import Image
        r = image_quality.assess(_png(Image.new("L", (300, 400), 200)), "image/png")
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, "too_small")

    def test_dark_image_flagged(self):
        r = image_quality.assess(_png(self._sharp_page().point(lambda p: p // 12)), "image/png")
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, "too_dark")

    def test_pdf_always_passes_the_gate(self):
        r = image_quality.assess(b"%PDF-1.4 ...", "application/pdf")
        self.assertTrue(r.ok)

    def test_classify_returns_unreadable_for_blur(self):
        from PIL import ImageFilter
        blurred = self._sharp_page().filter(ImageFilter.GaussianBlur(10))
        r = doc_classifier.classify(_png(blurred), "image/png")
        self.assertTrue(r.unreadable)
        self.assertEqual(r.needs, ["file"])
        self.assertIn("blurry", r.quality_reason)


class PdfPathTests(_Det):
    """classify() over a real generated PDF — exercises _pdf_text + the gate."""

    def setUp(self):
        try:
            import reportlab  # noqa
        except Exception:
            self.skipTest("reportlab not available")

    def _pdf(self, text):
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        y = 800
        for line in text.strip().splitlines():
            c.drawString(40, y, line.strip()[:110])
            y -= 12
            if y < 40:
                c.showPage()
                y = 800
        c.showPage()
        c.save()
        return buf.getvalue()

    def test_cbc_pdf_files_as_lab_report_cbc(self):
        r = doc_classifier.classify(self._pdf(CBC), "application/pdf")
        self.assertFalse(r.unreadable)
        self.assertEqual(r.doc_type, "lab_report")
        self.assertEqual(r.categories[:1], ["cbc"])
        self.assertEqual(r.doc_date, date(2026, 9, 11))
        self.assertEqual(r.needs, [])

    def test_prescription_pdf(self):
        r = doc_classifier.classify(self._pdf(PRESCRIPTION), "application/pdf")
        self.assertEqual(r.doc_type, "prescription")
        self.assertEqual(r.categories, [])

    def test_health_package_pdf_multi(self):
        r = doc_classifier.classify(self._pdf(HEALTH_PACKAGE), "application/pdf")
        self.assertEqual(r.doc_type, "lab_report")
        self.assertTrue(r.multi)
        self.assertIn("cbc", r.categories)
        self.assertIn("lipid", r.categories)

    def test_pdf_gate_never_blocks_pdf(self):
        # even a near-empty PDF passes the image gate (it's just "other")
        r = doc_classifier.classify(self._pdf("x"), "application/pdf")
        self.assertFalse(r.unreadable)

    def test_encrypted_pdf_reports_a_specific_reason(self):
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        c.drawString(40, 800, "COMPLETE BLOOD COUNT  Haemoglobin 13.4 g/dL")
        c.showPage()
        c.save()
        # reportlab has no encrypt on Canvas across versions; encrypt via pypdf
        try:
            from pypdf import PdfReader, PdfWriter
        except Exception:
            self.skipTest("pypdf not available")
        w = PdfWriter()
        for p in PdfReader(io.BytesIO(buf.getvalue())).pages:
            w.add_page(p)
        w.encrypt("secret")
        enc = io.BytesIO()
        w.write(enc)
        r = doc_classifier.classify(enc.getvalue(), "application/pdf")
        self.assertTrue(r.unreadable)
        self.assertEqual(r.quality_reason, "encrypted")
        self.assertIn("password", r.quality_message.lower())


class OcrEngineTests(SimpleTestCase):
    """core.ocr — the pluggable OCR layer (RapidOCR primary, Tesseract fallback)."""

    def test_empty_bytes(self):
        r = ocr.run(b"")
        self.assertEqual(r.text, "")
        self.assertEqual(r.engine, "")

    def test_garbage_bytes_never_raise(self):
        r = ocr.run(b"not an image at all")
        self.assertEqual(r.text, "")

    def test_engine_none_disables_ocr(self):
        with self.settings(DOC_OCR_ENGINE="none"):
            self.assertEqual(ocr.available(), "none")
            self.assertEqual(ocr.run(b"\x89PNG\r\n").text, "")

    def test_pdf_page_images_needs_pymupdf(self):
        # returns [] rather than raising when the raw isn't a real PDF /
        # when PyMuPDF is absent — never blows up the classify() path
        self.assertEqual(ocr.pdf_page_images(b"%PDF-1.4 not really"), [])

    def test_classifier_ocr_text_degrades_cleanly(self):
        # no engine + a non-PDF that isn't a valid image -> ("", None)
        with self.settings(DOC_OCR_ENGINE="none"):
            text, conf = doc_classifier._ocr_text(b"xx", "image/png")
        self.assertEqual(text, "")
        self.assertIsNone(conf)

    def test_warmup_is_safe_and_idempotent(self):
        ocr._WARMED = False
        with self.settings(DOC_OCR_ENGINE="none"):
            self.assertEqual(ocr.warmup(), "")   # nothing to load
            self.assertEqual(ocr.warmup(), "")   # no-op second call, no raise
        ocr._WARMED = False


@override_settings(DOC_CLASSIFIER_LLM="", DOC_CLASSIFIER_VISION_MODEL="")
class LayerMergeTests(SimpleTestCase):
    """_apply_opinion — how an LLM / vision answer folds onto the keyword pass."""

    def _res(self, doc_type="other", conf=0.4, det=None, medical=False,
             cats=None, catconf=0.0, doc_date=None, dateconf=0.0):
        r = doc_classifier.ClassResult(doc_type=doc_type, confidence=conf, text_len=200)
        r._det_conf = det if det is not None else conf
        r._medical_signal = medical
        r.categories = list(cats or [])
        r.category_confidence = catconf
        r.doc_date = doc_date
        r.date_confidence = dateconf
        return r

    def test_agreement_raises_confidence(self):
        r = self._res("lab_report", conf=0.60, det=0.60, medical=True)
        doc_classifier._apply_opinion(r, {"kind": "lab_report", "confidence": 0.95}, "llm")
        self.assertGreaterEqual(r.confidence, 0.82)
        self.assertNotIn("kind", r.needs)

    def test_keyword_unsure_takes_the_llm_kind(self):
        r = self._res("other", conf=0.40, det=0.40)
        doc_classifier._apply_opinion(r, {"kind": "prescription", "confidence": 0.9}, "llm")
        self.assertEqual(r.doc_type, "prescription")
        self.assertEqual(r.sources.get("kind"), "llm")

    def test_strong_keyword_is_never_overridden(self):
        r = self._res("prescription", conf=0.95, det=0.95, medical=True)
        doc_classifier._apply_opinion(r, {"kind": "lab_report", "confidence": 0.95}, "vision")
        self.assertEqual(r.doc_type, "prescription")          # kept
        self.assertIn("vision!=prescription", r.notes)

    def test_moderate_disagreement_goes_to_the_patient(self):
        r = self._res("prescription", conf=0.78, det=0.78, medical=True)
        doc_classifier._apply_opinion(r, {"kind": "lab_report", "confidence": 0.85}, "llm")
        self.assertEqual(r.sources.get("kind"), "conflict")
        self.assertIn("kind", r.needs)                        # dropped below the gate

    def test_not_medical_only_without_medical_signal(self):
        r = self._res("other", conf=0.3, medical=False)
        doc_classifier._apply_opinion(r, {"kind": "not_medical", "confidence": 0.99}, "llm")
        self.assertTrue(r.non_medical)

        r2 = self._res("lab_report", conf=0.5, medical=True)
        doc_classifier._apply_opinion(r2, {"kind": "not_medical", "confidence": 0.99}, "llm")
        self.assertFalse(r2.non_medical)                      # medical lean protected

    def test_llm_fills_panel_and_date(self):
        r = self._res("lab_report", conf=0.9, det=0.9, medical=True)  # kind fine, panel+date open
        doc_classifier._apply_opinion(
            r, {"categories": ["thyroid"], "report_date": "2026-09-04", "date_source": "report"}, "llm")
        self.assertEqual(r.categories, ["thyroid"])
        self.assertGreaterEqual(r.category_confidence, 0.80)
        self.assertEqual(r.doc_date, date(2026, 9, 4))
        self.assertEqual(r.sources.get("date"), "llm")

    def test_empty_opinion_is_a_noop(self):
        r = self._res("lab_report", conf=0.9, det=0.9, medical=True)
        before = (r.doc_type, r.confidence)
        doc_classifier._apply_opinion(r, {}, "llm")
        self.assertEqual((r.doc_type, r.confidence), before)


@override_settings(DOC_CLASSIFIER_LLM="core.tests_doc_classifier._stub_llm",
                   DOC_CLASSIFIER_VISION_MODEL="")
class PipelineWithStubbedLlmTests(SimpleTestCase):
    """classify_text end-to-end with the text LLM stubbed — no network."""

    def test_garbled_text_is_rescued_by_the_llm(self):
        r = doc_classifier.classify_text(
            "C0MPL3TE BL00D C0UNT  Haemog|obin l3.4  W8C 72OO  "
            "Samp|e C0||ected 0n 11/O9/2O26  SRL DlAGN0STlCS")
        self.assertEqual(r.doc_type, "lab_report")
        self.assertEqual(r.categories, ["cbc"])
        self.assertEqual(r.doc_date, date(2026, 9, 11))
        self.assertEqual(r.needs, [])
        self.assertEqual(r.sources.get("kind"), "llm")

    def test_confident_keyword_result_skips_the_llm(self):
        global _STUB_CALLS
        _STUB_CALLS = 0
        doc_classifier.classify_text(CBC)
        self.assertEqual(_STUB_CALLS, 0)   # keyword was sure -> LLM never called


_STUB_CALLS = 0


def _stub_llm(text):
    """Test double for the text-LLM callable."""
    global _STUB_CALLS
    _STUB_CALLS += 1
    low = text.lower()
    if "bl00d c0unt" in low or "blood count" in low:
        return {"kind": "lab_report", "categories": ["cbc"],
                "report_date": "2026-09-11", "date_source": "collection", "confidence": 0.95}
    return {}
