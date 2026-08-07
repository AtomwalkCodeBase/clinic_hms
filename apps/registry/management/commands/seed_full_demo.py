"""
Management command: seed_full_demo

Seeds a complete, demo-ready dataset across 4 brand-new hospital tenants:
staff for every role (hospital admin, doctor, nurse, front desk, lab tech,
pharmacist), a lab test catalog, and patients spread across the real
appointment lifecycle (waiting in queue, vitals recorded, booked ahead,
and fully completed with a signed consultation + prescription + a real
PDF lab report). It also creates one flagship patient at the first hospital
with a full visit history but deliberately does NOT touch the second
hospital for her — that's the live part of the demo (see instructions
printed at the end and in DEMO_CREDENTIALS.md).

Nothing here invents fake ratings/reviews — every number is either backend
data (queue position, consultation counts) or clearly-labelled demo content
(vitals, lab values) generated the same way front-desk/lab-tech staff would
enter it for a real patient.

Idempotent per hospital: if a hospital's subdomain already exists, that
hospital is skipped entirely (not re-seeded) so this is safe to re-run
after partial failures. The flagship patient is skipped if already present.

Usage:
  python manage.py seed_full_demo --settings=atomwalk.settings.development

Requires reportlab for PDF generation:
  pip install reportlab --break-system-packages   (or: pip install -r requirements.txt)
"""

import base64
import itertools
import logging
from datetime import date, datetime, time as dtime, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.tenants.models import Tenant, Subscription
from apps.tenants.utils import create_tenant_database, run_tenant_migrations, _make_db_config
from apps.tenants.management.commands.provision_tenant import TIER_FEATURE_DEFAULTS
from apps.org.models import Branch, StaffUser, DoctorProfile, NextNumber
from apps.registry.models import StaffEmailIndex, PatientAccount, PortalBooking, SharedDocument
from apps.patients.models import Patient, Allergy
from apps.patients.services import PatientService
from apps.opd.models import Appointment, Vitals, OPDEncounter, Prescription, PrescriptionItem
from apps.lab.models import LabTest, LabRequest, LabReport, LabReportItem
from apps.lab.management.commands.seed_lab_catalog import STARTER_TESTS
from core.utils.nntm import get_next_number
from core.db_router import _thread_local

logger = logging.getLogger(__name__)

STAFF_PASSWORD = "Demo@12345"
PATIENT_PASSWORD = "Patient@12345"

HOSPITALS = [
    dict(name="Lakeview Multispecialty Hospital", subdomain="lakeview-demo",
         city="Bengaluru", state="Karnataka", code="LKV",
         accreditations="NABH, ISO 9001:2015",
         about="A 120-bed multispecialty hospital in Bengaluru known for its cardiology and orthopedics units."),
    dict(name="Horizon Care Hospital", subdomain="horizon-care-demo",
         city="Chennai", state="Tamil Nadu", code="HCH",
         accreditations="NABH",
         about="A community multispecialty hospital in Chennai focused on family medicine, women's health, and pediatrics."),
    dict(name="Cedar Health Hospital", subdomain="cedar-health-demo",
         city="Hyderabad", state="Telangana", code="CHH",
         accreditations="NABH, NABL",
         about="A diagnostics-forward hospital in Hyderabad with an in-house lab and a strong endocrinology practice."),
    dict(name="Metro Wellness Hospital", subdomain="metro-wellness-demo",
         city="Pune", state="Maharashtra", code="MWH",
         accreditations="ISO 9001:2015",
         about="A modern day-care and OPD-focused hospital in Pune serving IT-corridor families."),
]

CITY_LANGUAGE = {"Bengaluru": "Kannada", "Chennai": "Tamil", "Hyderabad": "Telugu", "Pune": "Marathi"}

SPECIALTIES = [
    dict(spec="General Medicine",  known_for="Fever, Diabetes, Hypertension, General checkups", fee=500),
    dict(spec="Pediatrics",        known_for="Child immunization, Growth concerns, Common infections", fee=450),
    dict(spec="Orthopedics",       known_for="Joint pain, Fractures, Back pain, Sports injuries", fee=700),
    dict(spec="Gynecology",        known_for="Pregnancy care, PCOS, Menstrual disorders", fee=650),
    dict(spec="Cardiology",        known_for="Chest pain, Hypertension, Heart checkups", fee=900),
    dict(spec="Dermatology",       known_for="Skin allergies, Acne, Hair fall", fee=550),
    dict(spec="ENT",               known_for="Sinusitis, Hearing issues, Throat infections", fee=500),
    dict(spec="Endocrinology",     known_for="Diabetes, Thyroid disorders, Hypertension", fee=800),
    dict(spec="Pulmonology",       known_for="Asthma, Chronic cough, Breathlessness", fee=750),
    dict(spec="Gastroenterology",  known_for="Acidity, IBS, Liver disorders", fee=700),
    dict(spec="Nephrology",        known_for="Kidney stones, CKD, Hypertension", fee=800),
    dict(spec="Psychiatry",        known_for="Anxiety, Depression, Sleep disorders", fee=600),
]

