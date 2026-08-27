"""
Management command: seed_investor_demo

Seeds ONE richly-detailed "flagship" hospital tenant for an internal
investor demo — going deep on a single hospital rather than wide across
several (that's what seed_full_demo does, 4 hospitals x 3 doctors each).

This creates:
  - One Tenant on the "enterprise" license tier (every feature flag on), a
    full public profile (accreditations, about text, registration-fee
    billing config), and one Branch with a real street address/phone.
  - 15 doctors spanning 12 specialties (General Medicine, Pediatrics, and
    Orthopedics get a second doctor), each with a fully spelled-out,
    individually-authored profile below — not generated from a loop, so
    every field (mobile number, email, MCI/NMC registration number,
    qualification, years of experience, consultation + follow-up fee,
    working days, and shift hours) is a deliberate, specific value rather
    than a templated placeholder.
  - Realistic, VARIED shift hours per doctor (early-morning starters,
    midday-only, evening-only, and everything between) — with one hard
    rule applied to every single one: whatever else their hours look
    like, every doctor's shift covers 4:00-6:00 PM, so no matter when the
    demo is actually run, every doctor shows up as "available now." A
    doctor's real-world working window is one continuous [start, end)
    range in this schema (DoctorAvailabilitySlot has no split-shift
    support yet — see that model's docstring), so "different slots" here
    means different start times and different total lengths, not
    disconnected morning+evening blocks.
  - Realistic, VARIED working days per doctor — most work 5-6 days a
    week, a few senior/visiting specialists only come in 2-3 days a
    week — but every doctor, without exception, works Thursday, so the
    demo isn't at the mercy of which doctors happen to be "on" that day.
  - A dedicated consultation room per doctor spread across Ground, 1st,
    2nd, and 3rd floor (grouped roughly the way a real hospital would:
    high-footfall General Medicine/Pediatrics near the entrance on the
    ground floor, surgical/specialist OPDs upstairs, Psychiatry tucked
    away on the top floor for privacy).
  - Supporting staff for every other role (nurses, front desk, lab techs,
    pharmacists, a hospital admin).
  - The real drug catalog (apps.prescriptions.seed_drug_catalog) and lab
    test catalog (apps.lab.seed_lab_catalog) — reused as-is, not
    reinvented here.
  - A spread of patients per doctor across the real appointment lifecycle
    (waiting, vitals done, scheduled ahead, and fully completed with a
    signed consultation + prescription + real PDF lab report) — reuses
    seed_full_demo's `_build_visit` helper rather than duplicating that
    ~150 lines of logic.

Nothing here fabricates ratings, reviews, or any number a real clinic
wouldn't actually have on file — every figure is either backend-generated
(queue position, token number) or the same kind of manually-entered detail
front-desk/lab-tech/a doctor's own profile page would produce for a real
patient or a real doctor.

Idempotent: if a tenant with this subdomain already exists, the whole
command exits without touching it (safe to re-run after a partial
failure, but won't top up more doctors on a second run — that's
intentional, this is meant to run once per demo environment).

Usage:
  python manage.py seed_investor_demo --settings=atomwalk.settings.development
  python manage.py seed_investor_demo --name "Novacare Hospital" \
      --subdomain novacare-flagship --city Bengaluru --state Karnataka \
      --roster b --settings=atomwalk.settings.development

--roster b is required whenever you're seeding a SECOND hospital with this
command (see the --roster help text below) — it swaps in a completely
different set of 15 doctor names so the two hospitals never show up with
an identically-named doctor in the cross-hospital patient search.

Requires reportlab (same as seed_full_demo — for the lab report PDFs):
  pip install reportlab --break-system-packages

After this, optionally run set_investor_demo_photos to attach real
(stock, license-free) doctor portrait photos — see that command's
docstring for why it can't run from a network-sandboxed environment.
"""

import itertools
import logging
from datetime import date, time as dtime
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.tenants.models import Tenant, Subscription
from apps.tenants.utils import create_tenant_database, run_tenant_migrations, _make_db_config
from apps.tenants.management.commands.provision_tenant import TIER_FEATURE_DEFAULTS
from apps.org.models import (
    Branch, StaffUser, DoctorProfile, StaffProfile, NextNumber, Room, RoomAssignment,
    DoctorSchedule, DoctorAvailabilitySlot,
)
from apps.registry.models import StaffMobileIndex
from apps.billing.models import BillingService
from apps.lab.models import LabTest
from apps.patients.services import PatientService
from core.db_router import _thread_local

from apps.registry.management.commands.seed_full_demo import (
    Command as SeedFullDemoCommand,
    _register_db, _random_dob, _patient_name_iter,
)

logger = logging.getLogger(__name__)

STAFF_PASSWORD = "Demo@12345"
PATIENT_PASSWORD = "Patient@12345"

# day_of_week: 0=Monday ... 6=Sunday (Python's date.weekday() convention,
# same as DoctorAvailabilitySlot/RoomAssignment). 3 = Thursday — every
# doctor below includes it deliberately (see module docstring).
MON, TUE, WED, THU, FRI, SAT, SUN = range(7)

