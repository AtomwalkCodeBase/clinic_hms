"""
Management command: add_cardiologist_cedar

One-off addition: a 4th doctor — a Cardiologist — at Cedar Health Hospital
(the existing seed_full_demo tenant, subdomain cedar-health-demo), end to
end: staff login, DoctorProfile (specialisation/qualification/fee/known_for/
bio/languages), a real gender-matched profile photo, and three patients
spread across the same appointment-lifecycle states seed_full_demo uses
(waiting in queue, vitals recorded, and a fully signed consultation with
prescription) so the new doctor's dashboard isn't empty on first login.

Idempotent: skips doctor creation if the email already exists; skips patient
seeding if that doctor already has patients.

Usage:
  python manage.py add_cardiologist_cedar --settings=atomwalk.settings.development
"""

import base64
import itertools
import urllib.request
from datetime import date, timedelta, time as dtime
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.tenants.models import Tenant
from apps.tenants.utils import _make_db_config
from apps.org.models import Branch, StaffUser, DoctorProfile
from apps.registry.models import StaffEmailIndex
from apps.patients.services import PatientService
from apps.opd.models import Appointment, Vitals, OPDEncounter
from core.utils.nntm import get_next_number
from core.db_router import _thread_local

STAFF_PASSWORD = "hms@1234"  # matches the rest of the seeded demo (reset_demo_passwords)
CEDAR_SUBDOMAIN = "cedar-health-demo"

DOCTOR_EMAIL = "rakesh.doctor4@cedar-health-demo.demo"
DOCTOR_FIRST, DOCTOR_LAST, DOCTOR_GENDER = "Rakesh", "Chowdary", "M"

# New, gender-matched Unsplash portrait (free-to-use, no attribution required)
# — not one of the six already used by seed_full_demo's other 12 doctors.
DOCTOR_PHOTO_URL = "https://images.unsplash.com/photo-1612276529731-4b21494e6d71?crop=faces&fit=crop&w=400&h=400&q=80"

COMPLAINTS = ["Chest pain and breathlessness on exertion", "Palpitations for 2 days", "Routine cardiac checkup"]
PATIENTS = [
    dict(full_name="Manoj Iyengar", dob="1968-04-12", gender="male", mobile="7100900001",
         complaint="Chest pain and breathlessness on exertion", state="waiting"),
    dict(full_name="Sarita Rangan", dob="1975-09-03", gender="female", mobile="7100900002",
         complaint="Palpitations for 2 days", state="vitals_done"),
    dict(full_name="Deepak Bhargava", dob="1960-01-22", gender="male", mobile="7100900003",
         complaint="Routine cardiac checkup", state="done"),
]


