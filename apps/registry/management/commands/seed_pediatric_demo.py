"""
Management command: seed_pediatric_demo

Seeds two demo workflows inside ONE already-existing, already-provisioned
hospital tenant:

  1. Normal OPD workflow, on the hospital's existing general doctor (found
     by role, not hardcoded to a name) — a spread of today's appointments:
     some just booked (no vitals yet) and some with vitals already recorded
     (ready to consult).

  2. Pediatric workflow, on a newly created Pediatrician — one parent with
     two children (a newborn, 2 days old, and a 6-year-old with a full
     multi-point growth + vaccination history so the patient portal's
     Growth & Vaccination chart has real data to draw), plus two more
     independent pediatric patients with appointments booked for their next
     due vaccination, so the pediatrician's queue isn't just the one family.

Deliberately does NOT invent a growth-percentile curve or any number that
isn't the kind of thing a real clinic visit would have recorded — every
height/weight/vaccination row here is the same shape as real data (see
PortalGrowthView / build_roadmap()), just backfilled directly into the
registry tables instead of simulated through 20 live encounters.

Idempotent: every patient/staff row is looked up by mobile/phone first and
reused if it already exists, so re-running this after a partial failure (or
just to top up appointments for "today" again) does not create duplicates.

Usage:
  python manage.py seed_pediatric_demo --tenant lakeview-clinic
  python manage.py seed_pediatric_demo --tenant lakeview-clinic --password "hms@1234"
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
from core.utils.nntm import get_next_number
from apps.org.models import Branch, StaffUser, DoctorProfile, DoctorSchedule, DoctorAvailabilitySlot, NextNumber
from apps.registry.models import StaffMobileIndex, PatientIdentity, PatientAccount, SharedVaccination, SharedVital
from apps.patients.models import Patient
from apps.patients.services import PatientService
from apps.opd.models import Appointment, Vitals

logger = logging.getLogger(__name__)

DEFAULT_PASSWORD = "hms@1234"

# Exact vaccine_name/scheduled_label pairs, copied verbatim from the real
# seeded "Default Schedule" (apps/registry/migrations/0018_...) — must match
# these strings exactly (build_roadmap() matches on vaccine_name.lower() +
# an exact scheduled_label) or the record shows up as an unmatched "extra"
# instead of resolving its slot, same bug we fixed on the upload form.
SCHEDULE_BY_LABEL = [
    ("Birth",        ["BCG", "Hepatitis B - 1", "OPV - 0"]),
    ("6 weeks",      ["DTP - 1", "OPV - 1", "Hepatitis B - 2"]),
    ("10 weeks",     ["DTP - 2", "OPV - 2"]),
    ("14 weeks",     ["DTP - 3", "OPV - 3", "Hepatitis B - 3"]),
    ("9 months",     ["Measles - 1", "MMR - 1"]),
    ("16-18 months", ["MMR - 2 (Booster)", "DTP Booster - 1"]),
    ("5 years",      ["DTP Booster - 2"]),
    # "6 years" (Typhoid Booster) and "10 years" (Tdap/Td Booster) are
    # deliberately left unrecorded for the 6-year-old below — she just
    # turned 6, so Typhoid Booster naturally renders as "due now" with no
    # fabricated record, which is a more honest (and more interesting)
    # demo state than marking everything complete.
]

# (age_in_days, height_cm, weight_kg) — a plausible, unremarkable pediatric
# growth trajectory (WHO-ish, not a percentile lookup — see module docstring
# and PortalGrowthView's own "no percentile curves yet" note). Good enough
# to draw a real, visually varied line on the Growth chart.
GROWTH_CURVE = [
    (0,    50.0, 3.3),
    (42,   55.0, 4.5),
    (70,   58.0, 5.6),
    (98,   60.0, 6.4),
    (183,  66.0, 7.8),
    (274,  70.0, 8.9),
    (365,  75.0, 9.6),
    (548,  80.0, 11.0),
    (730,  86.0, 12.5),
    (1095, 95.0, 14.2),
    (1460, 102.0, 16.0),
    (1825, 109.0, 18.0),
    (2190, 115.0, 20.0),
]


class Command(BaseCommand):
    help = "Seed a normal-OPD doctor workflow and a pediatric doctor workflow inside one existing tenant."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", default="lakeview-clinic",
                             help="Hospital subdomain to seed into (default: lakeview-clinic).")
        parser.add_argument("--password", default=DEFAULT_PASSWORD,
                             help="Password set on every new login created (default: hms@1234).")

    def handle(self, *args, **opts):
        subdomain = opts["tenant"]
        password = opts["password"]

        try:
            tenant = Tenant.objects.using("default").get(subdomain=subdomain)
        except Tenant.DoesNotExist:
            raise CommandError(
                f"No tenant with subdomain '{subdomain}'. Pass --tenant <subdomain> "
                f"(check the Hospital Code shown in platform-admin)."
            )

        db = tenant.db_name
        if db not in settings.DATABASES:
            settings.DATABASES[db] = _make_db_config(db)
        set_tenant_db(db)

        branch = Branch.objects.using(db).filter(is_active=True).order_by("id").first()
        if not branch:
            raise CommandError(f"Tenant '{subdomain}' has no active branch — nothing to register patients into.")

        self.stdout.write(self.style.NOTICE(f"Seeding into '{tenant.name}' ({db}), branch '{branch.name}'…"))

        report = {"tenant": tenant.name, "subdomain": subdomain, "password": password}

        with transaction.atomic(using=db), transaction.atomic(using="default"):
            doctor1 = self._find_general_doctor(db)
            report["doctor1"] = self._describe_staff(db, doctor1)
            self._ensure_schedule(db, doctor1)
            self._seed_doctor1_workflow(db, branch, doctor1, report)

            doctor2 = self._ensure_pediatrician(db, tenant, branch, password)
            report["doctor2"] = self._describe_staff(db, doctor2)
            self._seed_family_workflow(db, tenant, branch, doctor2, password, report)
            self._seed_extra_pediatric_bookings(db, tenant, branch, doctor2, report)

        self._print_report(report)

    # ── Doctor 1 (existing, general workflow) ───────────────────────────────

    def _find_general_doctor(self, db):
        doctor = (
            StaffUser.objects.using(db)
            .filter(role="doctor", is_active=True)
            .order_by("id")
            .first()
        )
        if not doctor:
            raise CommandError(
                "No active doctor found in this tenant — create one via Hospital Admin → Staff first, "
                "then re-run this command."
            )
        return doctor

    def _ensure_schedule(self, db, doctor):
        schedule, _ = DoctorSchedule.objects.using(db).get_or_create(
            doctor=doctor, defaults={"slot_duration_minutes": 15},
        )
        if not DoctorAvailabilitySlot.objects.using(db).filter(schedule=schedule).exists():
            for dow in range(0, 6):  # Monday–Saturday
                DoctorAvailabilitySlot.objects.using(db).create(
                    schedule=schedule, day_of_week=dow, is_available=True,
                    start_time=dtime(9, 0), end_time=dtime(17, 0),
                )

    def _seed_doctor1_workflow(self, db, branch, doctor, report):
        today = date.today()
        adults = [
            dict(mobile="9000010001", full_name="Suresh Pillai",    dob=date(1985, 4, 12), gender="male",   complaint="Fever since 2 days", vitals=False),
            dict(mobile="9000010002", full_name="Meenakshi Rao",    dob=date(1992, 8, 3),  gender="female", complaint="Persistent cough",     vitals=False),
            dict(mobile="9000010003", full_name="Deepak Verma",     dob=date(1978, 1, 25), gender="male",   complaint="Follow-up: blood pressure", vitals=True),
            dict(mobile="9000010004", full_name="Anjali Nambiar",   dob=date(1989, 11, 9), gender="female", complaint="Routine health checkup",    vitals=True),
        ]

        next_token = self._next_token(db, doctor.id, today)
        created_summ = []
        for a in adults:
            patient = self._ensure_adult_patient(db, branch, a["mobile"], a["full_name"], a["dob"], a["gender"])
            appt = self._ensure_appointment(
                db, patient, doctor, today, next_token,
                chief_complaint=a["complaint"],
                status=Appointment.STATUS_VITALS_DONE if a["vitals"] else Appointment.STATUS_SCHEDULED,
            )
            if a["vitals"] and not Vitals.objects.using(db).filter(appointment=appt).exists():
                Vitals.objects.using(db).create(
                    appointment=appt,
                    systolic_bp=124, diastolic_bp=80, pulse_rate=76,
                    temperature=Decimal("98.4"), spo2=98, respiratory_rate=16,
                    weight_kg=Decimal("68.0"), height_cm=Decimal("168.0"),
                    nurse_notes="Vitals recorded, patient ready for consultation.",
                )
            next_token += 1
            created_summ.append(f"{a['full_name']} — {appt.status}")
        report["doctor1_patients"] = created_summ

    # ── Doctor 2 (new pediatrician) ─────────────────────────────────────────

    def _ensure_pediatrician(self, db, tenant, branch, password):
        existing = StaffUser.objects.using(db).filter(phone="9000020000").first()
        if existing:
            return existing

        NextNumber.objects.using(db).get_or_create(
            branch_id=0, entity="employee_id",
            defaults={"prefix": "EMP-", "pad_length": 6, "last_number": 0},
        )
        employee_id, _ = get_next_number(0, "employee_id", using=db)

        staff = StaffUser(
            phone="9000020000", email="kavya.pediatrician@demo.local",
            employee_id=employee_id, first_name="Kavya", last_name="Reddy",
            role="doctor", branch=branch, must_change_password=False, is_active=True,
        )
        staff.set_password(password)
        staff.save(using=db)

        DoctorProfile.objects.using(db).create(
            staff=staff, registration_no="MCI-PED-88213",
            specialisation="Pediatrics", qualification="MBBS, MD (Pediatrics)",
            gender="F", experience_years=10, consultation_fee=Decimal("450.00"),
            known_for="Child immunization, Growth concerns, Newborn care",
        )
        self._ensure_schedule(db, staff)

        # Registry-level mobile → tenant index, same write StaffInviteView
        # does — without this, logging in as Dr. Reddy by phone number can't
        # find which tenant DB to route to.
        StaffMobileIndex.objects.using("default").update_or_create(
            mobile=staff.phone,
            defaults={"tenant_id": tenant.id, "db_name": db, "email": staff.email or None},
        )

        return staff

    # ── Family: one parent, two children ────────────────────────────────────

    def _seed_family_workflow(self, db, tenant, branch, doctor2, password, report):
        today = date.today()

        parent_identity, parent_patient, parent_account = self._ensure_adult_with_portal_login(
            db, branch, mobile="9000030000", full_name="Lakshmi Krishnan",
            dob=date(1990, 6, 15), gender="female", password=password,
        )

        newborn_dob = today - timedelta(days=2)
        newborn_identity, newborn_patient = self._ensure_dependent_patient(
            db, branch, guardian_awpid=parent_identity.awpid, full_name="Aarav Krishnan",
            dob=newborn_dob, gender="male",
        )
        self._seed_vitals_and_vax(
            db, tenant, newborn_identity.awpid, newborn_dob, doctor2,
            growth_points=[(1, 50.0, 3.3)],
            vax_labels=["Birth"],
        )
        six_week_visit = newborn_dob + timedelta(days=42)
        self._ensure_appointment(
            db, newborn_patient, doctor2, six_week_visit, self._next_token(db, doctor2.id, six_week_visit),
            chief_complaint="6-week vaccination visit (DTP-1, OPV-1, Hepatitis B-2)",
            status=Appointment.STATUS_SCHEDULED,
        )

        six_yo_dob = date(today.year - 6, today.month, today.day)
        six_yo_identity, six_yo_patient = self._ensure_dependent_patient(
            db, branch, guardian_awpid=parent_identity.awpid, full_name="Diya Krishnan",
            dob=six_yo_dob, gender="female",
        )
        self._seed_vitals_and_vax(
            db, tenant, six_yo_identity.awpid, six_yo_dob, doctor2,
            growth_points=GROWTH_CURVE,
            vax_labels=[label for label, _ in SCHEDULE_BY_LABEL],
        )
        # Deliberately no appointment for the 6-year-old — "records updated,
        # nothing currently booked" bucket.

        report["family"] = {
            "parent_portal_login": {"mobile": "9000030000", "password": password, "awpid": parent_identity.awpid},
            "newborn": {"name": "Aarav Krishnan", "dob": str(newborn_dob), "awpid": newborn_identity.awpid,
                        "next_appointment": str(six_week_visit)},
            "six_year_old": {"name": "Diya Krishnan", "dob": str(six_yo_dob), "awpid": six_yo_identity.awpid,
                              "growth_points": len(GROWTH_CURVE), "vaccines_completed": sum(len(v) for _, v in SCHEDULE_BY_LABEL)},
        }

    def _seed_extra_pediatric_bookings(self, db, tenant, branch, doctor2, report):
        today = date.today()
        extras = [
            dict(guardian_mobile="9000040000", guardian_name="Priya Iyer",
                 child_name="Rohan Iyer", dob=today - timedelta(days=274),  # 9 months
                 labels=["Birth", "6 weeks", "10 weeks", "14 weeks"],
                 appt_date=today, complaint="9-month vaccination due — Measles-1, MMR-1"),
            dict(guardian_mobile="9000050000", guardian_name="Neha Sharma",
                 child_name="Ishaan Sharma", dob=today - timedelta(days=548),  # 18 months
                 labels=["Birth", "6 weeks", "10 weeks", "14 weeks", "9 months"],
                 appt_date=today + timedelta(days=1), complaint="18-month booster due — MMR-2, DTP Booster-1"),
        ]
        summary = []
        for e in extras:
            g_identity, _, _ = self._ensure_adult_with_portal_login(
                db, branch, mobile=e["guardian_mobile"], full_name=e["guardian_name"],
                dob=date(1988, 5, 20), gender="female", password=None,  # no portal login needed for these
            )
            child_identity, child_patient = self._ensure_dependent_patient(
                db, branch, guardian_awpid=g_identity.awpid, full_name=e["child_name"],
                dob=e["dob"], gender="male",
            )
            self._seed_vitals_and_vax(
                db, tenant, child_identity.awpid, e["dob"], doctor2,
                growth_points=[(1, 50.0, 3.3)],
                vax_labels=e["labels"],
            )
            self._ensure_appointment(
                db, child_patient, doctor2, e["appt_date"], self._next_token(db, doctor2.id, e["appt_date"]),
                chief_complaint=e["complaint"], status=Appointment.STATUS_SCHEDULED,
            )
            summary.append(f"{e['child_name']} — appointment {e['appt_date']}")
        report["extra_pediatric_bookings"] = summary

    # ── Shared helpers ───────────────────────────────────────────────────────

    def _ensure_adult_patient(self, db, branch, mobile, full_name, dob, gender):
        existing = Patient.objects.using(db).filter(mobile=mobile).first()
        if existing:
            return existing
        patient = PatientService.register(
            data=dict(full_name=full_name, mobile=mobile, branch_id=branch.id,
                      dpdp_consent=True, date_of_birth=dob, gender=gender),
            tenant_id=None, db_name=db,
        )
        return patient

    def _ensure_adult_with_portal_login(self, db, branch, mobile, full_name, dob, gender, password):
        patient = Patient.objects.using(db).filter(mobile=mobile).first()
        if not patient:
            patient = PatientService.register(
                data=dict(full_name=full_name, mobile=mobile, branch_id=branch.id,
                          dpdp_consent=True, hie_consent=True, date_of_birth=dob, gender=gender),
                tenant_id=None, db_name=db,
            )
        identity = PatientIdentity.objects.using("default").get(awpid=patient.awpid)
        account = None
        if password:
            account = PatientAccount.objects.using("default").filter(mobile=mobile).first()
            if not account:
                account = PatientAccount(awpid=identity.awpid, full_name=full_name, mobile=mobile,
                                          gender="F" if gender == "female" else "M", date_of_birth=dob)
                account.set_password(password)
                account.save(using="default")
        return identity, patient, account

    def _ensure_dependent_patient(self, db, branch, guardian_awpid, full_name, dob, gender):
        patient = Patient.objects.using(db).filter(
            is_dependent=True, guardian_awpid=guardian_awpid, full_name=full_name, date_of_birth=dob,
        ).first()
        if not patient:
            patient = PatientService.register(
                data=dict(full_name=full_name, is_dependent=True, guardian_awpid=guardian_awpid,
                          date_of_birth=dob, gender=gender, relationship="child",
                          branch_id=branch.id, dpdp_consent=True),
                tenant_id=None, db_name=db,
            )
        identity = PatientIdentity.objects.using("default").get(awpid=patient.awpid)
        return identity, patient

    def _next_token(self, db, doctor_id, appt_date):
        last = list(
            Appointment.objects.using(db)
            .filter(scheduled_date=appt_date, doctor_user_id=doctor_id)
            .values_list("token_number", flat=True)
        )
        return (max([t for t in last if t is not None], default=0)) + 1

    def _ensure_appointment(self, db, patient, doctor, appt_date, token, chief_complaint, status):
        existing = Appointment.objects.using(db).filter(
            patient_id=patient.uuid, doctor_user_id=doctor.id, scheduled_date=appt_date,
        ).first()
        if existing:
            return existing
        return Appointment.objects.using(db).create(
            patient_id=patient.uuid, patient_awpid=patient.awpid,
            doctor_user_id=doctor.id, doctor_name=doctor.get_full_name(),
            branch_id=patient.branch_id, appointment_type=Appointment.TYPE_OPD,
            status=status, scheduled_date=appt_date, scheduled_time=dtime(10, 0),
            token_number=token, chief_complaint=chief_complaint,
        )

    def _seed_vitals_and_vax(self, db, tenant, awpid, dob, doctor, growth_points, vax_labels):
        for age_days, height_cm, weight_kg in growth_points:
            recorded_at = timezone.make_aware(datetime.combine(dob + timedelta(days=age_days), dtime(10, 0)))
            if not SharedVital.objects.using("default").filter(awpid=awpid, recorded_at=recorded_at).exists():
                SharedVital.objects.using("default").create(
                    awpid=awpid, recorded_at=recorded_at, source="clinic",
                    height_cm=Decimal(str(height_cm)), weight_kg=Decimal(str(weight_kg)),
                    source_tenant_id=tenant.id,
                )

        label_to_names = dict(SCHEDULE_BY_LABEL)
        for label in vax_labels:
            names = label_to_names.get(label, [])
            # Rough age offset per label, matching the real schedule's min_age_days.
            offset = {"Birth": 0, "6 weeks": 42, "10 weeks": 70, "14 weeks": 98,
                      "9 months": 274, "16-18 months": 548, "5 years": 1825}.get(label, 0)
            administered = dob + timedelta(days=offset)
            for vname in names:
                if SharedVaccination.objects.using("default").filter(
                    awpid=awpid, vaccine_name=vname, scheduled_label=label,
                ).exists():
                    continue
                SharedVaccination.objects.using("default").create(
                    awpid=awpid, vaccine_name=vname, scheduled_label=label,
                    administered_date=administered, source=SharedVaccination.SOURCE_CLINIC,
                    verification_status=SharedVaccination.STATUS_VERIFIED,
                    verified_by_name=doctor.get_full_name(), verified_at=timezone.now(),
                    source_tenant_id=tenant.id, recorded_by="staff",
                )

    def _describe_staff(self, db, staff):
        # Explicit filter().first() rather than the staff.doctor_profile
        # reverse-relation accessor — that raises DoctorProfile.DoesNotExist
        # (not caught by getattr's default) if the doctor has no profile row
        # yet, e.g. an existing doctor created before specialisation was set.
        profile = DoctorProfile.objects.using(db).filter(staff=staff).first()
        return {"name": staff.get_full_name(), "phone": staff.phone, "employee_id": staff.employee_id,
                "specialisation": profile.specialisation if profile else ""}

    def _print_report(self, report):
        self.stdout.write(self.style.SUCCESS("\nSeed complete.\n"))
        self.stdout.write(f"Hospital: {report['tenant']} ({report['subdomain']})\n")
        self.stdout.write(f"Doctor 1 (general, existing): {report['doctor1']['name']} — {report['doctor1_patients']}\n")
        self.stdout.write(f"Doctor 2 (pediatrician, new): {report['doctor2']['name']} — phone 9000020000 / password {report['password']}\n")
        fam = report["family"]
        self.stdout.write(f"Parent portal login: mobile {fam['parent_portal_login']['mobile']} / password {report['password']}\n")
        self.stdout.write(f"  Newborn: {fam['newborn']}\n")
        self.stdout.write(f"  6-year-old: {fam['six_year_old']}\n")
        self.stdout.write(f"Extra pediatric bookings: {report['extra_pediatric_bookings']}\n")
