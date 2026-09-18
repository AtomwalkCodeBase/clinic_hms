"""
Management command: seed_mahanandi_demo

Populates Mahanandi Hospitals (db_name="aw_mahanandi_hospitals") with a full
day of realistic, internally-consistent demo data across its 4 existing
doctors (Sowmya Patil — Pediatrics, Manjunath Hiremath — General Physician,
Chaitra Gowda — ENT, Ravikiran Naik — Endocrinology) and its nurse
(Bhavana Rao), so the platform looks like an actively-running hospital
rather than an empty demo shell.

Two workflows:

  1. Adult OPD workflow (GP / ENT / Endocrinology) — today's appointments
     spread across the full status lifecycle (scheduled → waiting →
     vitals_done → in_progress → done), each with vitals and, for "done"
     visits, a fully signed OPDEncounter + Prescription appropriate to the
     complaint and specialty (fever, hypertension, diabetes, sinusitis,
     ear pain, hypothyroidism, PCOS, etc.) — vitals are clinically
     consistent with each condition (e.g. elevated BP for the hypertension
     follow-up, bradycardia + low-normal temp for hypothyroidism).

  2. Pediatric workflow (Sowmya Patil) — 6 guardians (2 with patient-portal
     logins), 7 children spanning newborn → adolescent, each with:
       - A BirthHistory row (newborn/infant).
       - A real growth history: past "done" Appointments + Vitals at
         realistic prior visit ages (so apps.patients.growth_vaccination_views
         .PatientGrowthView draws an actual multi-point line — growth data
         is derived from Vitals on real Appointments, there's no separate
         GrowthMeasurement model), ending at today's actual visit for
         patients seen today.
       - SharedVaccination rows for every dose already due as of their
         current age, using the exact vaccine_name/scheduled_label strings
         Mahanandi's active (or fallback "Default Schedule") vaccination
         schedule uses — doses not yet administered are simply absent (no
         row), which is what a fresh view naturally renders as "due"/
         "unknown"; nothing is fabricated as "overdue" beyond just not
         creating the record for it. One child (Meera, 8y) is genuinely
         overdue on "6 years" Typhoid Booster; one (Karthik, 14y) is fully
         up to date through "10 years" — a deliberate mix per doctor.
       - Today's appointment across the same waiting → vitals → doctor →
         done spectrum as the adult workflow.

Idempotent: every patient/appointment/vaccination row is looked up by its
natural key first and only created if missing, so re-running this (e.g. to
top up "today's" appointments on a later date) does not duplicate history.

Usage:
  python manage.py seed_mahanandi_demo --settings=atomwalk.settings.development
"""

import logging
from datetime import date, datetime, time as dtime, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.tenants.models import Tenant
from apps.tenants.utils import _make_db_config
from core.db_router import set_tenant_db
from apps.org.models import Branch, StaffUser, DoctorProfile, NurseDoctorAssignment
from apps.registry.models import PatientIdentity, PatientAccount, SharedVaccination
from apps.patients.models import Patient, BirthHistory
from apps.patients.services import PatientService
from apps.opd.models import Appointment, Vitals, OPDEncounter, Prescription, PrescriptionItem

logger = logging.getLogger(__name__)

TENANT_DB_NAME = "aw_mahanandi_hospitals"
GUARDIAN_PORTAL_PASSWORD = "Patient@12345"

# Exact vaccine_name/scheduled_label pairs — confirmed to match Mahanandi's
# fallback "Default Schedule" (VaccinationScheduleRule, schedule id=1) at
# the time this was written. build_roadmap() matches on these strings
# exactly, so they must not drift from what the tenant's active schedule
# actually contains.
SCHEDULE_BY_LABEL = [
    ("Birth",        ["BCG", "Hepatitis B - 1", "OPV - 0"]),
    ("6 weeks",      ["DTP - 1", "OPV - 1", "Hepatitis B - 2"]),
    ("10 weeks",     ["DTP - 2", "OPV - 2"]),
    ("14 weeks",     ["DTP - 3", "OPV - 3", "Hepatitis B - 3"]),
    ("9 months",     ["Measles - 1", "MMR - 1"]),
    ("16-18 months", ["MMR - 2 (Booster)", "DTP Booster - 1"]),
    ("5 years",      ["DTP Booster - 2"]),
    ("6 years",      ["Typhoid Booster"]),
    ("10 years",     ["Tdap/Td Booster"]),
]
LABEL_OFFSET_DAYS = {
    "Birth": 0, "6 weeks": 42, "10 weeks": 70, "14 weeks": 98,
    "9 months": 274, "16-18 months": 548, "5 years": 1825,
    "6 years": 2190, "10 years": 3650,
}