class Command(BaseCommand):
    help = "Add a Cardiologist doctor (staff + profile + photo + demo patients) at Cedar Health Hospital."

    def handle(self, *args, **options):
        try:
            tenant = Tenant.objects.using("default").get(db_name__isnull=False, subdomain=CEDAR_SUBDOMAIN)
        except Tenant.DoesNotExist:
            raise CommandError(
                f"No tenant with subdomain={CEDAR_SUBDOMAIN} — run seed_full_demo first."
            )
        db = tenant.db_name
        if db not in settings.DATABASES:
            settings.DATABASES[db] = _make_db_config(db)

        branch = Branch.objects.using(db).filter(is_active=True).first()
        if not branch:
            raise CommandError(f"No active branch found in {db}.")

        # ── Doctor staff account ────────────────────────────────────────────
        staff = StaffUser.objects.using(db).filter(email=DOCTOR_EMAIL).first()
        if staff:
            self.stdout.write(self.style.WARNING(f"  {DOCTOR_EMAIL} already exists — skipping doctor creation."))
        else:
            staff = StaffUser(email=DOCTOR_EMAIL, first_name=DOCTOR_FIRST, last_name=DOCTOR_LAST,
                               role="doctor", branch=branch)
            staff.set_password(STAFF_PASSWORD)
            staff.save(using=db)
            StaffEmailIndex.objects.using("default").update_or_create(
                email=DOCTOR_EMAIL, defaults={"tenant_id": tenant.id, "db_name": db},
            )

            # Profile photo — downloaded here (works when run on a machine with
            # real internet access; this sandbox cannot reach images.unsplash.com,
            # see set_demo_doctor_photos.py for the same constraint).
            try:
                req = urllib.request.Request(DOCTOR_PHOTO_URL, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    raw = resp.read()
                    content_type = resp.headers.get("Content-Type", "image/jpeg")
                staff.photo = f"data:{content_type};base64,{base64.b64encode(raw).decode('ascii')}"
                staff.save(using=db, update_fields=["photo"])
                self.stdout.write(self.style.SUCCESS(f"  Photo set ({len(raw):,} bytes)."))
            except Exception as exc:
                self.stdout.write(self.style.WARNING(
                    f"  Could not download profile photo ({exc}) — run set_staff_photo manually if needed."
                ))

            DoctorProfile.objects.using(db).create(
                staff=staff,
                registration_no=f"TS/CARD/{tenant.id}{staff.id:04d}",
                specialisation="Cardiology",
                qualification="MBBS, MD (Medicine), DM (Cardiology)",
                gender=DOCTOR_GENDER,
                experience_years=14,
                consultation_fee=Decimal("900.00"),
                bio="Interventional cardiologist with a focus on preventive heart care, hypertension "
                    "management, and post-cardiac-event follow-up.",
                languages="English, Hindi, Telugu",
                known_for="Chest pain, Hypertension, Heart checkups",
            )
            self.stdout.write(self.style.SUCCESS(f"  Created Dr. {DOCTOR_FIRST} {DOCTOR_LAST} (Cardiology) — {DOCTOR_EMAIL}"))

        # ── Demo patients across the appointment lifecycle ─────────────────
        already_has_patients = Appointment.objects.using(db).filter(doctor_user_id=staff.id).exists()
        if already_has_patients:
            self.stdout.write(self.style.WARNING("  Doctor already has patients — skipping patient seeding."))
        else:
            _thread_local.tenant_id = tenant.id
            _thread_local.db_alias = db
            front_desk = StaffUser.objects.using(db).filter(role="front_desk").first()
            for p in PATIENTS:
                patient = PatientService.register(
                    data=dict(full_name=p["full_name"], date_of_birth=p["dob"], gender=p["gender"],
                              mobile=p["mobile"], branch_id=branch.id, payer_type="self",
                              dpdp_consent=True, hie_consent=False),
                    tenant_id=tenant.id, db_name=db,
                )
                self._build_visit(db, branch, patient, staff, front_desk, p["state"], p["complaint"])
            self.stdout.write(self.style.SUCCESS(f"  Seeded {len(PATIENTS)} demo patients for Dr. {DOCTOR_FIRST} {DOCTOR_LAST}."))

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. Login: {DOCTOR_EMAIL} / {STAFF_PASSWORD}"
        ))

    # ── helpers (mirrors seed_full_demo._build_visit, trimmed) ─────────────
    def _next_token(self, db, doctor_id, appt_date):
        last = Appointment.objects.using(db).filter(
            scheduled_date=appt_date, doctor_user_id=doctor_id,
        ).values_list("token_number", flat=True)
        return (max(last) + 1) if last else 1

    def _build_visit(self, db, branch, patient, doc, front_desk, state, complaint):
        today = date.today()
        front_desk_id = front_desk.id if front_desk else None

        if state == "waiting":
            appt_date = today
            Appointment.objects.using(db).create(
                patient_id=patient.uuid, patient_awpid=patient.awpid, doctor_user_id=doc.id,
                doctor_name=doc.get_full_name(), branch_id=branch.id,
                appointment_type="opd", status="waiting", scheduled_date=appt_date,
                scheduled_time=timezone.now().time().replace(microsecond=0),
                token_number=self._next_token(db, doc.id, appt_date),
                chief_complaint=complaint, booked_by_user_id=front_desk_id,
            )
            return

        if state == "vitals_done":
            appt_date = today
            appt = Appointment.objects.using(db).create(
                patient_id=patient.uuid, patient_awpid=patient.awpid, doctor_user_id=doc.id,
                doctor_name=doc.get_full_name(), branch_id=branch.id,
                appointment_type="opd", status="vitals_done", scheduled_date=appt_date,
                scheduled_time=timezone.now().time().replace(microsecond=0),
                token_number=self._next_token(db, doc.id, appt_date),
                chief_complaint=complaint, booked_by_user_id=front_desk_id,
            )
            Vitals.objects.using(db).create(
                appointment=appt, recorded_by_user_id=front_desk_id,
                systolic_bp=132, diastolic_bp=86, pulse_rate=88, temperature=Decimal("98.6"),
                spo2=97, respiratory_rate=18, weight_kg=Decimal("72"), height_cm=Decimal("168"),
                blood_sugar_rbs=110,
            )
            return

        # state == "done" — full signed consultation + prescription
        appt_date = today - timedelta(days=6)
        appt = Appointment.objects.using(db).create(
            patient_id=patient.uuid, patient_awpid=patient.awpid, doctor_user_id=doc.id,
            doctor_name=doc.get_full_name(), branch_id=branch.id,
            appointment_type="opd", status="waiting", scheduled_date=appt_date,
            scheduled_time=dtime(11, 0), token_number=self._next_token(db, doc.id, appt_date),
            chief_complaint=complaint, booked_by_user_id=front_desk_id,
        )
        Vitals.objects.using(db).create(
            appointment=appt, recorded_by_user_id=front_desk_id,
            systolic_bp=138, diastolic_bp=88, pulse_rate=82, temperature=Decimal("98.4"),
            spo2=98, respiratory_rate=16, weight_kg=Decimal("80"), height_cm=Decimal("172"),
            blood_sugar_rbs=104,
        )
        diag = {"code": "I25.10", "description": "Atherosclerotic heart disease without angina pectoris"}
        enc = OPDEncounter.objects.using(db).create(
            appointment=appt, patient_id=patient.uuid, doctor_user_id=doc.id, status="draft",
            subjective=complaint, objective="S1 S2 heard, no murmurs. BP mildly elevated. ECG: normal sinus rhythm.",
            assessment=diag["description"], plan="Lifestyle modification, statin therapy, follow-up in 4 weeks.",
            diagnoses=[diag], investigations="Lipid profile, ECG advised",
            advice_to_patient="Low-salt, low-fat diet. Daily 30-minute walk. Avoid smoking/alcohol.",
            follow_up_in_days=28,
        )
        enc.signed_at = timezone.now()
        enc.status = "signed"
        enc.save(using=db, update_fields=["signed_at", "status"])

        from apps.opd.models import Prescription, PrescriptionItem
        rx = Prescription.objects.using(db).create(
            encounter=enc, patient_id=patient.uuid, doctor_user_id=doc.id, status="active",
        )
        PrescriptionItem.objects.using(db).create(
            prescription=rx, drug_name="Atorvastatin", dosage="20mg", frequency="od",
            route="oral", duration_days=30, instructions="At night",
        )
        PrescriptionItem.objects.using(db).create(
            prescription=rx, drug_name="Amlodipine", dosage="5mg", frequency="od",
            route="oral", duration_days=30, instructions="In the morning",
        )

        # Mirror the live consultation flow's HIE write-through so this visit
        # shows up correctly if this patient is ever looked up cross-hospital.
        try:
            from apps.opd.views import _sync_to_hie, _auto_generate_invoice
            _auto_generate_invoice(enc, db, doc, patient)
            _sync_to_hie(enc, db, patient)
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"    (HIE sync / invoice skipped: {exc})"))
