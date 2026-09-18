"""
Management command: seed_lakshmi_family_demo

One-off demo seeding for the specific patient account already used
throughout mobile-app testing (Lakshmi Krishnan, AWPID-20260812-X8YF7UT4)
and her two existing dependants, for the 18 Sep 2026 Patients App demo.

What this does:
  1. Ages the two existing dependants to a clean 7 and 9 (Diya, Aarav) —
     they were previously 6 and a newborn, left over from an earlier
     pediatric-demo run and not what today's demo needs.
  2. Rebuilds BOTH children's vaccination history from scratch, consistent
     with their new birthdates: every dose through the "5 years" milestone
     recorded as verified/clinic-administered, and the "6 years" (Typhoid
     Booster) milestone deliberately left unrecorded for both — since both
     are now past that age, it shows up as a real, unfabricated "due/
     overdue" item on the roadmap. Rebuilt rather than DOB-shifted only,
     because the old rows' administered_date values were tied to the old
     (wrong) birthdates and would otherwise read as administered before
     birth / years after the labelled milestone.
  3. Adds documents that were genuinely missing for a "reports and
     prescriptions" demo story: an X-ray for Lakshmi (she had none), a lab
     report for Diya (she had prescriptions but no reports), and one of
     each for Aarav (he had neither).

Deliberately scoped to these three specific people, not a generic seeder —
re-running it is safe (vaccination rows are fully replaced each time; new
documents are only added if a document with the same title doesn't already
exist for that awpid).

Usage:
  python manage.py seed_lakshmi_family_demo
"""

import base64
from datetime import date, timedelta
from io import BytesIO

from django.core.management.base import BaseCommand
from django.db import transaction


LAKSHMI_AWPID = "AWPID-20260812-X8YF7UT4"
DIYA_AWPID = "AWPID-20260812-S1CNZSUV"
AARAV_AWPID = "AWPID-20260812-M0OF7AW7"

TODAY = date(2026, 9, 17)

# vaccine_name, scheduled_label, due_days — exact copy of the seeded
# "Default Schedule" (apps/registry/migrations/0018_seed_default_vaccination_schedule.py).
# Only the milestones through "5 years" are recorded here; "6 years" and
# "10 years" are left out on purpose (see module docstring).
_SCHEDULE = [
    ("BCG",               "Birth",        0),
    ("Hepatitis B - 1",   "Birth",        0),
    ("OPV - 0",           "Birth",        0),
    ("DTP - 1",           "6 weeks",      42),
    ("OPV - 1",           "6 weeks",      42),
    ("Hepatitis B - 2",   "6 weeks",      42),
    ("DTP - 2",           "10 weeks",     70),
    ("OPV - 2",           "10 weeks",     70),
    ("DTP - 3",           "14 weeks",     98),
    ("OPV - 3",           "14 weeks",     98),
    ("Hepatitis B - 3",   "14 weeks",     98),
    ("Measles - 1",       "9 months",     274),
    ("MMR - 1",           "9 months",     274),
    ("MMR - 2 (Booster)", "16-18 months", 548),
    ("DTP Booster - 1",   "16-18 months", 548),
    ("DTP Booster - 2",   "5 years",      1825),
]