class Command(BaseCommand):
    help = "Populate Mahanandi Hospitals with a full day of realistic OPD + pediatric demo data."

    def handle(self, *args, **options):
        try:
            tenant = Tenant.objects.using("default").get(db_name=TENANT_DB_NAME)
        except Tenant.DoesNotExist:
            raise CommandError(f"No tenant with db_name={TENANT_DB_NAME!r}.")

        db = tenant.db_name
        if db not in settings.DATABASES:
            settings.DATABASES[db] = _make_db_config(db)
        set_tenant_db(db)

        self.db = db
        self.tenant = tenant
        self.today = date.today()
        self._credentials = []

        self.branch = Branch.objects.using(db).filter(is_active=True).order_by("id").first()
        if not self.branch:
            raise CommandError("Mahanandi Hospitals has no active branch.")

        profiles = {
            dp.specialisation: dp.staff
            for dp in DoctorProfile.objects.using(db).select_related("staff")
        }
        required = ["Pediatrics", "General Physician", "ENT", "Endocrinology"]
        missing = [s for s in required if s not in profiles]
        if missing:
            raise CommandError(
                f"Mahanandi is missing doctor(s) for: {missing} — run seed_recent_hospitals_staff first."
            )
        self.doctors = profiles

        self.nurse = StaffUser.objects.using(db).filter(role="nurse", is_active=True).first()
        if not self.nurse:
            raise CommandError("No active nurse found at Mahanandi.")

        with transaction.atomic(using=db), transaction.atomic(using="default"):
            self._ensure_nurse_assignments()
            self._seed_adult_workflow(self.doctors["General Physician"], GP_PATIENTS)
            self._seed_adult_workflow(self.doctors["ENT"], ENT_PATIENTS)
            self._seed_adult_workflow(self.doctors["Endocrinology"], ENDO_PATIENTS)
            self._seed_pediatric_workflow()

        self._print_report()

    # ── Setup ────────────────────────────────────────────────────────────

    def _ensure_nurse_assignments(self):
        for doctor in self.doctors.values():
            NurseDoctorAssignment.objects.using(self.db).get_or_create(
                nurse=self.nurse, doctor=doctor,
            )
        self.stdout.write(self.style.SUCCESS(
            f"Nurse {self.nurse.get_full_name()} assigned to all 4 doctors."
        ))

    # ── Shared low-level helpers ─────────────────────────────────────────

    def _next_token(self, doctor_id, appt_date):
        last = list(
            Appointment.objects.using(self.db)
            .filter(scheduled_date=appt_date, doctor_user_id=doctor_id)
            .values_list("token_number", flat=True)
        )
        return (max([t for t in last if t is not None], default=0)) + 1

    def _status_timestamps(self, appt_date, appt_time, status):
        """Chronologically sane checked_in_at/started_at/completed_at for
        TODAY's appointments, based on status — scheduled patients haven't
        checked in yet, waiting have, in_progress additionally has a
        started_at, done has all three in order before "now"."""
        base = timezone.make_aware(datetime.combine(appt_date, appt_time))
        out = {"checked_in_at": None, "started_at": None, "completed_at": None}
        if status == Appointment.STATUS_SCHEDULED:
            return out
        out["checked_in_at"] = base - timedelta(minutes=10)
        if status in (Appointment.STATUS_WAITING, Appointment.STATUS_VITALS_DONE):
            return out
        out["started_at"] = base
        if status == Appointment.STATUS_IN_PROGRESS:
            return out
        out["completed_at"] = base + timedelta(minutes=15)
        return out

    def _ensure_appointment(self, patient, doctor, appt_date, appt_time, token,
                             chief_complaint, status, branch=None):
        existing = Appointment.objects.using(self.db).filter(
            patient_id=patient.uuid, doctor_user_id=doctor.id, scheduled_date=appt_date,
        ).first()
        if existing:
            return existing
        ts = self._status_timestamps(appt_date, appt_time, status)
        return Appointment.objects.using(self.db).create(
            patient_id=patient.uuid, patient_awpid=patient.awpid,
            doctor_user_id=doctor.id, doctor_name=doctor.get_full_name(),
            branch_id=(branch or self.branch).id, appointment_type=Appointment.TYPE_OPD,
            status=status, scheduled_date=appt_date, scheduled_time=appt_time,
            token_number=token, chief_complaint=chief_complaint,
            payment_preference=Appointment.PAYMENT_PAY_AT_DESK,
            **ts,
        )

    def _ensure_vitals(self, appt, **fields):
        if Vitals.objects.using(self.db).filter(appointment=appt).exists():
            return
        Vitals.objects.using(self.db).create(
            appointment=appt, recorded_by_user_id=self.nurse.id, **fields,
        )

    def _ensure_encounter(self, appt, doctor, subjective, objective, assessment,
                           diagnoses, plan, advice_to_patient, follow_up_in_days,
                           investigations="", medicines=None):
        if OPDEncounter.objects.using(self.db).filter(appointment=appt).exists():
            return
        enc = OPDEncounter.objects.using(self.db).create(
            appointment=appt, patient_id=appt.patient_id, doctor_user_id=doctor.id,
            status=OPDEncounter.STATUS_DRAFT,
            subjective=subjective, objective=objective, assessment=assessment,
            plan=plan, diagnoses=diagnoses, investigations=investigations,
            advice_to_patient=advice_to_patient, follow_up_in_days=follow_up_in_days,
        )
        enc.sign(using=self.db)

        rx = Prescription.objects.using(self.db).create(
            encounter=enc, patient_id=appt.patient_id, doctor_user_id=doctor.id,
            status=Prescription.STATUS_ACTIVE,
        )
        for m in (medicines or []):
            PrescriptionItem.objects.using(self.db).create(
                prescription=rx, drug_name=m["name"], dosage=m["dosage"],
                frequency=m["frequency"], route=m.get("route", "oral"),
                duration_days=m.get("duration_days"), instructions=m.get("instructions", ""),
            )

    def _ensure_adult_patient(self, mobile, full_name, dob, gender):
        existing = Patient.objects.using(self.db).filter(mobile=mobile).first()
        if existing:
            return existing
        return PatientService.register(
            data=dict(full_name=full_name, mobile=mobile, branch_id=self.branch.id,
                      dpdp_consent=True, hie_consent=True, date_of_birth=dob, gender=gender),
            tenant_id=self.tenant.id, db_name=self.db,
        )

    def _ensure_guardian(self, mobile, full_name, dob, gender, with_portal_login):
        patient = Patient.objects.using(self.db).filter(mobile=mobile).first()
        if not patient:
            patient = PatientService.register(
                data=dict(full_name=full_name, mobile=mobile, branch_id=self.branch.id,
                          dpdp_consent=True, hie_consent=True, date_of_birth=dob, gender=gender),
                tenant_id=self.tenant.id, db_name=self.db,
            )
        identity = PatientIdentity.objects.using("default").get(awpid=patient.awpid)
        if with_portal_login:
            account = PatientAccount.objects.using("default").filter(mobile=mobile).first()
            if not account:
                account = PatientAccount(
                    awpid=identity.awpid, full_name=full_name, mobile=mobile,
                    gender="F" if gender == "female" else "M", date_of_birth=dob,
                )
                account.set_password(GUARDIAN_PORTAL_PASSWORD)
                account.save(using="default")
            self._credentials.append({
                "role": "patient (guardian)", "name": full_name,
                "mobile": mobile, "password": GUARDIAN_PORTAL_PASSWORD,
            })
        return identity, patient

    def _ensure_child_patient(self, guardian_identity, guardian_mobile, full_name, dob, gender):
        patient = Patient.objects.using(self.db).filter(
            is_dependent=True, guardian_awpid=guardian_identity.awpid,
            full_name=full_name, date_of_birth=dob,
        ).first()
        if not patient:
            patient = PatientService.register(
                data=dict(
                    full_name=full_name, is_dependent=True, guardian_awpid=guardian_identity.awpid,
                    guardian_name=guardian_identity.full_name, guardian_mobile=guardian_mobile,
                    relationship="child", date_of_birth=dob, gender=gender,
                    branch_id=self.branch.id, dpdp_consent=True, hie_consent=True,
                ),
                tenant_id=self.tenant.id, db_name=self.db,
            )
        identity = PatientIdentity.objects.using("default").get(awpid=patient.awpid)
        return identity, patient

    def _ensure_birth_history(self, patient, **fields):
        if BirthHistory.objects.using(self.db).filter(patient=patient).exists():
            return
        BirthHistory.objects.using(self.db).create(
            patient=patient, recorded_by=self.nurse.id, **fields,
        )

    def _ensure_growth_visit(self, patient, doctor, dob, age_days, height_cm, weight_kg,
                              head_circumference_cm=None, complaint="Routine growth check-up"):
        """A past, already-`done` well-child visit — exists purely to give
        the growth chart a real historical Vitals-on-Appointment point (see
        module docstring: there's no separate GrowthMeasurement model)."""
        visit_date = dob + timedelta(days=age_days)
        appt = Appointment.objects.using(self.db).filter(
            patient_id=patient.uuid, doctor_user_id=doctor.id, scheduled_date=visit_date,
        ).first()
        if not appt:
            visit_dt = timezone.make_aware(datetime.combine(visit_date, dtime(10, 30)))
            appt = Appointment.objects.using(self.db).create(
                patient_id=patient.uuid, patient_awpid=patient.awpid,
                doctor_user_id=doctor.id, doctor_name=doctor.get_full_name(),
                branch_id=self.branch.id, appointment_type=Appointment.TYPE_OPD,
                status=Appointment.STATUS_DONE, scheduled_date=visit_date,
                scheduled_time=dtime(10, 30), token_number=1, chief_complaint=complaint,
                checked_in_at=visit_dt - timedelta(minutes=10),
                started_at=visit_dt, completed_at=visit_dt + timedelta(minutes=15),
            )
        self._ensure_vitals(
            appt, height_cm=Decimal(str(height_cm)), weight_kg=Decimal(str(weight_kg)),
            head_circumference_cm=Decimal(str(head_circumference_cm)) if head_circumference_cm else None,
        )
        return appt

    def _ensure_vaccinations(self, awpid, dob, doctor, labels_done):
        label_to_names = dict(SCHEDULE_BY_LABEL)
        for label in labels_done:
            administered = dob + timedelta(days=LABEL_OFFSET_DAYS[label])
            for vname in label_to_names[label]:
                if SharedVaccination.objects.using("default").filter(
                    awpid=awpid, vaccine_name=vname, scheduled_label=label,
                ).exists():
                    continue
                SharedVaccination.objects.using("default").create(
                    awpid=awpid, vaccine_name=vname, scheduled_label=label,
                    administered_date=administered, source=SharedVaccination.SOURCE_CLINIC,
                    verification_status=SharedVaccination.STATUS_VERIFIED,
                    verified_by_name=doctor.get_full_name(), verified_at=timezone.now(),
                    source_tenant_id=self.tenant.id, recorded_by="staff",
                )

    # ── Adult OPD workflow ───────────────────────────────────────────────

    def _seed_adult_workflow(self, doctor, patients):
        for p in patients:
            patient = self._ensure_adult_patient(p["mobile"], p["name"], p["dob"], p["gender"])
            token = self._next_token(doctor.id, self.today)
            appt = self._ensure_appointment(
                patient, doctor, self.today, p["time"], token,
                chief_complaint=p["complaint"], status=p["status"],
            )
            if p["status"] in (Appointment.STATUS_VITALS_DONE, Appointment.STATUS_IN_PROGRESS, Appointment.STATUS_DONE):
                self._ensure_vitals(appt, **p["vitals"])
            if p["status"] == Appointment.STATUS_DONE:
                self._ensure_encounter(
                    appt, doctor, subjective=p["subjective"], objective=p["objective"],
                    assessment=p["assessment"], diagnoses=p["diagnoses"], plan=p["plan"],
                    advice_to_patient=p["advice"], follow_up_in_days=p["follow_up_days"],
                    medicines=p["medicines"],
                )

    # ── Pediatric workflow ───────────────────────────────────────────────

    def _seed_pediatric_workflow(self):
        ped = self.doctors["Pediatrics"]
        today = self.today

        # ── Family 1: Kavya Reddy — two siblings, portal login ──────────
        g1, _ = self._ensure_guardian("9870050001", "Kavya Reddy", date(1993, 2, 14), "female", True)

        # Vihaan Reddy — 10-day-old newborn — done
        vihaan_dob = today - timedelta(days=10)
        _, vihaan = self._ensure_child_patient(g1, "9870050001", "Vihaan Reddy", vihaan_dob, "male")
        self._ensure_birth_history(
            vihaan, gestational_age_weeks=39, birth_weight_kg=Decimal("3.10"),
            delivery_mode="normal", apgar_score_1min=8, apgar_score_5min=9,
            notes="Uneventful vaginal delivery, cried immediately at birth.",
        )
        self._ensure_vaccinations(vihaan.awpid, vihaan_dob, ped, ["Birth"])
        token = self._next_token(ped.id, today)
        appt = self._ensure_appointment(
            vihaan, ped, today, dtime(8, 0), token,
            chief_complaint="10-day newborn well-baby check-up", status=Appointment.STATUS_DONE,
        )
        self._ensure_vitals(
            appt, weight_kg=Decimal("3.35"), height_cm=Decimal("51.0"),
            head_circumference_cm=Decimal("35.0"), temperature=Decimal("98.4"),
            pulse_rate=130, spo2=99, respiratory_rate=42,
            nurse_notes="Feeding well per mother, active and pink.",
        )
        self._ensure_encounter(
            appt, ped,
            subjective="Baby feeding well on breast milk, passing urine/stools normally, no fever noted by mother.",
            objective="Alert, active, pink, no jaundice. Umbilical stump healing well, no discharge. "
                      "Anterior fontanelle soft and flat. Heart sounds normal, chest clear on auscultation, abdomen soft, non-tender.",
            assessment="Healthy term newborn with appropriate weight gain since birth.",
            diagnoses=[{"code": "Z00.129", "description": "Well child newborn examination"}],
            plan="Continue exclusive breastfeeding on demand. Routine newborn care advice reinforced.",
            advice_to_patient="Exclusive breastfeeding, keep umbilical cord dry, return if fever, poor feeding, or jaundice. "
                               "Next visit at 6 weeks for first set of vaccinations.",
            follow_up_in_days=32,
            medicines=[dict(name="Vitamin D3 drops", dosage="400 IU", frequency="od", duration_days=180,
                             instructions="Once daily, continue through infancy")],
        )

        # Ananya Reddy — 4-year-old, Vihaan's sister — done, full growth history
        ananya_dob = today - timedelta(days=1460)
        _, ananya = self._ensure_child_patient(g1, "9870050001", "Ananya Reddy", ananya_dob, "female")
        self._ensure_growth_visit(ananya, ped, ananya_dob, 0, 50.0, 3.3, head_circumference_cm=34.5, complaint="Birth")
        self._ensure_growth_visit(ananya, ped, ananya_dob, 365, 75.0, 9.6, head_circumference_cm=46.0, complaint="1-year check-up")
        self._ensure_growth_visit(ananya, ped, ananya_dob, 730, 86.0, 12.5, complaint="2-year check-up")
        self._ensure_growth_visit(ananya, ped, ananya_dob, 1095, 95.0, 14.2, complaint="3-year check-up")
        self._ensure_vaccinations(ananya.awpid, ananya_dob, ped,
                                   ["Birth", "6 weeks", "10 weeks", "14 weeks", "9 months", "16-18 months"])
        token = self._next_token(ped.id, today)
        appt = self._ensure_appointment(
            ananya, ped, today, dtime(8, 20), token,
            chief_complaint="4-year well-child check-up and growth assessment", status=Appointment.STATUS_DONE,
        )
        self._ensure_vitals(
            appt, weight_kg=Decimal("16.0"), height_cm=Decimal("102.0"),
            temperature=Decimal("98.2"), pulse_rate=98, spo2=99, respiratory_rate=22,
            nurse_notes="Active and cooperative, no distress.",
        )
        self._ensure_encounter(
            appt, ped,
            subjective="Mother reports child is eating well, active, no complaints today — here for routine growth check.",
            objective="Alert, playful, well-nourished. No pallor or icterus. Chest clear, abdomen soft, no organomegaly.",
            assessment="Normal growth and development for age; growth parameters tracking well.",
            diagnoses=[{"code": "Z00.129", "description": "Routine child health examination, growth within normal limits"}],
            plan="Continue balanced diet and outdoor activity. Due for DTP Booster-2 at 5 years.",
            advice_to_patient="Continue balanced diet, regular outdoor play, return at 5 years for the next vaccination dose.",
            follow_up_in_days=365,
            medicines=[dict(name="Multivitamin syrup", dosage="5ml", frequency="od", duration_days=30,
                             instructions="Once daily after breakfast")],
        )

        # ── Family 2: Sunita Iyer — one child, portal login ─────────────
        g2, _ = self._ensure_guardian("9870050002", "Sunita Iyer", date(1991, 6, 10), "female", True)
        aryan_dob = today - timedelta(days=63)
        _, aryan = self._ensure_child_patient(g2, "9870050002", "Aryan Iyer", aryan_dob, "male")
        self._ensure_birth_history(
            aryan, gestational_age_weeks=38, birth_weight_kg=Decimal("3.30"),
            delivery_mode="normal", apgar_score_1min=9, apgar_score_5min=9,
        )
        self._ensure_growth_visit(aryan, ped, aryan_dob, 0, 50.0, 3.3, head_circumference_cm=34.0, complaint="Birth")
        self._ensure_vaccinations(aryan.awpid, aryan_dob, ped, ["Birth"])
        token = self._next_token(ped.id, today)
        appt = self._ensure_appointment(
            aryan, ped, today, dtime(9, 0), token,
            chief_complaint="6-week immunization visit (slightly delayed), mild cold symptoms",
            status=Appointment.STATUS_IN_PROGRESS,
        )
        self._ensure_vitals(
            appt, weight_kg=Decimal("5.4"), height_cm=Decimal("57.0"),
            head_circumference_cm=Decimal("38.5"), temperature=Decimal("99.0"),
            pulse_rate=128, spo2=98, respiratory_rate=36,
            nurse_notes="Mild nasal congestion, otherwise active and feeding well.",
        )

        # ── Family 3: Manjula Devi — one child, no portal login ─────────
        g3, _ = self._ensure_guardian("9870050003", "Manjula Devi", date(1989, 9, 5), "female", False)
        sanvi_dob = today - timedelta(days=274)
        _, sanvi = self._ensure_child_patient(g3, "9870050003", "Sanvi Naik", sanvi_dob, "female")
        self._ensure_birth_history(
            sanvi, gestational_age_weeks=39, birth_weight_kg=Decimal("3.20"),
            delivery_mode="c_section", apgar_score_1min=8, apgar_score_5min=9,
        )
        self._ensure_growth_visit(sanvi, ped, sanvi_dob, 0, 50.0, 3.2, head_circumference_cm=34.2, complaint="Birth")
        self._ensure_vaccinations(sanvi.awpid, sanvi_dob, ped, ["Birth", "6 weeks", "10 weeks", "14 weeks"])
        token = self._next_token(ped.id, today)
        appt = self._ensure_appointment(
            sanvi, ped, today, dtime(9, 30), token,
            chief_complaint="9-month vaccination and growth check, mild diaper rash",
            status=Appointment.STATUS_VITALS_DONE,
        )
        self._ensure_vitals(
            appt, weight_kg=Decimal("8.2"), height_cm=Decimal("68.0"),
            head_circumference_cm=Decimal("44.0"), temperature=Decimal("98.6"),
            pulse_rate=120, spo2=99, respiratory_rate=30,
            nurse_notes="Mild erythema in diaper area, otherwise well. Ready for doctor.",
        )

        # ── Family 4: Ramesh Kulkarni — one child, no portal login ──────
        g4, _ = self._ensure_guardian("9870050004", "Ramesh Kulkarni", date(1984, 1, 20), "male", False)
        aditya_dob = today - timedelta(days=548)
        _, aditya = self._ensure_child_patient(g4, "9870050004", "Aditya Kulkarni", aditya_dob, "male")
        self._ensure_growth_visit(aditya, ped, aditya_dob, 0, 50.0, 3.4, head_circumference_cm=34.8, complaint="Birth")
        self._ensure_growth_visit(aditya, ped, aditya_dob, 274, 71.0, 9.5, head_circumference_cm=45.0, complaint="9-month check-up")
        self._ensure_vaccinations(aditya.awpid, aditya_dob, ped, ["Birth", "6 weeks", "10 weeks", "14 weeks", "9 months"])
        token = self._next_token(ped.id, today)
        self._ensure_appointment(
            aditya, ped, today, dtime(10, 0), token,
            chief_complaint="18-month booster vaccination due, mild fussiness and low appetite for 2 days",
            status=Appointment.STATUS_WAITING,
        )

        # ── Family 5: Geeta Shetty — one child, no portal login ─────────
        g5, _ = self._ensure_guardian("9870050005", "Geeta Shetty", date(1980, 11, 11), "female", False)
        meera_dob = today - timedelta(days=2920)
        _, meera = self._ensure_child_patient(g5, "9870050005", "Meera Shetty", meera_dob, "female")
        self._ensure_growth_visit(meera, ped, meera_dob, 0, 50.0, 3.2, head_circumference_cm=34.5, complaint="Birth")
        self._ensure_growth_visit(meera, ped, meera_dob, 365, 75.0, 9.4, head_circumference_cm=46.0, complaint="1-year check-up")
        self._ensure_growth_visit(meera, ped, meera_dob, 1095, 94.0, 14.0, complaint="3-year check-up")
        self._ensure_growth_visit(meera, ped, meera_dob, 1825, 109.0, 18.0, complaint="5-year check-up")
        self._ensure_growth_visit(meera, ped, meera_dob, 2555, 122.0, 22.0, complaint="7-year check-up")
        self._ensure_vaccinations(meera.awpid, meera_dob, ped,
                                   ["Birth", "6 weeks", "10 weeks", "14 weeks", "9 months", "16-18 months", "5 years"])
        # "6 years" (Typhoid Booster, due at 2190 days) deliberately left
        # unrecorded — she's 2920 days old today, so it's genuinely overdue,
        # a realistic "pending vaccination" demo state rather than everyone
        # being perfectly up to date.
        token = self._next_token(ped.id, today)
        self._ensure_appointment(
            meera, ped, today, dtime(10, 30), token,
            chief_complaint="Fever and cough since 3 days", status=Appointment.STATUS_WAITING,
        )

        # ── Family 6: Vijaya Rao — one child, no portal login ───────────
        g6, _ = self._ensure_guardian("9870050006", "Vijaya Rao", date(1978, 8, 8), "female", False)
        karthik_dob = today - timedelta(days=5110)
        _, karthik = self._ensure_child_patient(g6, "9870050006", "Karthik Rao", karthik_dob, "male")
        self._ensure_growth_visit(karthik, ped, karthik_dob, 0, 50.0, 3.3, head_circumference_cm=35.0, complaint="Birth")
        self._ensure_growth_visit(karthik, ped, karthik_dob, 730, 87.0, 13.0, complaint="2-year check-up")
        self._ensure_growth_visit(karthik, ped, karthik_dob, 1825, 110.0, 19.0, complaint="5-year check-up")
        self._ensure_growth_visit(karthik, ped, karthik_dob, 2920, 128.0, 26.0, complaint="8-year check-up")
        self._ensure_growth_visit(karthik, ped, karthik_dob, 4015, 143.0, 35.0, complaint="11-year check-up")
        self._ensure_growth_visit(karthik, ped, karthik_dob, 4745, 158.0, 45.0, complaint="13-year check-up")
        self._ensure_vaccinations(karthik.awpid, karthik_dob, ped,
                                   [label for label, _ in SCHEDULE_BY_LABEL])  # fully up to date, all 9 slots
        token = self._next_token(ped.id, today)
        self._ensure_appointment(
            karthik, ped, today, dtime(14, 0), token,
            chief_complaint="Annual adolescent growth and development follow-up",
            status=Appointment.STATUS_SCHEDULED,
        )

        self._credentials.append({"role": "info", "name": "Pediatric guardians without portal login",
                                   "mobile": "Manjula Devi / Ramesh Kulkarni / Geeta Shetty / Vijaya Rao",
                                   "password": "(no portal account — front-desk/registry identity only)"})

    def _print_report(self):
        self.stdout.write(self.style.SUCCESS(
            f"\nMahanandi Hospitals ({self.tenant.subdomain}) demo data seeded for {self.today}.\n"
        ))
        self.stdout.write("Doctor logins: use the credentials from seed_recent_hospitals_staff (password Hms@1234).\n")
        self.stdout.write("Nurse login: Bhavana Rao, same password.\n\n")
        self.stdout.write("Guardian patient-portal logins:\n")
        for c in self._credentials:
            self.stdout.write(f"  {c['name']:<35} {c['mobile']:<15} {c['password']}\n")