DOCTOR_NAMES = [
    ("Vikram", "Rao", "M"), ("Ananya", "Iyer", "F"), ("Karan", "Sethi", "M"),
    ("Meera", "Nair", "F"), ("Rohan", "Kapoor", "M"), ("Divya", "Menon", "F"),
    ("Aditya", "Desai", "M"), ("Priya", "Bhatt", "F"), ("Suresh", "Reddy", "M"),
    ("Neha", "Joshi", "F"), ("Farhan", "Ali", "M"), ("Kavya", "Krishnan", "F"),
]
NURSE_NAMES = [
    ("Lakshmi", "Pillai", "F"), ("Ramesh", "Kumar", "M"), ("Sunita", "Yadav", "F"),
    ("Arvind", "Shetty", "M"), ("Pooja", "Verma", "F"), ("Manoj", "Tiwari", "M"),
    ("Geeta", "Pandey", "F"), ("Vishal", "Bose", "M"), ("Anjali", "Chauhan", "F"),
    ("Deepak", "Mishra", "M"), ("Swati", "Ghosh", "F"), ("Ritesh", "Kulkarni", "M"),
]
FRONT_DESK_NAMES = [("Sanjay", "Kumar", "M"), ("Kirti", "Shah", "F"), ("Manish", "Trivedi", "M"), ("Rekha", "Iyer", "F")]
LAB_TECH_NAMES   = [("Prakash", "Naidu", "M"), ("Shreya", "Kulkarni", "F"), ("Anil", "Chopra", "M"), ("Bhavna", "Rathi", "F")]
PHARMACIST_NAMES = [("Ajay", "Bhosale", "M"), ("Nandini", "Rao", "F"), ("Sameer", "Qureshi", "M"), ("Tanvi", "Deshmukh", "F")]
ADMIN_NAMES      = [("Ravi", "Malhotra", "M"), ("Sonal", "Agarwal", "F"), ("Imran", "Sheikh", "M"), ("Radhika", "Nambiar", "F")]

PATIENT_FIRST = [
    "Aarav", "Ishaan", "Kabir", "Vivaan", "Reyansh", "Aisha", "Zara", "Myra", "Anaya", "Diya",
    "Rahul", "Amit", "Sunil", "Vikas", "Gaurav", "Nisha", "Pooja", "Kavita", "Sneha", "Rina",
    "Yusuf", "Imran", "Salman", "Fatima", "Ayesha", "Sana", "Nida", "Arjun", "Rohit",
    "Siddharth", "Varun", "Nikhil", "Abhishek", "Tarun", "Shalini", "Preeti", "Sarika", "Meenal",
]
PATIENT_LAST = [
    "Sharma", "Verma", "Gupta", "Singh", "Patel", "Reddy", "Nair", "Iyer", "Menon", "Rao",
    "Khan", "Sheikh", "Ansari", "Das", "Bose", "Chatterjee", "Mukherjee", "Pillai", "Naidu", "Kulkarni",
]

COMPLAINTS = [
    "Fever and body ache since 3 days", "Persistent cough and cold", "Lower back pain",
    "Frequent headaches", "Joint pain in knees", "Skin rash and itching",
    "Acidity and stomach discomfort", "Shortness of breath on exertion",
    "High blood pressure follow-up", "Routine diabetes checkup",
    "Sore throat and difficulty swallowing", "Dizziness and fatigue",
]
DIAGNOSES = [
    {"code": "J06.9",   "description": "Acute upper respiratory infection"},
    {"code": "M54.5",   "description": "Low back pain"},
    {"code": "E11.9",   "description": "Type 2 diabetes mellitus without complications"},
    {"code": "I10",     "description": "Essential (primary) hypertension"},
    {"code": "L30.9",   "description": "Dermatitis, unspecified"},
    {"code": "K21.9",   "description": "Gastro-esophageal reflux disease"},
    {"code": "J45.909", "description": "Asthma, unspecified"},
    {"code": "M25.561", "description": "Pain in right knee"},
]
DRUGS = [
    {"drug_name": "Paracetamol",   "dosage": "650mg", "frequency": "td", "route": "oral", "duration_days": 5,  "instructions": "After food"},
    {"drug_name": "Azithromycin",  "dosage": "500mg", "frequency": "od", "route": "oral", "duration_days": 3,  "instructions": "Before food"},
    {"drug_name": "Metformin",     "dosage": "500mg", "frequency": "bd", "route": "oral", "duration_days": 30, "instructions": "After food"},
    {"drug_name": "Amlodipine",    "dosage": "5mg",   "frequency": "od", "route": "oral", "duration_days": 30, "instructions": "In the morning"},
    {"drug_name": "Cetirizine",    "dosage": "10mg",  "frequency": "od", "route": "oral", "duration_days": 7,  "instructions": "At night"},
    {"drug_name": "Pantoprazole",  "dosage": "40mg",  "frequency": "od", "route": "oral", "duration_days": 14, "instructions": "Before breakfast"},
]