# Every one of the 15 doctors below is hand-specified, not generated —
# every field is a deliberate value. `start`/`end` is the doctor's one
# continuous working window each day they work; every window here spans
# 4:00-6:00 PM regardless of how different the rest of the shift looks,
# so any doctor is bookable/"available now" whenever the demo happens to
# run. `days` always includes THU.
DOCTORS = [
    dict(first="Anil", last="Kumar", gender="M", mobile="9845010001",
         spec="General Medicine", qual="MBBS, MD (General Medicine)",
         reg_no="NMC-KA-2011-04521", exp=14, fee=500, followup_fee=350,
         known_for="Fever, Diabetes, Hypertension, General checkups",
         start=dtime(9, 0), end=dtime(18, 0), days=[MON, TUE, WED, THU, FRI, SAT],
         floor="Ground Floor", room="Ground OPD-1"),
    dict(first="Shalini", last="Rao", gender="F", mobile="9845010002",
         spec="General Medicine", qual="MBBS, MD (General Medicine)",
         reg_no="NMC-KA-2015-08832", exp=9, fee=550, followup_fee=400,
         known_for="Preventive health checkups, Chronic disease management",
         start=dtime(10, 0), end=dtime(18, 0), days=[MON, TUE, THU, FRI, SAT],
         floor="Ground Floor", room="Ground OPD-2"),
    dict(first="Arjun", last="Mehta", gender="M", mobile="9886010003",
         spec="Pediatrics", qual="MBBS, MD (Pediatrics)",
         reg_no="NMC-KA-2009-02214", exp=16, fee=450, followup_fee=300,
         known_for="Child immunization, Growth concerns, Common infections",
         start=dtime(9, 30), end=dtime(18, 0), days=[MON, TUE, WED, THU, FRI, SAT],
         floor="Ground Floor", room="Ground OPD-3"),
    dict(first="Kavita", last="Iyer", gender="F", mobile="9886010004",
         spec="Pediatrics", qual="MBBS, DCH (Pediatrics)",
         reg_no="NMC-KA-2017-09341", exp=7, fee=500, followup_fee=350,
         known_for="Newborn care, Nutrition counselling, Vaccination",
         start=dtime(11, 0), end=dtime(18, 0), days=[TUE, WED, THU, FRI, SAT],
         floor="Ground Floor", room="Ground OPD-4"),
    dict(first="Rajesh", last="Nair", gender="M", mobile="9900010005",
         spec="Orthopedics", qual="MBBS, MS (Orthopedics)",
         reg_no="NMC-KA-2008-01187", exp=17, fee=700, followup_fee=500,
         known_for="Joint pain, Fractures, Back pain, Sports injuries",
         start=dtime(10, 0), end=dtime(19, 0), days=[MON, TUE, WED, THU, FRI, SAT],
         floor="1st Floor", room="1st Floor OPD-1"),
    dict(first="Pooja", last="Sharma", gender="F", mobile="9900010006",
         spec="Orthopedics", qual="MBBS, MS (Ortho), Fellowship Joint Replacement",
         reg_no="NMC-KA-2012-05563", exp=12, fee=900, followup_fee=650,
         known_for="Knee & hip replacement, Spine care",
         start=dtime(12, 0), end=dtime(19, 0), days=[TUE, THU, FRI],
         floor="1st Floor", room="1st Floor OPD-2"),
    dict(first="Vivek", last="Chandran", gender="M", mobile="9741010007",
         spec="Gynecology", qual="MBBS, MS (OBG)",
         reg_no="NMC-KA-2010-03398", exp=15, fee=650, followup_fee=450,
         known_for="Pregnancy care, PCOS, Menstrual disorders",
         start=dtime(9, 0), end=dtime(18, 0), days=[MON, TUE, THU, FRI, SAT],
         floor="1st Floor", room="1st Floor OPD-3"),
    dict(first="Ritu", last="Kapoor", gender="F", mobile="9741010008",
         spec="Cardiology", qual="MBBS, MD, DM (Cardiology)",
         reg_no="NMC-KA-2006-00721", exp=19, fee=900, followup_fee=650,
         known_for="Chest pain, Hypertension, Heart checkups",
         start=dtime(11, 0), end=dtime(19, 0), days=[MON, TUE, WED, THU, FRI, SAT],
         floor="1st Floor", room="1st Floor OPD-4"),
    dict(first="Sanjay", last="Bhatia", gender="M", mobile="9880010009",
         spec="Dermatology", qual="MBBS, MD (Dermatology)",
         reg_no="NMC-KA-2013-06674", exp=11, fee=550, followup_fee=400,
         known_for="Skin allergies, Acne, Hair fall",
         start=dtime(12, 0), end=dtime(18, 0), days=[MON, TUE, THU, SAT],
         floor="1st Floor", room="1st Floor OPD-5"),
    dict(first="Anjali", last="Desai", gender="F", mobile="9880010010",
         spec="ENT", qual="MBBS, MS (ENT)",
         reg_no="NMC-KA-2014-07458", exp=10, fee=500, followup_fee=350,
         known_for="Sinusitis, Hearing issues, Throat infections",
         start=dtime(13, 0), end=dtime(18, 0), days=[TUE, WED, THU, FRI, SAT],
         floor="2nd Floor", room="2nd Floor OPD-1"),
    dict(first="Manoj", last="Pillai", gender="M", mobile="9902010011",
         spec="Endocrinology", qual="MBBS, MD, DM (Endocrinology)",
         reg_no="NMC-KA-2007-01532", exp=18, fee=800, followup_fee=600,
         known_for="Diabetes, Thyroid disorders, Hypertension",
         start=dtime(13, 0), end=dtime(19, 0), days=[MON, WED, THU, FRI, SAT],
         floor="2nd Floor", room="2nd Floor OPD-2"),
    dict(first="Sneha", last="Warrier", gender="F", mobile="9902010012",
         spec="Pulmonology", qual="MBBS, MD (Pulmonology)",
         reg_no="NMC-KA-2016-08967", exp=8, fee=750, followup_fee=550,
         known_for="Asthma, Chronic cough, Breathlessness",
         start=dtime(14, 0), end=dtime(18, 0), days=[TUE, THU, FRI],
         floor="2nd Floor", room="2nd Floor OPD-3"),
    dict(first="Deepak", last="Shetty", gender="M", mobile="9663010013",
         spec="Gastroenterology", qual="MBBS, MD, DM (Gastroenterology)",
         reg_no="NMC-KA-2005-00298", exp=20, fee=700, followup_fee=500,
         known_for="Acidity, IBS, Liver disorders",
         start=dtime(14, 0), end=dtime(19, 0), days=[MON, TUE, WED, THU, FRI, SAT],
         floor="2nd Floor", room="2nd Floor OPD-4"),
    dict(first="Nandita", last="Ghosh", gender="F", mobile="9663010014",
         spec="Nephrology", qual="MBBS, MD, DM (Nephrology)",
         reg_no="NMC-KA-2011-04890", exp=13, fee=800, followup_fee=600,
         known_for="Kidney stones, CKD, Hypertension",
         start=dtime(15, 0), end=dtime(19, 0), days=[THU, SAT],
         floor="3rd Floor", room="3rd Floor OPD-1"),
    dict(first="Rahul", last="Verma", gender="M", mobile="9741010015",
         spec="Psychiatry", qual="MBBS, MD (Psychiatry)",
         reg_no="NMC-KA-2012-05219", exp=12, fee=600, followup_fee=450,
         known_for="Anxiety, Depression, Sleep disorders",
         start=dtime(16, 0), end=dtime(21, 0), days=[MON, TUE, THU, FRI, SAT],
         floor="3rd Floor", room="3rd Floor OPD-2"),
]
for _d in DOCTORS:
    assert _d["start"] <= dtime(16, 0) and _d["end"] >= dtime(18, 0), \
        f"{_d['first']} {_d['last']}'s shift doesn't cover 4-6 PM"
    assert THU in _d["days"], f"{_d['first']} {_d['last']} isn't working on Thursday"