# ── Adult patient rosters ────────────────────────────────────────────────
# Vitals are hand-picked to be clinically consistent with each complaint
# (e.g. elevated BP for the hypertension follow-up, low pulse/temperature
# for the hypothyroid follow-up, elevated RBS for the diabetic patients).

GP_PATIENTS = [
    dict(mobile="9870020001", name="Ramesh Kumar", dob=date(1979, 3, 14), gender="male",
         time=dtime(8, 0), complaint="Fever and body ache since 2 days", status=Appointment.STATUS_DONE,
         vitals=dict(systolic_bp=122, diastolic_bp=78, pulse_rate=96, temperature=Decimal("101.2"),
                     spo2=98, respiratory_rate=18, weight_kg=Decimal("74.0"), height_cm=Decimal("172.0"),
                     nurse_notes="Feels feverish, no rash, no breathing difficulty."),
         subjective="Fever and generalized body ache for 2 days, no cough or cold. No history of travel.",
         objective="Alert, oriented, mild pallor absent. Throat mildly congested, no tonsillar exudate. Chest clear, abdomen soft.",
         assessment="Acute viral febrile illness, no localizing signs of bacterial infection.",
         diagnoses=[{"code": "R50.9", "description": "Fever, unspecified — likely viral"}],
         plan="Symptomatic management, adequate hydration and rest. Review if fever persists beyond 3 more days.",
         advice="Plenty of fluids, rest, paracetamol for fever above 100°F, return if breathlessness or persistent high fever.",
         follow_up_days=5,
         medicines=[dict(name="Paracetamol", dosage="650mg", frequency="td", duration_days=5, instructions="After food, for fever"),
                    dict(name="ORS sachets", dosage="1 sachet in 1L water", frequency="sos", duration_days=5, instructions="As needed for hydration")]),
    dict(mobile="9870020002", name="Sunanda Bhat", dob=date(1972, 7, 22), gender="female",
         time=dtime(8, 20), complaint="Hypertension follow-up", status=Appointment.STATUS_DONE,
         vitals=dict(systolic_bp=148, diastolic_bp=94, pulse_rate=82, temperature=Decimal("98.2"),
                     spo2=97, respiratory_rate=16, weight_kg=Decimal("71.0"), height_cm=Decimal("160.0"),
                     nurse_notes="No chest pain or headache today."),
         subjective="On regular antihypertensives, occasional mild headaches, no chest pain or palpitations.",
         objective="BP mildly elevated today at 148/94. Heart sounds normal, no pedal edema, chest clear.",
         assessment="Essential hypertension, sub-optimally controlled — dose adjustment needed.",
         diagnoses=[{"code": "I10", "description": "Essential (primary) hypertension"}],
         plan="Step up antihypertensive dose, reinforce low-salt diet, recheck BP in 4 weeks.",
         advice="Reduce salt intake, daily 30-minute walk, take medication same time every morning, monitor home BP.",
         follow_up_days=28,
         medicines=[dict(name="Amlodipine", dosage="5mg", frequency="od", duration_days=30, instructions="Morning, continue"),
                    dict(name="Telmisartan", dosage="40mg", frequency="od", duration_days=30, instructions="Morning, new addition")]),
    dict(mobile="9870020003", name="Vikram Singh", dob=date(1986, 11, 5), gender="male",
         time=dtime(9, 0), complaint="Routine annual health checkup", status=Appointment.STATUS_IN_PROGRESS,
         vitals=dict(systolic_bp=118, diastolic_bp=76, pulse_rate=72, temperature=Decimal("98.4"),
                     spo2=99, respiratory_rate=16, weight_kg=Decimal("78.0"), height_cm=Decimal("175.0"),
                     blood_sugar_rbs=98, nurse_notes="No complaints, here for yearly checkup.")),
    dict(mobile="9870020004", name="Lata Iyer", dob=date(1964, 2, 18), gender="female",
         time=dtime(9, 20), complaint="Diabetes follow-up — sugar levels review", status=Appointment.STATUS_VITALS_DONE,
         vitals=dict(systolic_bp=130, diastolic_bp=84, pulse_rate=80, temperature=Decimal("98.0"),
                     spo2=97, respiratory_rate=16, weight_kg=Decimal("70.0"), height_cm=Decimal("158.0"),
                     blood_sugar_rbs=210, nurse_notes="Reports occasional fatigue, ready for doctor.")),
    dict(mobile="9870020005", name="Arjun Nair", dob=date(1995, 9, 30), gender="male",
         time=dtime(9, 40), complaint="Viral fever, sore throat", status=Appointment.STATUS_WAITING, vitals={}),
    dict(mobile="9870020006", name="Priyanka Das", dob=date(1990, 12, 1), gender="female",
         time=dtime(11, 30), complaint="General weakness and fatigue", status=Appointment.STATUS_SCHEDULED, vitals={}),
]