def _pdf_lab_report(hospital_name, patient_name, uhid, doctor_name, test_name, report_number, items, notes=""):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    y = height - 25 * mm

    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, y, hospital_name)
    y -= 7 * mm
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, y, "Laboratory Report")
    y -= 10 * mm

    c.drawString(20 * mm, y, f"Report No: {report_number}")
    c.drawString(120 * mm, y, f"Date: {date.today().strftime('%d-%b-%Y')}")
    y -= 6 * mm
    c.drawString(20 * mm, y, f"Patient: {patient_name}  (UHID: {uhid})")
    y -= 6 * mm
    c.drawString(20 * mm, y, f"Referring Doctor: {doctor_name}")
    y -= 6 * mm
    c.drawString(20 * mm, y, f"Test: {test_name}")
    y -= 10 * mm

    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, "Parameter")
    c.drawString(90 * mm, y, "Result")
    c.drawString(120 * mm, y, "Unit")
    c.drawString(140 * mm, y, "Reference Range")
    y -= 5 * mm
    c.line(20 * mm, y, 190 * mm, y)
    y -= 6 * mm

    c.setFont("Helvetica", 9)
    for item in items:
        c.drawString(20 * mm, y, str(item["parameter_name"])[:35])
        c.drawString(90 * mm, y, str(item["result_value"]))
        c.drawString(120 * mm, y, str(item.get("unit", "")))
        c.drawString(140 * mm, y, str(item.get("reference_range", "")))
        y -= 6 * mm

    if notes:
        y -= 6 * mm
        c.setFont("Helvetica-Oblique", 9)
        c.drawString(20 * mm, y, f"Notes: {notes}")

    c.setFont("Helvetica", 8)
    c.drawString(20 * mm, 15 * mm, "System-generated demo report — Atomwalk HMS.")
    c.showPage()
    c.save()

    pdf_bytes = buf.getvalue()
    buf.close()
    b64 = base64.b64encode(pdf_bytes).decode("ascii")
    return f"data:application/pdf;base64,{b64}"


def _generic_pdf(title, lines):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    y = height - 25 * mm
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20 * mm, y, title)
    y -= 12 * mm
    c.setFont("Helvetica", 10)
    for line in lines:
        c.drawString(20 * mm, y, line)
        y -= 7 * mm
    c.showPage()
    c.save()
    pdf_bytes = buf.getvalue()
    buf.close()
    return f"data:application/pdf;base64,{base64.b64encode(pdf_bytes).decode('ascii')}"