_mobile_counter = itertools.count(7000000000)


def _next_mobile():
    return str(next(_mobile_counter))


def _register_db(db_name):
    if db_name not in settings.DATABASES:
        settings.DATABASES[db_name] = _make_db_config(db_name)


def _pdf_lab_report(hospital_name, patient_name, uhid, doctor_name, test_name, report_number, items, notes=""):
    """Build a real, plausible-looking lab report PDF and return it as a base64 data URI."""
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
        if y < 30 * mm:
            c.showPage()
            y = height - 25 * mm
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
    """Small generic PDF used for the flagship patient's outside-document upload."""
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


def _sample_items(test_name, rng):
    tn = test_name.lower()
    if "count" in tn or "cbc" in tn:
        return [
            {"parameter_name": "Hemoglobin", "result_value": f"{rng.randint(11, 15)}.0", "unit": "g/dL", "reference_range": "13.0-17.0", "is_abnormal": False},
            {"parameter_name": "WBC Count", "result_value": str(rng.randint(4000, 11000)), "unit": "/µL", "reference_range": "4000-11000", "is_abnormal": False},
            {"parameter_name": "Platelet Count", "result_value": str(rng.randint(150000, 400000)), "unit": "/µL", "reference_range": "150000-400000", "is_abnormal": False},
        ]
    if "sugar" in tn or "hba1c" in tn:
        abnormal = rng.random() < 0.35
        return [{"parameter_name": "HbA1c" if "hba1c" in tn else "Blood Glucose",
                  "result_value": f"{rng.uniform(6.5, 9.0):.1f}" if "hba1c" in tn else str(rng.randint(85, 160)),
                  "unit": "%" if "hba1c" in tn else "mg/dL",
                  "reference_range": "<5.7" if "hba1c" in tn else "70-100",
                  "is_abnormal": abnormal}]
    if "lipid" in tn:
        return [
            {"parameter_name": "Total Cholesterol", "result_value": str(rng.randint(150, 230)), "unit": "mg/dL", "reference_range": "<200", "is_abnormal": rng.random() < 0.3},
            {"parameter_name": "HDL", "result_value": str(rng.randint(35, 60)), "unit": "mg/dL", "reference_range": ">40", "is_abnormal": False},
            {"parameter_name": "LDL", "result_value": str(rng.randint(80, 150)), "unit": "mg/dL", "reference_range": "<100", "is_abnormal": rng.random() < 0.3},
        ]
    if "thyroid" in tn:
        return [{"parameter_name": "TSH", "result_value": f"{rng.uniform(0.5, 5.5):.2f}", "unit": "mIU/L", "reference_range": "0.4-4.0", "is_abnormal": rng.random() < 0.3}]
    if "liver" in tn:
        return [
            {"parameter_name": "SGOT", "result_value": str(rng.randint(15, 45)), "unit": "U/L", "reference_range": "5-40", "is_abnormal": rng.random() < 0.3},
            {"parameter_name": "SGPT", "result_value": str(rng.randint(10, 50)), "unit": "U/L", "reference_range": "7-56", "is_abnormal": False},
        ]
    if "kidney" in tn:
        return [
            {"parameter_name": "Creatinine", "result_value": f"{rng.uniform(0.6, 1.3):.1f}", "unit": "mg/dL", "reference_range": "0.6-1.3", "is_abnormal": False},
            {"parameter_name": "Urea", "result_value": str(rng.randint(15, 40)), "unit": "mg/dL", "reference_range": "7-20", "is_abnormal": rng.random() < 0.2},
        ]
    if "urine" in tn:
        return [
            {"parameter_name": "Appearance", "result_value": "Clear", "unit": "", "reference_range": "Clear", "is_abnormal": False},
            {"parameter_name": "Pus Cells", "result_value": str(rng.randint(0, 8)), "unit": "/hpf", "reference_range": "0-5", "is_abnormal": rng.random() < 0.3},
        ]
    return [{"parameter_name": "Result", "result_value": "Within normal limits", "unit": "", "reference_range": "", "is_abnormal": False}]