ENT_PATIENTS = [
    dict(mobile="9870030001", name="Mohan Das", dob=date(1983, 5, 10), gender="male",
         time=dtime(8, 15), complaint="Chronic sinusitis follow-up", status=Appointment.STATUS_DONE,
         vitals=dict(systolic_bp=120, diastolic_bp=80, pulse_rate=76, temperature=Decimal("98.6"),
                     spo2=98, respiratory_rate=16, nurse_notes="Reports improved nasal breathing."),
         subjective="Nasal congestion and facial heaviness improving since last visit, no fever.",
         objective="Nasal mucosa mildly congested, no purulent discharge. No sinus tenderness on palpation.",
         assessment="Chronic rhinosinusitis, improving on current treatment.",
         diagnoses=[{"code": "J32.9", "description": "Chronic sinusitis, unspecified"}],
         plan="Continue nasal steroid spray and saline rinses, review in 2 weeks.",
         advice="Steam inhalation twice daily, avoid dust/allergen exposure, complete the nasal spray course.",
         follow_up_days=14,
         medicines=[dict(name="Fluticasone nasal spray", dosage="1 spray each nostril", frequency="od", duration_days=14, instructions="Morning, after nasal rinse"),
                    dict(name="Cetirizine", dosage="10mg", frequency="od", duration_days=14, instructions="Night")]),
    dict(mobile="9870030002", name="Kavitha Menon", dob=date(1990, 8, 25), gender="female",
         time=dtime(9, 10), complaint="Ear pain and discharge, left ear", status=Appointment.STATUS_VITALS_DONE,
         vitals=dict(systolic_bp=116, diastolic_bp=74, pulse_rate=84, temperature=Decimal("99.1"),
                     spo2=98, respiratory_rate=17, nurse_notes="Mild low-grade fever, ready for doctor.")),
    dict(mobile="9870030003", name="Rajesh Pillai", dob=date(1998, 1, 14), gender="male",
         time=dtime(9, 45), complaint="Sore throat and difficulty swallowing", status=Appointment.STATUS_WAITING, vitals={}),
    dict(mobile="9870030004", name="Shalini Kumari", dob=date(1975, 6, 20), gender="female",
         time=dtime(12, 0), complaint="Hearing loss evaluation, right ear", status=Appointment.STATUS_SCHEDULED, vitals={}),
]