# A second, entirely distinct set of 15 doctors — pass --roster b when
# seeding a second demo hospital from this same command so it doesn't end
# up with doctors that share a name with the first hospital's. Cross-
# hospital patient search (apps.patients.portal_views.PortalSearchView)
# shows every active hospital's doctors together, so two hospitals with an
# identically-named "Dr. Ritu Kapoor" read as a bug even though they're
# correctly two different people at two different hospitals — this is
# what caused that the first time (both flagship hospitals were seeded
# from the same hardcoded DOCTORS list above).
#
# Same specialty/schedule/room/fee per position as DOCTORS — that's the
# physical hospital's own setup, independent of which specific person is
# in the chair — only the identity fields (name, mobile, registration
# number) differ, and every one of those is unique versus DOCTORS above
# and versus every other hardcoded name in this file.
_DOCTORS_B_IDENTITY = [
    ("Suresh",    "Acharya",     "9811110001", "NMC-KA-2011-11201"),
    ("Meenakshi", "Subramaniam", "9811110002", "NMC-KA-2015-11202"),
    ("Rohit",     "Bajaj",       "9811110003", "NMC-KA-2009-11203"),
    ("Divya",     "Menezes",     "9811110004", "NMC-KA-2017-11204"),
    ("Harish",    "Bhalla",      "9811110005", "NMC-KA-2008-11205"),
    ("Swati",     "Kulkarni",    "9811110006", "NMC-KA-2012-11206"),
    ("Naveen",    "Reddy",       "9811110007", "NMC-KA-2010-11207"),
    ("Kavya",     "Prabhu",      "9811110008", "NMC-KA-2006-11208"),
    ("Ashok",     "Malhotra",    "9811110009", "NMC-KA-2013-11209"),
    ("Ritika",    "Sengupta",    "9811110010", "NMC-KA-2014-11210"),
    ("Vikram",    "Oberoi",      "9811110011", "NMC-KA-2007-11211"),
    ("Farah",     "Qadri",       "9811110012", "NMC-KA-2016-11212"),
    ("Girish",    "Kamath",      "9811110013", "NMC-KA-2005-11213"),
    ("Alka",      "Dutta",       "9811110014", "NMC-KA-2011-11214"),
    ("Sameer",    "Chowdhury",   "9811110015", "NMC-KA-2012-11215"),
]
assert len(_DOCTORS_B_IDENTITY) == len(DOCTORS), "DOCTORS_B_IDENTITY must have one entry per DOCTORS entry"