class Command(BaseCommand):
    help = "Seed a real-life family demo (reports, prescriptions, X-ray, vaccinations) for Lakshmi Krishnan's account"

    def handle(self, *args, **options):
        try:
            import reportlab  # noqa: F401
        except ImportError:
            self.stderr.write(self.style.ERROR(
                "reportlab is not installed. Run: pip install reportlab"))
            return

        from apps.registry.models import PatientIdentity, SharedVaccination, SharedDocument
        from core import storage as blob_storage

        with transaction.atomic(using="default"):
            # ── 1. age the two dependants ────────────────────────────────
            diya = PatientIdentity.objects.using("default").get(awpid=DIYA_AWPID)
            aarav = PatientIdentity.objects.using("default").get(awpid=AARAV_AWPID)

            diya_dob = date(2019, 4, 18)   # -> 7 years old as of 17 Sep 2026
            aarav_dob = date(2017, 1, 22)  # -> 9 years old as of 17 Sep 2026
            diya.date_of_birth = diya_dob
            aarav.date_of_birth = aarav_dob
            diya.save(using="default", update_fields=["date_of_birth"])
            aarav.save(using="default", update_fields=["date_of_birth"])
            self.stdout.write(self.style.SUCCESS(
                f"  Diya Krishnan -> DOB {diya_dob} (7 yrs)   Aarav Krishnan -> DOB {aarav_dob} (9 yrs)"))

            # ── 2. rebuild vaccination history for both, relative to the
            #      new birthdates. Full replace, not a DOB-only shift.
            #      Every completed dose also gets an uploaded certificate —
            #      GrowthVaccinationChart/RecordsPage/HealthTimeline all gate
            #      "View Certificate" purely on has_certificate + record_id,
            #      regardless of source, so a clinic-administered row needs
            #      the same real S3 file_data a self-reported upload gets
            #      (see the note on _ensure_vax_certificate below — no bare
            #      data: URI here, PortalVaccinationFileView has no fallback
            #      for one). ────────────────────────────────────────────────
            for awpid, dob, full_name in [(DIYA_AWPID, diya_dob, "Diya Krishnan"), (AARAV_AWPID, aarav_dob, "Aarav Krishnan")]:
                SharedVaccination.objects.using("default").filter(awpid=awpid).delete()
                identity = blob_storage.identity_slug(name=full_name, identifier=awpid)
                rows = []
                for vaccine_name, sched_label, due_days in _SCHEDULE:
                    # a realistic few-day-to-few-week real-world scheduling
                    # slip, not administered exactly on the due date
                    slip = 3 if due_days == 0 else min(21, max(3, due_days // 20))
                    administered = dob + timedelta(days=due_days + slip)
                    mime_type = "application/pdf"
                    cert_pdf = _generic_pdf("VACCINATION CERTIFICATE", [
                        "Lakeview Multispecialty Hospital, Bengaluru",
                        "",
                        f"Patient: {full_name}     AWPID: {awpid}",
                        f"Vaccine: {vaccine_name}     Schedule slot: {sched_label}",
                        f"Date of Administration: {administered.strftime('%d-%b-%Y')}",
                        "",
                        "This certifies that the above-named individual has received",
                        "the vaccination indicated on this certificate.",
                        "",
                        "-- Dr. Ananya Iyer, MBBS, MD Pediatrics",
                    ])
                    file_key = blob_storage.upload_data_uri(
                        cert_pdf, prefix="vaccination-certs", mime_type=mime_type,
                        category="vaccination-certificate", identity=identity,
                    )
                    file_name = blob_storage.display_file_name(
                        "vaccination-certificate", mime_type,
                        detail=vaccine_name, name=full_name, identifier=awpid,
                    )
                    rows.append(SharedVaccination(
                        awpid=awpid, vaccine_name=vaccine_name, scheduled_label=sched_label,
                        administered_date=administered, source="clinic",
                        verification_status="verified", recorded_by="staff",
                        file_name=file_name, mime_type=mime_type, file_data=file_key,
                    ))
                SharedVaccination.objects.using("default").bulk_create(rows)
                self.stdout.write(self.style.SUCCESS(
                    f"  {full_name}: {len(rows)} vaccinations recorded (Birth to 5 years), each with a "
                    f"certificate on file; Typhoid Booster (6 years) left due/overdue on purpose"))

            # ── 3. fill the genuinely missing documents ──────────────────
            def _ensure_doc(awpid, title, **fields):
                if SharedDocument.objects.using("default").filter(awpid=awpid, title=title, deleted_at__isnull=True).exists():
                    self.stdout.write(f"  (already exists) {title}")
                    return
                SharedDocument.objects.using("default").create(
                    awpid=awpid, title=title, uploaded_by="patient", source_tenant_id=None,
                    verification_status="unverified", review_state="filed",
                    classification_method="keyword", **fields,
                )
                self.stdout.write(self.style.SUCCESS(f"  + {title}"))

            # Lakshmi — X-ray (the one thing her otherwise well-stocked
            # vault was missing)
            xray_pdf = _generic_pdf("CHEST X-RAY REPORT", [
                "Apollo Diagnostic Centre, Bengaluru",
                "",
                f"Patient: Lakshmi Krishnan     Age/Sex: 36 / F",
                f"Date: 20-Aug-2026     Ref. Doctor: Dr. Vikram Rao",
                "",
                "Examination: Chest X-Ray (PA view)",
                "",
                "Findings:",
                "  Lung fields are clear bilaterally. No focal consolidation,",
                "  effusion or pneumothorax. Cardiac silhouette is normal in",
                "  size and contour. Bony thorax unremarkable.",
                "",
                "Impression:",
                "  No acute cardiopulmonary abnormality detected.",
                "",
                "-- Dr. Rohan Kapoor, MD Radiology",
            ])
            _ensure_doc(
                LAKSHMI_AWPID, "Chest X-Ray Report — 20 Aug 2026",
                doc_type="scan", file_name="chest_xray_20aug2026.pdf", mime_type="application/pdf",
                file_data=xray_pdf, document_date=date(2026, 8, 20), date_source="report",
                hospital_label="Apollo Diagnostic Centre", doctor_label="Dr. Rohan Kapoor",
            )

            # Diya (7) — a lab report to go with her existing prescriptions
            diya_cbc = _pdf_lab_report(
                "Lakeview Multispecialty Hospital", "Diya Krishnan", "LKV-DIYA-07",
                "Dr. Ananya Iyer", "Complete Blood Count (CBC)", "LKV-LAB-88231",
                [
                    {"parameter_name": "Hemoglobin", "result_value": "12.6", "unit": "g/dL", "reference_range": "11.5-15.5"},
                    {"parameter_name": "WBC Count", "result_value": "7200", "unit": "/µL", "reference_range": "5000-13000"},
                    {"parameter_name": "Platelet Count", "result_value": "285000", "unit": "/µL", "reference_range": "150000-450000"},
                ],
                notes="Routine well-child check-up. All parameters within normal pediatric range.",
            )
            _ensure_doc(
                DIYA_AWPID, "Complete Blood Count — 10 Jul 2026",
                doc_type="lab_report", file_name="diya_cbc_10jul2026.pdf", mime_type="application/pdf",
                file_data=diya_cbc, document_date=date(2026, 7, 10), date_source="report",
                report_categories=["cbc"], category_method="keyword",
                hospital_label="Lakeview Multispecialty Hospital", doctor_label="Dr. Ananya Iyer",
            )

            # Aarav (9) — had neither a report nor a prescription
            aarav_rx = _generic_pdf("PRESCRIPTION", [
                "Lakeview Multispecialty Hospital",
                "",
                "Patient: Aarav Krishnan     Age/Sex: 9 / M",
                "Date: 05-Aug-2026     Dr. Ananya Iyer (Pediatrics)",
                "",
                "Diagnosis: Acute Pharyngitis",
                "",
                "Rx:",
                "  1. Amoxicillin 250mg Syrup - 5ml twice daily x 5 days",
                "  2. Paracetamol 250mg Syrup - 5ml SOS for fever, max 3x/day",
                "  3. Warm saline gargles twice daily",
                "",
                "Advice: Adequate fluids and rest. Review after 5 days if",
                "symptoms persist.",
                "",
                "-- Dr. Ananya Iyer, MBBS, MD Pediatrics",
            ])
            _ensure_doc(
                AARAV_AWPID, "Prescription — 05 Aug 2026",
                doc_type="prescription", file_name="aarav_rx_05aug2026.pdf", mime_type="application/pdf",
                file_data=aarav_rx, document_date=date(2026, 8, 5), date_source="report",
                hospital_label="Lakeview Multispecialty Hospital", doctor_label="Dr. Ananya Iyer",
            )
            aarav_vitd = _pdf_lab_report(
                "Lakeview Multispecialty Hospital", "Aarav Krishnan", "LKV-AARAV-09",
                "Dr. Ananya Iyer", "Vitamin D (25-OH)", "LKV-LAB-88450",
                [
                    {"parameter_name": "Vitamin D (25-OH)", "result_value": "22.4", "unit": "ng/mL", "reference_range": "30-100"},
                ],
                notes="Mildly low — recommend Vitamin D3 supplementation and sun exposure; recheck in 3 months.",
            )
            _ensure_doc(
                AARAV_AWPID, "Vitamin D (25-OH) — 05 Aug 2026",
                doc_type="lab_report", file_name="aarav_vitd_05aug2026.pdf", mime_type="application/pdf",
                file_data=aarav_vitd, document_date=date(2026, 8, 5), date_source="report",
                report_categories=["vitamin"], category_method="keyword",
                hospital_label="Lakeview Multispecialty Hospital", doctor_label="Dr. Ananya Iyer",
            )

            # ── 4. self-reported vaccination certificates ────────────────
            # Every vaccination row seeded above is source="clinic" with no
            # file attached (a clinician logged it directly — nothing to
            # scan). That leaves the self-reported-upload + certificate-
            # review feature with no seeded data to demo. Unlike
            # SharedDocument.file_data (read back as-is when it's a raw
            # "data:" URI — see PortalDocumentDetailView), PortalVaccination-
            # FileView always calls blob_storage.signed_url() on file_data
            # with no such fallback, so this must go through the same
            # upload_data_uri() S3 path PortalVaccinationUploadView uses —
            # a bare data: URI here would 500/break when viewed.
            def _ensure_vax_certificate(awpid, patient_name, vaccine_name, administered_date, cert_lines):
                if SharedVaccination.objects.using("default").filter(
                    awpid=awpid, vaccine_name=vaccine_name, source=SharedVaccination.SOURCE_SELF_REPORTED,
                ).exists():
                    self.stdout.write(f"  (already exists) {vaccine_name} certificate — {patient_name}")
                    return
                mime_type = "application/pdf"
                identity = blob_storage.identity_slug(name=patient_name, identifier=awpid)
                file_key = blob_storage.upload_data_uri(
                    _generic_pdf("VACCINATION CERTIFICATE", cert_lines),
                    prefix="vaccination-certs", mime_type=mime_type,
                    category="vaccination-certificate", identity=identity,
                )
                file_name = blob_storage.display_file_name(
                    "vaccination-certificate", mime_type,
                    detail=vaccine_name, name=patient_name, identifier=awpid,
                )
                SharedVaccination.objects.using("default").create(
                    awpid=awpid, vaccine_name=vaccine_name, scheduled_label="",
                    administered_date=administered_date, source=SharedVaccination.SOURCE_SELF_REPORTED,
                    verification_status=SharedVaccination.STATUS_PENDING,
                    file_name=file_name, mime_type=mime_type, file_data=file_key,
                    recorded_by="patient",
                )
                self.stdout.write(self.style.SUCCESS(f"  + {vaccine_name} certificate — {patient_name} (pending review)"))

            # Diya — a flu shot taken at an outside camp, not part of the
            # standard schedule, uploaded by the parent and awaiting a
            # doctor's review (the roadmap should show it as an "extra"
            # record with has_certificate=true, not auto-verified).
            _ensure_vax_certificate(
                DIYA_AWPID, "Diya Krishnan", "Influenza Vaccine", date(2026, 9, 1),
                [
                    "Apollo Wellness Immunization Camp, Bengaluru",
                    "",
                    "Beneficiary: Diya Krishnan     Age/Sex: 7 / F",
                    "Vaccine: Influenza (Quadrivalent)     Dose: Annual",
                    "Date of Administration: 01-Sep-2026",
                    "Batch No: FLU-2026-4471     Manufacturer: Sanofi Pasteur",
                    "",
                    "This certifies that the above-named individual has received",
                    "the vaccination indicated on this certificate.",
                    "",
                    "-- Dr. Kiran Bhatt, Camp Medical Officer",
                ],
            )

            # Aarav — Hepatitis A given at a community camp, same
            # self-reported/pending story.
            _ensure_vax_certificate(
                AARAV_AWPID, "Aarav Krishnan", "Hepatitis A - 1", date(2026, 8, 25),
                [
                    "Community Health Immunization Camp, HSR Layout",
                    "",
                    "Beneficiary: Aarav Krishnan     Age/Sex: 9 / M",
                    "Vaccine: Hepatitis A - Dose 1",
                    "Date of Administration: 25-Aug-2026",
                    "Batch No: HEPA-2026-1182     Manufacturer: GSK",
                    "",
                    "This certifies that the above-named individual has received",
                    "the vaccination indicated on this certificate.",
                    "",
                    "-- Dr. Meera Nair, Camp Medical Officer",
                ],
            )

        self.stdout.write(self.style.SUCCESS("\nDone."))