ENDO_PATIENTS = [
    dict(mobile="9870040001", name="Suresh Babu", dob=date(1968, 4, 2), gender="male",
         time=dtime(8, 30), complaint="Diabetes follow-up — HbA1c review", status=Appointment.STATUS_DONE,
         vitals=dict(systolic_bp=128, diastolic_bp=82, pulse_rate=78, temperature=Decimal("98.2"),
                     spo2=97, respiratory_rate=16, weight_kg=Decimal("82.0"), height_cm=Decimal("170.0"),
                     blood_sugar_rbs=165, nurse_notes="No hypoglycemic episodes reported."),
         subjective="On Metformin for type 2 diabetes, generally compliant with diet, no hypoglycemic episodes.",
         objective="No pallor, no diabetic foot lesions on inspection. Random blood sugar 165 mg/dL today.",
         assessment="Type 2 Diabetes Mellitus, fairly well controlled on current regimen.",
         diagnoses=[{"code": "E11.9", "description": "Type 2 diabetes mellitus without complications"}],
         plan="Continue Metformin, add low-dose Glimepiride, HbA1c recheck in 3 months.",
         advice="Continue diabetic diet, regular walking, foot self-examination daily, home glucose monitoring.",
         follow_up_days=90,
         medicines=[dict(name="Metformin", dosage="500mg", frequency="bd", duration_days=90, instructions="After breakfast and dinner"),
                    dict(name="Glimepiride", dosage="1mg", frequency="od", duration_days=90, instructions="Before breakfast")]),
    dict(mobile="9870040002", name="Nirmala Devi", dob=date(1973, 10, 11), gender="female",
         time=dtime(9, 15), complaint="Hypothyroidism follow-up", status=Appointment.STATUS_IN_PROGRESS,
         vitals=dict(systolic_bp=118, diastolic_bp=76, pulse_rate=62, temperature=Decimal("97.6"),
                     spo2=98, respiratory_rate=15, weight_kg=Decimal("68.0"), height_cm=Decimal("155.0"),
                     nurse_notes="Reports mild fatigue and cold intolerance, consistent with prior visits.")),
    dict(mobile="9870040003", name="Ashok Reddy", dob=date(1962, 2, 28), gender="male",
         time=dtime(9, 50), complaint="Newly diagnosed diabetes — first consultation", status=Appointment.STATUS_VITALS_DONE,
         vitals=dict(systolic_bp=136, diastolic_bp=88, pulse_rate=80, temperature=Decimal("98.4"),
                     spo2=97, respiratory_rate=16, weight_kg=Decimal("88.0"), height_cm=Decimal("168.0"),
                     blood_sugar_rbs=245, nurse_notes="Referred from GP with high random blood sugar, ready for doctor.")),
    dict(mobile="9870040004", name="Deepa Rao", dob=date(1988, 3, 17), gender="female",
         time=dtime(10, 15), complaint="PCOS and irregular periods", status=Appointment.STATUS_WAITING, vitals={}),
]