DOCTORS_B = []
for _base, (_first, _last, _mobile, _reg) in zip(DOCTORS, _DOCTORS_B_IDENTITY):
    _nd = dict(_base)
    _nd.update(first=_first, last=_last, mobile=_mobile, reg_no=_reg)
    DOCTORS_B.append(_nd)

for _d in DOCTORS_B:
    assert _d["start"] <= dtime(16, 0) and _d["end"] >= dtime(18, 0), \
        f"{_d['first']} {_d['last']}'s shift doesn't cover 4-6 PM"
    assert THU in _d["days"], f"{_d['first']} {_d['last']} isn't working on Thursday"

_all_doctor_names = [(d["first"], d["last"]) for d in DOCTORS] + [(d["first"], d["last"]) for d in DOCTORS_B]
assert len(_all_doctor_names) == len(set(_all_doctor_names)), "DOCTORS and DOCTORS_B must not share a name"

# 4th element is experience_years — used to backfill StaffProfile.experience_years
# and, combined with the per-role "years since qualifying" base age in
# _dob_for_role() below, a realistic StaffUser.date_of_birth. Doctors already
# carry their own "exp" key in the DOCTORS dicts above; these five lists
# needed the same thing added since nothing else in this file tracked it.
NURSE_NAMES = [
    ("Lakshmi", "Menon", "F", 9), ("Ramesh", "Yadav", "M", 5), ("Sunita", "Bose", "F", 12),
    ("Arvind", "Naidu", "M", 7), ("Pooja", "Tiwari", "F", 4), ("Manoj", "Pandey", "M", 15),
    ("Geeta", "Chauhan", "F", 6), ("Vishal", "Mishra", "M", 3),
]
FRONT_DESK_NAMES = [("Sanjay", "Trivedi", "M", 6), ("Kirti", "Agarwal", "F", 3)]
LAB_TECH_NAMES   = [("Prakash", "Chopra", "M", 9), ("Shreya", "Rathi", "F", 4)]
PHARMACIST_NAMES = [("Ajay", "Deshmukh", "M", 7), ("Nandini", "Qureshi", "F", 5)]
ADMIN_NAMES      = [("Radhika", "Nambiar", "F", 14), ("Imran", "Sheikh", "M", 10)]

# Qualification pool per role (varied so not every nurse/pharmacist/etc.
# looks like a copy-paste of the next one) and the legally-relevant detail
# (registration_no/council_name) for the two roles StaffProfile's own
# docstring calls out as mandatory-by-law: nurse and pharmacist.
STAFF_QUALIFICATIONS = {
    "nurse":          ["B.Sc Nursing", "GNM (General Nursing & Midwifery)", "P.B. B.Sc Nursing"],
    "front_desk":      ["B.Com", "BBA", "Diploma in Hospital Administration"],
    "lab_tech":       ["B.Sc MLT (Medical Laboratory Technology)", "DMLT"],
    "pharmacist":     ["B.Pharm", "D.Pharm", "M.Pharm"],
    "hospital_admin": ["MHA (Master of Hospital Administration)", "MBA (Healthcare Management)"],
}
STAFF_COUNCIL = {
    "nurse":      "Karnataka State Nursing Council",
    "pharmacist": "Karnataka State Pharmacy Council",
    "lab_tech":   "Karnataka Medical Lab Technicians Board",
}
STAFF_REG_PREFIX = {"nurse": "KSNC", "pharmacist": "KSPC", "lab_tech": "KMLTB"}
# Rough age a person in that role would realistically be, N years after
# finishing the degree above (used only to derive a plausible DOB — doctors
# use a separate, higher base since MBBS + MD/MS/DM takes longer than a
# nursing/pharmacy/commerce degree).
STAFF_ROLE_BASE_AGE = {
    "nurse": 22, "front_desk": 21, "lab_tech": 22, "pharmacist": 22, "hospital_admin": 26,
}
DOCTOR_BASE_AGE = 27  # MBBS (~24) + internship/PG entry — see DOCTORS' exp values above

# Populates the empty "Service Price Catalog" panel on Billing Setup — ad-hoc
# billable items (procedures, room/bed charges, misc.) that fall outside the
# consultation fee (set per-doctor above), the lab test catalog, and the drug
# catalog, each of which already has its own dedicated pricing system.
BILLING_CATALOG = [
    ("ECG", "PROC-ECG", "Procedure", "250"),
    ("X-Ray (Single View)", "PROC-XRAY1", "Procedure", "400"),
    ("X-Ray (Two Views)", "PROC-XRAY2", "Procedure", "650"),
    ("Nebulization", "PROC-NEB", "Procedure", "150"),
    ("IV Fluid Administration", "PROC-IVF", "Procedure", "300"),
    ("Dressing (Minor)", "PROC-DRESS-MIN", "Procedure", "150"),
    ("Dressing (Major)", "PROC-DRESS-MAJ", "Procedure", "450"),
    ("Suturing", "PROC-SUTURE", "Procedure", "500"),
    ("Plaster Cast Application", "PROC-CAST", "Procedure", "800"),
    ("Physiotherapy Session", "PROC-PHYSIO", "Procedure", "400"),
    ("General Ward (Per Day)", "ROOM-GEN", "Room / Bed", "1500"),
    ("Semi-Private Room (Per Day)", "ROOM-SEMI", "Room / Bed", "2800"),
    ("Private Room (Per Day)", "ROOM-PVT", "Room / Bed", "4500"),
    ("ICU (Per Day)", "ROOM-ICU", "Room / Bed", "8000"),
    ("Ambulance (Local)", "OTH-AMB", "Other", "1200"),
    ("Wheelchair Rental (Per Day)", "OTH-WCHAIR", "Other", "100"),
    ("Discharge Summary Fee", "OTH-DISCHG", "Other", "200"),
]