def _random_dob(rng):
    age = rng.randint(8, 75)
    year = date.today().year - age
    month = rng.randint(1, 12)
    day = rng.randint(1, 28)
    return date(year, month, day)


def _patient_name_iter(rng):
    combos = [(f, l) for f in PATIENT_FIRST for l in PATIENT_LAST]
    rng.shuffle(combos)
    return iter(combos)


class Command(BaseCommand):
    help = "Seed a full demo dataset: 4 hospitals, all staff roles, patients across the appointment lifecycle, real PDF lab reports, and a flagship cross-hospital HIE consent scenario."

    def handle(self, *args, **options):
        import random
        rng = random.Random(20260805)

        try:
            import reportlab  # noqa: F401
        except ImportError:
            raise CommandError(
                "reportlab is not installed. Run: pip install reportlab --break-system-packages "
                "(or: pip install -r requirements.txt) and re-run this command."
            )

        credentials_lines = ["# Atomwalk HMS — Demo Credentials\n",
                              f"Generated: {timezone.now().strftime('%d-%b-%Y %H:%M')}\n",
                              f"\nDefault staff password (all roles, all hospitals): `{STAFF_PASSWORD}`\n",
                              f"Default patient portal password: `{PATIENT_PASSWORD}`\n"]

        patient_names = _patient_name_iter(rng)
        seeded_tenants = []

        for h_idx, hinfo in enumerate(HOSPITALS):
            self.stdout.write(f"\n{'=' * 70}\n  {hinfo['name']} ({hinfo['subdomain']})\n{'=' * 70}")

            if Tenant.objects.filter(subdomain=hinfo["subdomain"]).exists():
                self.stdout.write(self.style.WARNING("  Already exists — skipping (not re-seeded)."))
                tenant = Tenant.objects.get(subdomain=hinfo["subdomain"])
                seeded_tenants.append((hinfo, tenant))
                continue

            tenant = Tenant.objects.create(
                name=hinfo["name"], subdomain=hinfo["subdomain"],
                db_name=f"aw_{hinfo['subdomain'].replace('-', '_')}",
                city=hinfo["city"], state=hinfo["state"],
                accreditations=hinfo["accreditations"], about=hinfo["about"],
                is_active=True,
            )
            Subscription.objects.create(tenant=tenant, license_tier="growth", status="active", **TIER_FEATURE_DEFAULTS["growth"])

            db = tenant.db_name
            self.stdout.write(f"  Creating database {db}...")
            create_tenant_database(db)
            self.stdout.write("  Running migrations...")
            run_tenant_migrations(db)
            _register_db(db)
            _thread_local.tenant_id = tenant.id
            _thread_local.db_alias = db

            branch = Branch.objects.using(db).create(
                name=hinfo["name"], city=hinfo["city"], state=hinfo["state"], is_active=True,
            )

            for entity, prefix, pad in [
                ("uhid", f"{hinfo['code']}-", 6), ("invoice", "INV-", 6),
                ("lab_report", "LR-", 6), ("lab_test", "LT-", 4),
                ("prescription", "RX-", 6), ("queue", "", 4),
            ]:
                NextNumber.objects.using(db).get_or_create(
                    branch_id=branch.id, entity=entity, defaults={"prefix": prefix, "pad_length": pad, "last_number": 0},
                )

            existing_tests = set()
            for name, sample_type, price, turnaround, desc in STARTER_TESTS:
                if name.lower() in existing_tests:
                    continue
                code, _ = get_next_number(branch_id=branch.id, entity="lab_test", using=db)
                LabTest.objects.using(db).create(
                    name=name, code=code, sample_type=sample_type, turnaround_hours=turnaround,
                    price=price, description=desc, is_active=True,
                )
                existing_tests.add(name.lower())
            lab_tests = list(LabTest.objects.using(db).all())

            language = f"English, Hindi, {CITY_LANGUAGE[hinfo['city']]}"

            admin_first, admin_last, _ = ADMIN_NAMES[h_idx]
            admin_email = f"{admin_first.lower()}.admin@{hinfo['subdomain']}.demo"
            admin = self._make_staff(db, tenant, "hospital_admin", admin_first, admin_last, admin_email, branch)

            doctors = []
            for d_i in range(3):
                spec = SPECIALTIES[(h_idx * 3 + d_i) % len(SPECIALTIES)]
                first, last, gender = DOCTOR_NAMES[(h_idx * 3 + d_i) % len(DOCTOR_NAMES)]
                email = f"{first.lower()}.doctor{d_i + 1}@{hinfo['subdomain']}.demo"
                staff = self._make_staff(db, tenant, "doctor", first, last, email, branch)
                exp = rng.randint(5, 20)
                DoctorProfile.objects.using(db).create(
                    staff=staff, registration_no=f"NMC-{100000 + staff.id}",
                    specialisation=spec["spec"], qualification="MBBS, MD",
                    gender=gender, experience_years=exp,
                    consultation_fee=Decimal(str(spec["fee"])),
                    bio=f"Dr. {last} is a {spec['spec']} specialist with {exp} years of experience, "
                        f"dedicated to patient-centered care at {hinfo['name']}.",
                    languages=language, known_for=spec["known_for"],
                )
                doctors.append((staff, spec))

            nurses = []
            for n_i in range(3):
                first, last, _ = NURSE_NAMES[(h_idx * 3 + n_i) % len(NURSE_NAMES)]
                email = f"{first.lower()}.nurse{n_i + 1}@{hinfo['subdomain']}.demo"
                nurses.append(self._make_staff(db, tenant, "nurse", first, last, email, branch))

            fd_first, fd_last, _ = FRONT_DESK_NAMES[h_idx]
            front_desk = self._make_staff(db, tenant, "front_desk", fd_first, fd_last, f"{fd_first.lower()}.frontdesk@{hinfo['subdomain']}.demo", branch)

            lt_first, lt_last, _ = LAB_TECH_NAMES[h_idx]
            lab_tech = self._make_staff(db, tenant, "lab_tech", lt_first, lt_last, f"{lt_first.lower()}.labtech@{hinfo['subdomain']}.demo", branch)

            ph_first, ph_last, _ = PHARMACIST_NAMES[h_idx]
            pharmacist = self._make_staff(db, tenant, "pharmacist", ph_first, ph_last, f"{ph_first.lower()}.pharmacist@{hinfo['subdomain']}.demo", branch)

            for doc, spec in doctors:
                for state in ("waiting", "vitals_done", "scheduled", "done"):
                    first, last = next(patient_names)
                    dob = _random_dob(rng)
                    gender = rng.choice(["M", "F"])
                    patient = PatientService.register(
                        {
                            "full_name": f"{first} {last}", "mobile": _next_mobile(),
                            "branch_id": branch.id, "gender": gender, "date_of_birth": dob,
                            "dpdp_consent": True, "hie_consent": False, "preferred_language": "en",
                        },
                        tenant_id=tenant.id, db_name=db,
                    )
                    self._build_visit(db, tenant, branch, patient, doc, front_desk, lab_tech, lab_tests, rng, state)

            self.stdout.write(self.style.SUCCESS(f"  Seeded {hinfo['name']}."))
            seeded_tenants.append((hinfo, tenant))

            credentials_lines.append(f"\n## {hinfo['name']} ({hinfo['city']}) — subdomain `{hinfo['subdomain']}`\n")
            credentials_lines.append(f"- Hospital Admin: `{admin_email}`\n")
            for i, (doc, spec) in enumerate(doctors):
                credentials_lines.append(f"- Doctor {i + 1} ({spec['spec']}): `{doc.email}` — Dr. {doc.get_full_name()}\n")
            for i, n in enumerate(nurses):
                credentials_lines.append(f"- Nurse {i + 1}: `{n.email}`\n")
            credentials_lines.append(f"- Front Desk: `{front_desk.email}`\n")
            credentials_lines.append(f"- Lab Technician: `{lab_tech.email}`\n")
            credentials_lines.append(f"- Pharmacist: `{pharmacist.email}`\n")

        # ── Flagship cross-hospital patient ─────────────────────────────────
        flagship_info = self._build_flagship(seeded_tenants, rng)
        if flagship_info:
            credentials_lines.append("\n## Flagship demo patient (switching hospitals + HIE consent)\n")
            credentials_lines.append(f"- Patient portal login: `{flagship_info['email']}` / `{PATIENT_PASSWORD}`\n")
            credentials_lines.append(f"- Full name: {flagship_info['full_name']} (UHID at {flagship_info['home_hospital']}: {flagship_info['uhid']})\n")
            credentials_lines.append(
                f"- Already has a full visit history (vitals, signed consultation, prescription, "
                f"an abnormal HbA1c lab report as a real PDF, and one allergy) at **{flagship_info['home_hospital']}**.\n"
            )
            credentials_lines.append(
                f"- Deliberately has NO record yet at **{flagship_info['target_hospital']}** — log in as her on the "
                f"patient portal, search/browse a doctor at {flagship_info['target_hospital']}, and book. The HIE consent "
                f"modal will fire (new hospital, no consent on file there yet). Agree to it, then log in as a doctor at "
                f"{flagship_info['target_hospital']} and open her encounter — her {flagship_info['home_hospital']} history "
                f"(diagnosis, vitals, allergy, lab result, and an outside document) should now appear in the history sidebar.\n"
            )

        out_path = Path(settings.BASE_DIR) / "DEMO_CREDENTIALS.md"
        out_path.write_text("".join(credentials_lines), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"\nAll done. Full credential list written to: {out_path}"))

    # ── helpers ──────────────────────────────────────────────────────────
    def _make_staff(self, db, tenant, role, first, last, email, branch):
        staff = StaffUser(email=email, first_name=first, last_name=last, role=role, branch=branch)
        staff.set_password(STAFF_PASSWORD)
        staff.save(using=db)
        StaffEmailIndex.objects.using("default").update_or_create(
            email=email, defaults={"tenant_id": tenant.id, "db_name": db},
        )
        return staff

    def _next_token(self, db, doctor_id, appt_date):
        last = Appointment.objects.using(db).filter(
            scheduled_date=appt_date, doctor_user_id=doctor_id,
        ).values_list("token_number", flat=True)
        return (max(last) + 1) if last else 1

    def _build_visit(self, db, tenant, branch, patient, doc, front_desk, lab_tech, lab_tests, rng, state,
                      complaint=None, diagnosis=None, hie_consent_at_home=False):
        """Create an Appointment (plus, for 'done', the full consultation trail) for one patient."""
        complaint = complaint or rng.choice(COMPLAINTS)
        today = date.today()

        if state == "waiting":
            appt_date = today
            appt = Appointment.objects.using(db).create(
                patient_id=patient.uuid, patient_awpid=patient.awpid, doctor_user_id=doc.id,
                doctor_name=doc.get_full_name(), branch_id=branch.id,
                appointment_type="opd", status="waiting", scheduled_date=appt_date,
                scheduled_time=timezone.now().time().replace(microsecond=0),
                token_number=self._next_token(db, doc.id, appt_date),
                chief_complaint=complaint, booked_by_user_id=front_desk.id,
            )
            return appt

        if state == "vitals_done":
            appt_date = today
            appt = Appointment.objects.using(db).create(
                patient_id=patient.uuid, patient_awpid=patient.awpid, doctor_user_id=doc.id,
                doctor_name=doc.get_full_name(), branch_id=branch.id,
                appointment_type="opd", status="vitals_done", scheduled_date=appt_date,
                scheduled_time=timezone.now().time().replace(microsecond=0),
                token_number=self._next_token(db, doc.id, appt_date),
                chief_complaint=complaint, booked_by_user_id=front_desk.id,
            )
            Vitals.objects.using(db).create(
                appointment=appt, recorded_by_user_id=front_desk.id,
                systolic_bp=rng.randint(110, 140), diastolic_bp=rng.randint(70, 90),
                pulse_rate=rng.randint(65, 95), temperature=Decimal(rng.choice(["98.4", "98.6", "99.1", "100.2"])),
                spo2=rng.randint(95, 99), respiratory_rate=rng.randint(14, 20),
                weight_kg=Decimal(str(rng.randint(50, 85))), height_cm=Decimal(str(rng.randint(150, 185))),
                blood_sugar_rbs=rng.randint(90, 160),
            )
            return appt

        if state == "scheduled":
            appt_date = today + timedelta(days=rng.randint(1, 5))
            appt = Appointment.objects.using(db).create(
                patient_id=patient.uuid, patient_awpid=patient.awpid, doctor_user_id=doc.id,
                doctor_name=doc.get_full_name(), branch_id=branch.id,
                appointment_type="opd", status="scheduled", scheduled_date=appt_date,
                scheduled_time=dtime(rng.choice([10, 11, 15, 16]), rng.choice([0, 15, 30, 45])),
                token_number=self._next_token(db, doc.id, appt_date),
                chief_complaint=complaint, booked_by_user_id=front_desk.id,
            )
            return appt

        # state == "done" — full consultation trail with prescription + lab report
        appt_date = today - timedelta(days=rng.randint(3, 20))
        appt = Appointment.objects.using(db).create(
            patient_id=patient.uuid, patient_awpid=patient.awpid, doctor_user_id=doc.id,
            doctor_name=doc.get_full_name(), branch_id=branch.id,
            appointment_type="opd", status="waiting", scheduled_date=appt_date,
            scheduled_time=dtime(11, 0), token_number=self._next_token(db, doc.id, appt_date),
            chief_complaint=complaint, booked_by_user_id=front_desk.id,
        )
        Vitals.objects.using(db).create(
            appointment=appt, recorded_by_user_id=front_desk.id,
            systolic_bp=rng.randint(110, 145), diastolic_bp=rng.randint(70, 92),
            pulse_rate=rng.randint(65, 95), temperature=Decimal(rng.choice(["98.4", "98.6", "99.1"])),
            spo2=rng.randint(95, 99), respiratory_rate=rng.randint(14, 20),
            weight_kg=Decimal(str(rng.randint(50, 85))), height_cm=Decimal(str(rng.randint(150, 185))),
            blood_sugar_rbs=rng.randint(90, 160),
        )

        diag = diagnosis or rng.choice(DIAGNOSES)
        enc = OPDEncounter.objects.using(db).create(
            appointment=appt, patient_id=patient.uuid, doctor_user_id=doc.id, status="draft",
            subjective=complaint, objective="Vitals stable, no acute distress on examination.",
            assessment=diag["description"], plan="Symptomatic treatment; review in 2 weeks if not improved.",
            diagnoses=[diag],
            investigations=(rng.choice(lab_tests).name + " advised") if lab_tests else "",
            advice_to_patient="Adequate rest, hydration, and follow the prescribed medication schedule.",
            follow_up_in_days=14,
        )
        enc.sign(using=db)

        from apps.opd.views import _sync_to_hie, _auto_generate_invoice
        _auto_generate_invoice(enc, db, doc, patient)

        rx = Prescription.objects.using(db).create(encounter=enc, patient_id=patient.uuid, doctor_user_id=doc.id, status="active")
        for drug in rng.sample(DRUGS, k=2):
            PrescriptionItem.objects.using(db).create(prescription=rx, **drug)

        # Re-sync now that the prescription exists — sign() ran before rx was attached.
        _sync_to_hie(enc, db, patient)

        if rng.random() < 0.4:
            Allergy.objects.using(db).create(
                patient=patient, substance=rng.choice(["Penicillin", "Sulfa drugs", "Dust", "Peanuts"]),
                reaction="Rash and itching", severity=rng.choice(["mild", "moderate"]),
                is_active=True, recorded_at=timezone.now(),
            )

        if lab_tests:
            test = rng.choice(lab_tests)
            lr = LabRequest.objects.using(db).create(
                patient=patient, encounter=enc, appointment_id=appt.id, test=test,
                requested_by_id=doc.id, branch_id=branch.id, urgency="routine",
                clinical_notes=f"For {diag['description']}", status="collected", collected_at=timezone.now(),
            )
            report_number, _ = get_next_number(branch_id=branch.id, entity="lab_report", using=db)
            items = _sample_items(test.name, rng)
            pdf_uri = _pdf_lab_report(tenant.name, patient.full_name, patient.uhid, f"Dr. {doc.get_full_name()}", test.name, report_number, items)
            report = LabReport.objects.using(db).create(
                request=lr, patient=patient, report_number=report_number, status="delivered",
                result_summary=f"{test.name} — see attached report.", file_url=pdf_uri,
                file_name=f"{report_number}.pdf", mime_type="application/pdf",
                performed_by=lab_tech, verified_by=doc, delivered_at=timezone.now(),
            )
            for item in items:
                LabReportItem.objects.using(db).create(report=report, **item)
            lr.status = "completed"
            lr.save(using=db, update_fields=["status"])

        fu_date = today + timedelta(days=rng.randint(3, 10))
        Appointment.objects.using(db).create(
            patient_id=patient.uuid, patient_awpid=patient.awpid, doctor_user_id=doc.id,
            doctor_name=doc.get_full_name(), branch_id=branch.id,
            appointment_type="followup", status="scheduled", scheduled_date=fu_date,
            scheduled_time=dtime(11, 30), token_number=self._next_token(db, doc.id, fu_date),
            chief_complaint=f"Follow-up: {diag['description']}", booked_by_user_id=front_desk.id,
        )
        return appt

    def _build_flagship(self, seeded_tenants, rng):
        """
        One patient with a rich history at hospital #1 who has NOT yet visited
        hospital #2 — the live demo patient for the switching-hospitals /
        HIE-consent / shared-history story.
        """
        if len(seeded_tenants) < 2:
            self.stdout.write(self.style.WARNING("Skipping flagship patient — fewer than 2 hospitals seeded."))
            return None

        home_info, home_tenant = seeded_tenants[0]
        target_info, _target_tenant = seeded_tenants[1]
        db = home_tenant.db_name
        _register_db(db)
        _thread_local.tenant_id = home_tenant.id
        _thread_local.db_alias = db

        FLAGSHIP_MOBILE = "9876500001"
        FLAGSHIP_EMAIL = "meera.krishnan@patientdemo.com"

        existing = Patient.objects.using(db).filter(mobile=FLAGSHIP_MOBILE).first()
        if existing:
            self.stdout.write(self.style.WARNING("Flagship patient already exists — skipping re-seed."))
            return {
                "email": FLAGSHIP_EMAIL, "full_name": existing.full_name, "uhid": existing.uhid,
                "home_hospital": home_info["name"], "target_hospital": target_info["name"],
            }

        branch = Branch.objects.using(db).filter(is_active=True).order_by("id").first()
        doctor_staff = StaffUser.objects.using(db).filter(role="doctor", is_active=True).order_by("id").first()
        if not branch or not doctor_staff:
            self.stdout.write(self.style.WARNING("Skipping flagship patient — home hospital has no branch/doctor."))
            return None

        patient = PatientService.register(
            {
                "full_name": "Meera Krishnan", "mobile": FLAGSHIP_MOBILE,
                "branch_id": branch.id, "gender": "F", "date_of_birth": date(1988, 6, 14),
                "dpdp_consent": True, "hie_consent": True, "preferred_language": "en",
            },
            tenant_id=home_tenant.id, db_name=db,
        )

        lab_tests = list(LabTest.objects.using(db).all())
        diag = {"code": "E11.9", "description": "Type 2 diabetes mellitus without complications"}
        self._build_visit(
            db, home_tenant, branch, patient, doctor_staff,
            StaffUser.objects.using(db).filter(role="front_desk").first() or doctor_staff,
            StaffUser.objects.using(db).filter(role="lab_tech").first() or doctor_staff,
            lab_tests, rng, "done",
            complaint="Increased thirst and frequent urination for 2 weeks",
            diagnosis=diag,
        )

        Allergy.objects.using(db).create(
            patient=patient, substance="Sulfa drugs", reaction="Skin rash and swelling",
            severity="moderate", is_active=True, recorded_at=timezone.now(),
        )

        # Outside document she uploaded herself via the portal, pre-dating this hospital.
        doc_uri = _generic_pdf("Discharge Summary — Apollo Chennai (2024)", [
            "Patient: Meera Krishnan", "Diagnosis: Type 2 Diabetes Mellitus, newly diagnosed",
            "Advised: Metformin 500mg BD, dietary modification, HbA1c recheck in 3 months.",
        ])
        SharedDocument.objects.using("default").create(
            awpid=patient.awpid, title="Discharge Summary — Apollo Chennai (2024)",
            doc_type="discharge_summary", file_name="discharge_summary_2024.pdf",
            mime_type="application/pdf", file_data=doc_uri, uploaded_by="patient", source_tenant_id=None,
        )

        account = PatientAccount(
            awpid=patient.awpid, full_name=patient.full_name, email=FLAGSHIP_EMAIL,
            mobile=FLAGSHIP_MOBILE, gender=patient.gender, date_of_birth=patient.date_of_birth, is_active=True,
        )
        account.set_password(PATIENT_PASSWORD)
        account.save(using="default")

        latest_appt = Appointment.objects.using(db).filter(patient_id=patient.uuid, status="done").order_by("-scheduled_date").first()
        if latest_appt:
            PortalBooking.objects.using("default").create(
                account=account, tenant_id=home_tenant.id, db_name=db, hospital_name=home_tenant.name,
                appointment_id=latest_appt.id, doctor_name=latest_appt.doctor_name,
                scheduled_date=latest_appt.scheduled_date, chief_complaint=latest_appt.chief_complaint,
                status="done",
            )

        self.stdout.write(self.style.SUCCESS(
            f"Flagship patient created: {patient.full_name} (UHID {patient.uhid}) at {home_tenant.name}. "
            f"Portal login: {FLAGSHIP_EMAIL} / {PATIENT_PASSWORD}. No record yet at {target_info['name']} — "
            f"that's the live demo."
        ))
        return {
            "email": FLAGSHIP_EMAIL, "full_name": patient.full_name, "uhid": patient.uhid,
            "home_hospital": home_tenant.name, "target_hospital": target_info["name"],
        }