BIO_TEMPLATES = [
    "Dr. {last} ({qual}) has {exp} years of experience in {spec}, with a "
    "particular focus on {known_for_lower}. Known for a patient-first, "
    "explain-everything approach to consultations at {hospital}.",
    "With {exp} years in {spec} and a qualification of {qual}, Dr. {last} "
    "regularly sees cases involving {known_for_lower}. Believes in "
    "spending the time a diagnosis actually needs, not rushing a visit.",
    "Dr. {last} is a {spec} specialist ({qual}) with {exp} years of "
    "clinical experience, treating {known_for_lower} at {hospital}. "
    "Trained to keep explanations simple without skipping the details "
    "that matter.",
]

DAY_LABEL = {MON: "Mon", TUE: "Tue", WED: "Wed", THU: "Thu", FRI: "Fri", SAT: "Sat", SUN: "Sun"}


class Command(BaseCommand):
    help = "Seed one richly-detailed flagship hospital tenant for an investor demo (15 hand-specified doctors, full profiles, rooms, catalogs, patients)."

    def add_arguments(self, parser):
        parser.add_argument("--name", default="Novacare Hospital")
        parser.add_argument("--subdomain", default="novacare-flagship")
        parser.add_argument("--city", default="Bengaluru")
        parser.add_argument("--state", default="Karnataka")
        parser.add_argument("--address", default="482, 12th Main Road, Indiranagar")
        parser.add_argument("--pincode", default="560038")
        parser.add_argument("--phone", default="08041234567")
        parser.add_argument("--code", default="NCH", help="UHID/invoice prefix code for this hospital.")
        parser.add_argument("--patients-per-doctor", type=int, default=4)
        parser.add_argument(
            "--roster", choices=["a", "b"], default="a",
            help=(
                "Which hand-authored 15-doctor roster to use. 'a' is the original list "
                "(Anil Kumar ... Rahul Verma). 'b' is a second, entirely distinct set of names "
                "with the same specialties/schedules/rooms — always pass this when seeding a "
                "SECOND demo hospital, so it doesn't end up with doctors that share a name with "
                "the first one (cross-hospital patient search shows every hospital's doctors "
                "together, so identical names there read as a bug)."
            ),
        )

    def handle(self, *args, **options):
        import random
        rng = random.Random(20260827)

        try:
            import reportlab  # noqa: F401
        except ImportError:
            raise CommandError(
                "reportlab is not installed. Run: pip install reportlab --break-system-packages "
                "(or: pip install -r requirements.txt) and re-run this command."
            )

        name = options["name"]
        subdomain = options["subdomain"]
        city = options["city"]
        state = options["state"]
        address = options["address"]
        pincode = options["pincode"]
        phone = options["phone"]
        code = options["code"]
        patients_per_doctor = options["patients_per_doctor"]
        doctor_roster = DOCTORS if options["roster"] == "a" else DOCTORS_B

        if Tenant.objects.using("default").filter(subdomain=subdomain).exists():
            raise CommandError(
                f"A tenant with subdomain '{subdomain}' already exists. This command is meant to "
                f"run once per demo environment — pass a different --subdomain if you want a second one, "
                f"or delete the existing tenant first if you want to re-seed from scratch."
            )

        self.stdout.write(f"\n{'=' * 70}\n  {name} ({subdomain})\n{'=' * 70}")

        tenant = Tenant.objects.create(
            name=name, subdomain=subdomain, db_name=f"aw_{subdomain.replace('-', '_')}",
            city=city, state=state,
            accreditations="NABH, ISO 9001:2015, NABL",
            about=(
                f"{name} is a full-service multispecialty hospital in {city} offering "
                f"{len(set(d['spec'] for d in doctor_roster))} specialties under one roof, "
                f"with an in-house pharmacy and diagnostic lab."
            ),
            is_active=True,
            registration_fee_enabled=True,
            registration_fee_amount=Decimal("200"),
            default_tax_rate=Decimal("0"),
        )
        Subscription.objects.create(
            tenant=tenant, license_tier="enterprise", status="active",
            **TIER_FEATURE_DEFAULTS["enterprise"],
        )

        db = tenant.db_name
        self.stdout.write("  Creating database...")
        create_tenant_database(db)
        self.stdout.write("  Running migrations...")
        run_tenant_migrations(db)
        _register_db(db)
        _thread_local.tenant_id = tenant.id
        _thread_local.db_alias = db

        # Everything from here on is wrapped in one transaction per DB — if
        # anything fails partway through (a bad catalog seed, a duplicate
        # phone number, anything), both DBs roll back cleanly instead of
        # leaving a half-created hospital (some doctors but not others, no
        # patients) that then blocks a clean re-run because the Tenant row
        # above already exists. The Tenant/Subscription/DB-creation/
        # migration steps above can't be inside this — create_tenant_database
        # must run outside any transaction — so a failure before this point
        # still needs a manual `Tenant.objects.get(subdomain=...).delete()`
        # before retrying; a failure from here on doesn't.
        with transaction.atomic(using=db), transaction.atomic(using="default"):
            branch = Branch.objects.using(db).create(
                name=name, address=address, city=city, state=state, pincode=pincode,
                phone=phone, is_active=True,
            )

            for entity, prefix, pad in [
                ("uhid", f"{code}-", 6), ("invoice", "INV-", 6),
                ("lab_report", "LR-", 6), ("lab_test", "LT-", 4),
                ("prescription", "RX-", 6), ("queue", "", 4),
            ]:
                NextNumber.objects.using(db).get_or_create(
                    branch_id=branch.id, entity=entity, defaults={"prefix": prefix, "pad_length": pad, "last_number": 0},
                )

            self.stdout.write("  Seeding lab test catalog...")
            call_command("seed_lab_catalog", "--tenant", db)
            self.stdout.write("  Seeding drug catalog...")
            call_command("seed_drug_catalog", "--tenant", db)

            # ServiceCategory rows ("Consultation", "Procedure", "Room / Bed",
            # "Other", ...) already exist per-tenant via billing migration
            # 0005 — this just populates the price list itself, which nothing
            # else seeds (consultation/lab/pharmacy pricing come from their
            # own dedicated systems above, not this catalog).
            self.stdout.write("  Seeding billing service price catalog...")
            for svc_name, svc_code, svc_category, svc_price in BILLING_CATALOG:
                BillingService.objects.using(db).get_or_create(
                    name=svc_name,
                    defaults={"code": svc_code, "category": svc_category,
                              "unit_price": Decimal(svc_price), "tax_rate": Decimal("0"),
                              "is_active": True},
                )

            lab_tests = list(LabTest.objects.using(db).all())
            language = f"English, Hindi, {self._local_language(city)}"

            admin_first, admin_last, admin_gender, admin_exp = ADMIN_NAMES[0]
            admin_email = f"{admin_first.lower()}.admin@{subdomain}.demo"
            admin = self._make_staff(db, tenant, "hospital_admin", admin_first, admin_last, admin_email, branch)
            self._finish_staff(db, admin, "hospital_admin", admin_exp, admin_gender, language, rng, name)

            # ── Doctors — full profile + working schedule + dedicated room ──
            self.stdout.write(f"  Creating {len(doctor_roster)} doctors...")
            doctors = []
            for i, d in enumerate(doctor_roster):
                email = f"{d['first'].lower()}.{d['last'].lower()}@{subdomain}.demo"
                staff = self._make_staff(db, tenant, "doctor", d["first"], d["last"], email, branch, mobile=d["mobile"])
                bio = BIO_TEMPLATES[i % len(BIO_TEMPLATES)].format(
                    last=d["last"], qual=d["qual"], exp=d["exp"], spec=d["spec"],
                    known_for_lower=d["known_for"].lower(), hospital=name,
                )
                DoctorProfile.objects.using(db).create(
                    staff=staff, registration_no=d["reg_no"],
                    specialisation=d["spec"], qualification=d["qual"],
                    gender=d["gender"], experience_years=d["exp"],
                    consultation_fee=Decimal(str(d["fee"])),
                    followup_fee=Decimal(str(d["followup_fee"])),
                    bio=bio, languages=language, known_for=d["known_for"],
                )
                self._finish_staff(db, staff, "doctor", d["exp"], d["gender"], language, rng, name)

                schedule = DoctorSchedule.objects.using(db).create(doctor=staff, slot_duration_minutes=15)
                for dow in d["days"]:
                    DoctorAvailabilitySlot.objects.using(db).create(
                        schedule=schedule, day_of_week=dow, is_available=True,
                        start_time=d["start"], end_time=d["end"],
                    )

                room = Room.objects.using(db).create(
                    branch=branch, floor=d["floor"], name=d["room"], room_type="consultation",
                )
                for dow in d["days"]:
                    RoomAssignment.objects.using(db).create(
                        room=room, doctor=staff, day_of_week=dow,
                        start_time=d["start"], end_time=d["end"],
                    )

                days_str = "/".join(DAY_LABEL[dow] for dow in d["days"])
                self.stdout.write(
                    f"    Dr. {d['first']} {d['last']} — {d['spec']} — {d['room']} — "
                    f"{days_str} {d['start'].strftime('%H:%M')}-{d['end'].strftime('%H:%M')}"
                )
                doctors.append((staff, d))

            # ── Supporting staff ─────────────────────────────────────────────
            nurses = []
            for i, (first, last, gender, exp) in enumerate(NURSE_NAMES):
                staff = self._make_staff(db, tenant, "nurse", first, last, f"{first.lower()}.nurse{i + 1}@{subdomain}.demo", branch)
                self._finish_staff(db, staff, "nurse", exp, gender, language, rng, name)
                nurses.append(staff)

            front_desks = []
            for i, (first, last, gender, exp) in enumerate(FRONT_DESK_NAMES):
                staff = self._make_staff(db, tenant, "front_desk", first, last, f"{first.lower()}.frontdesk{i + 1}@{subdomain}.demo", branch)
                self._finish_staff(db, staff, "front_desk", exp, gender, language, rng, name)
                front_desks.append(staff)

            lab_techs = []
            for i, (first, last, gender, exp) in enumerate(LAB_TECH_NAMES):
                staff = self._make_staff(db, tenant, "lab_tech", first, last, f"{first.lower()}.labtech{i + 1}@{subdomain}.demo", branch)
                self._finish_staff(db, staff, "lab_tech", exp, gender, language, rng, name)
                lab_techs.append(staff)

            pharmacists = []
            for i, (first, last, gender, exp) in enumerate(PHARMACIST_NAMES):
                staff = self._make_staff(db, tenant, "pharmacist", first, last, f"{first.lower()}.pharmacist{i + 1}@{subdomain}.demo", branch)
                self._finish_staff(db, staff, "pharmacist", exp, gender, language, rng, name)
                pharmacists.append(staff)

            front_desk = front_desks[0]
            lab_tech = lab_techs[0]

            # ── Patients across the appointment lifecycle, per doctor ───────
            self.stdout.write(f"  Seeding patients ({patients_per_doctor} per doctor)...")
            helper = SeedFullDemoCommand()
            patient_names = _patient_name_iter(rng)
            states_cycle = ["done", "done", "waiting", "vitals_done", "scheduled"]

            for doc, d in doctors:
                for p_i in range(patients_per_doctor):
                    first, last = next(patient_names)
                    dob = _random_dob(rng)
                    gender = rng.choice(["M", "F"])
                    mobile = self._next_patient_mobile()
                    patient = PatientService.register(
                        {
                            "full_name": f"{first} {last}", "mobile": mobile,
                            "branch_id": branch.id, "gender": gender, "date_of_birth": dob,
                            "dpdp_consent": True, "hie_consent": False, "preferred_language": "en",
                        },
                        tenant_id=tenant.id, db_name=db,
                    )
                    state = states_cycle[p_i % len(states_cycle)]
                    helper._build_visit(db, tenant, branch, patient, doc, front_desk, lab_tech, lab_tests, rng, state)

            # _build_visit (seed_full_demo) never sets room_id/room_name/floor
            # on any appointment it creates — including the "done" state's
            # auto-generated follow-up booking, which isn't even returned to
            # us to backfill one at a time. Every doctor above DOES have a
            # real dedicated Room + RoomAssignment though, so resolve each
            # appointment's room the same way a real front-desk booking
            # would (apps.org.room_utils.resolve_room_for_slot, matched by
            # the doctor's day-of-week + time window) rather than leaving
            # every seeded appointment showing a blank Room column.
            self.stdout.write("  Backfilling room assignment onto seeded appointments...")
            import uuid as _uuid
            from apps.org.room_utils import resolve_room_for_slot, get_doctor_home_room
            room_filled = 0
            for appt in Appointment.objects.using(db).filter(
                branch_id=branch.id, room_id__isnull=True, scheduled_time__isnull=False,
            ):
                # doctor_user_id reads back as a real uuid.UUID object here
                # (Django's UUIDField behavior), but RoomAssignment.doctor_id
                # is a plain int FK — unwrap via .int, same as
                # apps.opd.views._resolve_doctor_consultation_fee does.
                raw_doctor_id = (
                    appt.doctor_user_id.int if isinstance(appt.doctor_user_id, _uuid.UUID)
                    else appt.doctor_user_id
                )
                match = resolve_room_for_slot(db, raw_doctor_id, appt.scheduled_date.weekday(), appt.scheduled_time)
                if not match:
                    # Seeded times (current wall-clock for waiting/vitals,
                    # a fixed 11:30 follow-up slot, etc.) don't always land
                    # inside the doctor's exact RoomAssignment window even
                    # though every doctor covers 4-6 PM daily. Fall back to
                    # the doctor's one dedicated room rather than leaving
                    # the column blank.
                    match = get_doctor_home_room(db, raw_doctor_id)
                if not match:
                    continue
                appt.room_id = match.room_id
                appt.room_name = match.room.name
                appt.floor = match.room.floor
                appt.save(using=db, update_fields=["room_id", "room_name", "floor"])
                room_filled += 1
            self.stdout.write(f"    {room_filled} appointment(s) got a room.")

        self.stdout.write(self.style.SUCCESS(f"\n  Seeded {name} — {len(doctors)} doctors, "
                                              f"{len(nurses) + len(front_desks) + len(lab_techs) + len(pharmacists) + 1} other staff, "
                                              f"{len(doctors) * patients_per_doctor} patients."))

        # ── Credentials file ─────────────────────────────────────────────────
        lines = [f"# {name} — Investor Demo Credentials\n",
                 f"Generated: {timezone.now().strftime('%d-%b-%Y %H:%M')}\n",
                 f"\nHospital subdomain: `{subdomain}`  |  City: {city}, {state}\n",
                 f"\nDefault staff password (all roles): `{STAFF_PASSWORD}`\n",
                 f"Default patient portal password: `{PATIENT_PASSWORD}`\n",
                 f"\n## Hospital Admin\n- `{admin_email}`\n",
                 f"\n## Doctors ({len(doctors)})\n"]
        for doc, d in doctors:
            days_str = "/".join(DAY_LABEL[dow] for dow in d["days"])
            lines.append(
                f"- **Dr. {d['first']} {d['last']}** — {d['spec']} — {d['qual']} — {d['exp']}y exp — "
                f"₹{d['fee']} consult / ₹{d['followup_fee']} follow-up — {d['room']} ({d['floor']}) — "
                f"{days_str} {d['start'].strftime('%H:%M')}-{d['end'].strftime('%H:%M')}\n"
                f"  Login: `{doc.email}`  |  Mobile: {d['mobile']}  |  Reg. No: {d['reg_no']}\n"
            )
        lines.append(f"\n## Nurses\n")
        for n in nurses:
            lines.append(f"- `{n.email}`\n")
        lines.append(f"\n## Front Desk\n")
        for f in front_desks:
            lines.append(f"- `{f.email}`\n")
        lines.append(f"\n## Lab Technicians\n")
        for l in lab_techs:
            lines.append(f"- `{l.email}`\n")
        lines.append(f"\n## Pharmacists\n")
        for p in pharmacists:
            lines.append(f"- `{p.email}`\n")
        lines.append(
            f"\n## Optional next step\nRun `python manage.py set_investor_demo_photos --tenant {db}` "
            f"from a machine with real internet access to attach stock doctor portrait photos.\n"
        )

        out_path = Path(settings.BASE_DIR) / "INVESTOR_DEMO_CREDENTIALS.md"
        out_path.write_text("".join(lines), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"\nAll done. Full credential list written to: {out_path}"))

    # ── helpers ──────────────────────────────────────────────────────────────
    def _make_staff(self, db, tenant, role, first, last, email, branch, mobile=None):
        # StaffUser.phone is `unique=True` with no null=True — it's the staff
        # login identifier, not an optional field (see apps/org/models.py).
        # Leaving it unset defaults every row to "", and the second such row
        # in the same tenant DB collides on the unique constraint. Doctors
        # already get a specific, hand-picked number from DOCTORS; every
        # other role gets one generated here so nobody is ever created blank.
        phone = mobile or self._next_staff_mobile()
        staff = StaffUser(
            email=email, first_name=first, last_name=last, role=role, branch=branch,
            phone=phone,
        )
        staff.set_password(STAFF_PASSWORD)
        staff.save(using=db)
        # StaffEmailIndex is deprecated (see apps/registry/models.py) — actual
        # staff login (StaffLoginView) resolves the tenant DB through
        # StaffMobileIndex by mobile OR email, keyed on `mobile`. Writing the
        # old table only (as an earlier version of this command did) leaves
        # every seeded login unable to authenticate at all: "Invalid
        # credentials" for a real, existing StaffUser row.
        StaffMobileIndex.objects.using("default").update_or_create(
            mobile=phone, defaults={"tenant_id": tenant.id, "db_name": db, "email": email or None},
        )
        return staff

    def _dob_for_age(self, rng, age):
        # Approximate — good enough for demo data. Caps day at 28 to dodge
        # Feb 29 without extra month-length logic.
        year = date.today().year - age
        return date(year, rng.randint(1, 12), rng.randint(1, 28))

    def _finish_staff(self, db, staff, role, exp, gender, language, rng, hospital_name):
        # Fills in everything the profile screens showed blank: DOB on every
        # StaffUser (doctors included — the user explicitly called this out),
        # plus a full StaffProfile for every non-doctor role (doctors already
        # get their equivalent detail via DoctorProfile in the caller).
        base_age = DOCTOR_BASE_AGE if role == "doctor" else STAFF_ROLE_BASE_AGE.get(role, 24)
        staff.date_of_birth = self._dob_for_age(rng, base_age + exp)
        staff.save(using=db, update_fields=["date_of_birth"])

        if role == "doctor":
            return

        role_label = role.replace("_", " ").title()
        profile_fields = dict(
            qualification=rng.choice(STAFF_QUALIFICATIONS.get(role, ["Diploma"])),
            experience_years=exp,
            gender=gender,
            bio=(f"{role_label} with {exp} years of experience in patient care "
                 f"and hospital operations at {hospital_name}."),
            languages=language,
        )
        # Mandatory-by-law registration detail for nurse/pharmacist (see
        # StaffProfile's docstring) — also filled for lab_tech since the
        # Staff page's own label ("if applicable") doesn't mean "never".
        if role in STAFF_COUNCIL:
            profile_fields.update(
                registration_no=f"{STAFF_REG_PREFIX[role]}-{rng.randint(10000, 99999)}",
                council_name=STAFF_COUNCIL[role],
                registration_expiry=date(date.today().year + rng.randint(2, 4), rng.randint(1, 12), rng.randint(1, 28)),
            )
        StaffProfile.objects.using(db).update_or_create(staff=staff, defaults=profile_fields)

    def _local_language(self, city):
        return {
            "Bengaluru": "Kannada", "Chennai": "Tamil", "Hyderabad": "Telugu",
            "Pune": "Marathi", "Mumbai": "Marathi", "Delhi": "Punjabi",
            "Kolkata": "Bengali", "Ahmedabad": "Gujarati",
        }.get(city, "Kannada")

    _patient_mobile_counter = itertools.count(7500000000)
    _staff_mobile_counter = itertools.count(9600000001)

    def _next_patient_mobile(self):
        return str(next(Command._patient_mobile_counter))

    def _next_staff_mobile(self):
        return str(next(Command._staff_mobile_counter))
