"""
Management command: seed_sparsh_demo

Seeds a curated, demo-ready staff roster into an ALREADY-PROVISIONED
hospital tenant (default target: db_name="aw_sparsh_hospital") — unlike
seed_full_demo (which spins up brand-new hospitals), this adds staff to a
hospital that already exists.

Creates:
  - 5 doctors  (General Medicine, Cardiology, Pediatrics, Orthopedics, General Surgery)
  - 2 nurses   (General Ward, ICU / Emergency)
  - 1 front desk
  - 1 pharmacist
  - 1 lab technician

Every field on StaffUser / DoctorProfile / StaffProfile is filled in —
mandatory AND optional (registration numbers, council names, bios,
languages, "known for", follow-up fee, gender, date of birth, a generated
digital signature, and — network permitting — a gender-matched profile
photo) — not just what the admin invite form requires.

Also prints the tenant's live `subdomain` ("Hospital Code") value straight
from the registry DB, so this doubles as a direct, first-hand answer to
"why isn't my hospital code showing" instead of a guess.

Idempotent: a staff member already present (matched by phone) is skipped,
not duplicated, so this is safe to re-run.

Usage:
  python manage.py seed_sparsh_demo
  python manage.py seed_sparsh_demo --db-name aw_sparsh_hospital
  python manage.py seed_sparsh_demo --no-photos      # skip Unsplash downloads
  python manage.py seed_sparsh_demo --password "Different@123"
"""

import base64
import io
import logging
import urllib.request
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.org.models import Branch, Department, StaffUser, DoctorProfile, StaffProfile
from apps.registry.models import StaffMobileIndex
from apps.tenants.models import Tenant
from apps.tenants.utils import _make_db_config
from core.db_router import _thread_local
from core.utils.nntm import get_next_number

logger = logging.getLogger(__name__)

DEFAULT_PASSWORD = "hms@1234"

# Same free-to-use Unsplash portraits already used by set_demo_doctor_photos —
# reused here so no new licensing question is introduced.
MALE_PHOTOS = [
    "https://images.unsplash.com/photo-1612349317150-e413f6a5b16d?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1612531386530-97286d97c2d2?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1730597842283-943c7986ee2c?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1612349316228-5942a9b489c2?crop=faces&fit=crop&w=400&h=400&q=80",
]
FEMALE_PHOTOS = [
    "https://images.unsplash.com/photo-1741707039536-113e200f9e0d?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1741275269731-83526786bb93?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1741707038935-0bf1f8eda81c?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1741707040287-7c0228b2fca7?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1749017818421-aadb344f32d8?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1741707039571-f1c3f957a2e8?crop=faces&fit=crop&w=400&h=400&q=80",
]

# ── The 5 doctors ────────────────────────────────────────────────────────
DOCTORS = [
    dict(first="Ananya", last="Rao", gender="F", phone="9900010001",
         dept="General Medicine", specialisation="General Medicine",
         qualification="MBBS, MD (General Medicine)", experience_years=8,
         consultation_fee=600, followup_fee=400,
         registration_no="KMC/2016/48210",
         known_for="Fever, Diabetes, Hypertension, General checkups",
         bio="Ananya focuses on everyday adult medicine — diabetes and hypertension "
             "management, fevers and infections, and general health checkups.",
         languages="English, Hindi, Kannada", dob=date(1988, 4, 12)),
    dict(first="Sudeep", last="K N", gender="M", phone="9900010002",
         dept="Cardiology", specialisation="Cardiology",
         qualification="MBBS, MD (Cardiology)", experience_years=12,
         consultation_fee=900, followup_fee=650,
         registration_no="KMC/2012/39044",
         known_for="Chest pain, Hypertension, Heart checkups, Angiography, Angioplasty",
         bio="Sudeep is an interventional cardiologist with 12 years of experience "
             "in coronary angiography and angioplasty, and long-term heart-failure care.",
         languages="English, Hindi, Kannada", dob=date(1984, 11, 2)),
    dict(first="Meera", last="Nair", gender="F", phone="9900010003",
         dept="Pediatrics", specialisation="Pediatrics",
         qualification="MBBS, DCH", experience_years=7,
         consultation_fee=500, followup_fee=350,
         registration_no="KMC/2017/51230",
         known_for="Child immunization, Growth concerns, Common infections",
         bio="Meera cares for infants through teenagers, with a special interest in "
             "immunization schedules and tracking healthy growth and development.",
         languages="English, Hindi, Kannada, Malayalam", dob=date(1990, 6, 18)),
    dict(first="Arjun", last="Reddy", gender="M", phone="9900010004",
         dept="Orthopedics", specialisation="Orthopedics",
         qualification="MBBS, MS (Orthopedics)", experience_years=10,
         consultation_fee=700, followup_fee=500,
         registration_no="KMC/2014/42117",
         known_for="Joint pain, Fractures, Back pain, Sports injuries",
         bio="Arjun treats fractures, joint pain and sports injuries, and performs "
             "both trauma and elective orthopedic surgery.",
         languages="English, Hindi, Kannada, Telugu", dob=date(1986, 1, 25)),
    dict(first="Priya", last="Menon", gender="F", phone="9900010005",
         dept="General Surgery", specialisation="General Surgery",
         qualification="MBBS, MS (General Surgery)", experience_years=9,
         consultation_fee=800, followup_fee=550,
         registration_no="KMC/2015/45509",
         known_for="Hernia, Gallbladder, Appendix, Minor & major surgical procedures",
         bio="Priya performs general and laparoscopic surgery, from day-care "
             "procedures to major abdominal surgery, and runs the surgical OPD.",
         languages="English, Hindi, Kannada, Malayalam", dob=date(1987, 9, 9)),
]

# ── 2 nurses ─────────────────────────────────────────────────────────────
NURSES = [
    dict(first="Kavya", last="Shetty", gender="F", phone="9900010006",
         dept="General Ward", qualification="B.Sc Nursing", experience_years=5,
         registration_no="KSNC/2019/22841", council_name="Karnataka State Nursing Council",
         registration_expiry=date(2028, 6, 30),
         bio="Kavya handles vitals, ward rounds and medication administration for "
             "general-ward inpatients, and coordinates day-to-day nursing care.",
         languages="English, Hindi, Kannada", dob=date(1996, 3, 14)),
    dict(first="Sneha", last="Kumari", gender="F", phone="9900010007",
         dept="ICU / Emergency", qualification="GNM", experience_years=4,
         registration_no="KSNC/2020/24518", council_name="Karnataka State Nursing Council",
         registration_expiry=date(2028, 11, 15),
         bio="Sneha works ICU and emergency shifts — critical-care vitals, triage "
             "support and close monitoring of unstable patients.",
         languages="English, Hindi, Kannada", dob=date(1997, 7, 22)),
]

# ── 1 front desk, 1 pharmacist, 1 lab tech ──────────────────────────────
FRONT_DESK = dict(
    first="Rahul", last="Kumar", gender="M", phone="9900010008", role="front_desk",
    dept=None, qualification="BBA (Hospital Administration)", experience_years=3,
    registration_no="", council_name="", registration_expiry=None,
    bio="Rahul runs front-desk operations — patient registration, appointment "
        "booking, check-in, queue management and billing initiation.",
    languages="English, Hindi, Kannada", dob=date(1996, 12, 5),
)
PHARMACIST = dict(
    first="Pooja", last="Iyer", gender="F", phone="9900010009", role="pharmacist",
    dept=None, qualification="B.Pharm", experience_years=6,
    registration_no="KSPC/2018/61829", council_name="Karnataka State Pharmacy Council",
    registration_expiry=date(2027, 3, 31),
    bio="Pooja handles prescription processing and dispensing, and manages "
        "pharmacy stock and batch/expiry tracking.",
    languages="English, Hindi, Kannada", dob=date(1994, 2, 17),
)
LAB_TECH = dict(
    first="Nithin", last="Raj", gender="M", phone="9900010010", role="lab_tech",
    dept=None, qualification="B.Sc Medical Laboratory Technology", experience_years=5,
    registration_no="IAMLS/KA/2019/3087", council_name="Indian Association of Medical Laboratory Scientists",
    registration_expiry=date(2027, 8, 31),
    bio="Nithin handles sample collection, lab order processing, result entry "
        "and report verification.",
    languages="English, Kannada, Hindi", dob=date(1995, 10, 30),
)


def _generate_signature_base64(full_name):
    """Render a plausible-looking signature PNG for digital_signature. Best
    effort — returns "" if Pillow / fonts aren't available rather than
    failing the whole seed run."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (420, 130), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        font = None
        for candidate in ("segoeui.ttf", "arial.ttf", "DejaVuSans-Oblique.ttf", "DejaVuSans.ttf"):
            try:
                font = ImageFont.truetype(candidate, 42)
                break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()
        draw.text((24, 38), full_name, font=font, fill=(25, 25, 95))
        draw.line([(24, 96), (396, 92)], fill=(25, 25, 95), width=2)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception as exc:
        logger.warning("Signature generation skipped for %s: %s", full_name, exc)
        return ""


def _download_photo_base64(url):
    """Best-effort download + base64-encode for StaffUser.photo. Returns ""
    on any failure (offline, blocked, timeout) — never raises."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
        return "data:image/jpeg;base64," + base64.b64encode(data).decode()
    except Exception as exc:
        logger.warning("Photo download skipped for %s: %s", url, exc)
        return ""


class Command(BaseCommand):
    help = "Seed a curated demo staff roster (5 doctors, 2 nurses, front desk, pharmacist, lab tech) into an already-provisioned tenant."

    def add_arguments(self, parser):
        parser.add_argument("--db-name", default="aw_sparsh_hospital",
                             help="Tenant db_name to seed (default: aw_sparsh_hospital).")
        parser.add_argument("--tenant-id", type=int, default=None,
                             help="Look up the tenant by id instead of --db-name.")
        parser.add_argument("--subdomain", default=None,
                             help="Look up the tenant by subdomain instead of --db-name.")
        parser.add_argument("--password", default=DEFAULT_PASSWORD,
                             help=f"Password to set for every seeded staff member (default: {DEFAULT_PASSWORD}).")
        parser.add_argument("--no-photos", action="store_true",
                             help="Skip downloading Unsplash profile photos (no network needed).")
        parser.add_argument("--reset-password", action="store_true",
                             help="If a staff member already exists (matched by phone), reset their password to --password instead of skipping them.")

    def handle(self, *args, **options):
        # ── Resolve the tenant, on the registry ("default") DB ──────────────
        qs = Tenant.objects.using("default")
        if options["tenant_id"]:
            tenant = qs.filter(pk=options["tenant_id"]).first()
        elif options["subdomain"]:
            tenant = qs.filter(subdomain=options["subdomain"]).first()
        else:
            tenant = qs.filter(db_name=options["db_name"]).first()
        if not tenant:
            raise CommandError(
                f"No tenant found (db_name={options['db_name']!r}, "
                f"tenant_id={options['tenant_id']!r}, subdomain={options['subdomain']!r}). "
                f"Check Settings → Database on the Hospital Admin's Settings page for the exact db_name."
            )

        db = tenant.db_name
        from django.conf import settings as dj_settings
        if db not in dj_settings.DATABASES:
            dj_settings.DATABASES[db] = _make_db_config(db)
        _thread_local.tenant_id = tenant.id
        _thread_local.db_alias = db

        self.stdout.write(self.style.MIGRATE_HEADING(f"\nTenant: {tenant.name}"))
        self.stdout.write(f"  id                = {tenant.id}")
        self.stdout.write(f"  db_name           = {tenant.db_name}")
        subdomain_display = tenant.subdomain or "<BLANK -- this is why Settings shows a dash>"
        self.stdout.write(f"  subdomain (Hospital Code) = {subdomain_display}")
        self.stdout.write(f"  is_active         = {tenant.is_active}")
        self.stdout.write(f"  fee_ownership     = {tenant.fee_ownership}")
        self.stdout.write("")

        branch = Branch.objects.using(db).filter(is_active=True).order_by("id").first()
        if not branch:
            raise CommandError(
                f"Tenant {tenant.name!r} ({db}) has no active Branch yet — create one from "
                f"Hospital Admin → Branches first, then re-run this command."
            )
        self.stdout.write(f"Seeding into branch: {branch.name} (id={branch.id})\n")

        password = options["password"]
        with_photos = not options["no_photos"]
        reset_password = options["reset_password"]
        email_domain = f"{tenant.subdomain}.demo" if tenant.subdomain else "sparsh-hospital.demo"

        dept_cache = {}

        def get_dept(name):
            if not name:
                return None
            if name not in dept_cache:
                dept, _ = Department.objects.using(db).get_or_create(
                    branch=branch, name=name, defaults={"is_active": True}
                )
                dept_cache[name] = dept
            return dept_cache[name]

        created, skipped = [], []
        photo_counters = {"M": 0, "F": 0}

        def next_employee_id():
            from apps.org.models import NextNumber
            NextNumber.objects.using(db).get_or_create(
                branch_id=0, entity="employee_id",
                defaults={"prefix": "EMP-", "pad_length": 6, "last_number": 0},
            )
            formatted_id, _ = get_next_number(0, "employee_id", using=db)
            return formatted_id

        def make_staff(first, last, gender, phone, role, dept_name, dob,
                        email_domain):
            full_name = f"{first} {last}"
            existing_staff = StaffUser.objects.using(db).filter(phone=phone).first()
            if existing_staff:
                if reset_password:
                    existing_staff.set_password(password)
                    existing_staff.must_change_password = False
                    existing_staff.save(using=db, update_fields=["password", "must_change_password"])
                    skipped.append(f"{full_name} ({phone}) — already existed, password reset to the new value")
                else:
                    skipped.append(f"{full_name} ({phone}) — already exists, skipped (pass --reset-password to update their password)")
                return None

            # This phone number's login is registered platform-wide (registry
            # DB), not just in this tenant — if it's claimed by a different
            # hospital, try the next few numbers in this same block rather
            # than aborting the whole run over one collision.
            original_phone = phone
            for attempt in range(10):
                existing_mobile = StaffMobileIndex.objects.using("default").filter(mobile=phone).first()
                if not existing_mobile:
                    break
                if existing_mobile.db_name == db:
                    break
                phone = str(int(original_phone) + 100 * (attempt + 1))
            else:
                skipped.append(f"{full_name} ({original_phone}) — mobile already registered at another hospital "
                                f"(tried {original_phone}..{phone}, all taken), skipped")
                return None
            if phone != original_phone:
                self.stdout.write(self.style.WARNING(
                    f"  Note: {original_phone} was already registered to another hospital — "
                    f"using {phone} for {full_name} instead."
                ))

            email = f"{first}.{last}".lower().replace(' ', '') + f"@{email_domain}"
            photo_url = ""
            photo_b64 = ""
            if with_photos:
                pool = MALE_PHOTOS if gender == "M" else FEMALE_PHOTOS
                idx = photo_counters[gender] % len(pool)
                photo_counters[gender] += 1
                photo_url = pool[idx]
                photo_b64 = _download_photo_base64(photo_url)

            with transaction.atomic(using=db):
                staff = StaffUser(
                    email=email,
                    first_name=first,
                    last_name=last,
                    role=role,
                    branch=branch,
                    department=get_dept(dept_name),
                    phone=phone,
                    employee_id=next_employee_id(),
                    date_of_birth=dob,
                    is_active=True,
                    must_change_password=False,   # demo creds should work immediately
                    photo=photo_b64,
                )
                staff.set_password(password)
                staff.save(using=db)

            StaffMobileIndex.objects.using("default").update_or_create(
                mobile=phone,
                defaults={"tenant_id": tenant.id, "db_name": db, "email": email},
            )
            staff._demo_photo_url = photo_url
            created.append((staff, role, photo_url))
            return staff

        # ── Doctors ──────────────────────────────────────────────────────
        for d in DOCTORS:
            staff = make_staff(d["first"], d["last"], d["gender"], d["phone"], "doctor",
                                d["dept"], d["dob"],
                                email_domain)
            if not staff:
                continue
            DoctorProfile.objects.using(db).create(
                staff=staff,
                registration_no=d["registration_no"],
                specialisation=d["specialisation"],
                qualification=d["qualification"],
                gender=d["gender"],
                experience_years=d["experience_years"],
                consultation_fee=d["consultation_fee"],
                followup_fee=d["followup_fee"],
                digital_signature=_generate_signature_base64(f"Dr. {d['first']} {d['last']}"),
                bio=d["bio"],
                photo_url=staff._demo_photo_url or "",
                languages=d["languages"],
                known_for=d["known_for"],
            )

        # ── Nurses ───────────────────────────────────────────────────────
        for n in NURSES:
            staff = make_staff(n["first"], n["last"], n["gender"], n["phone"], "nurse",
                                n["dept"], n["dob"],
                                email_domain)
            if not staff:
                continue
            StaffProfile.objects.using(db).create(
                staff=staff,
                registration_no=n["registration_no"],
                council_name=n["council_name"],
                registration_expiry=n["registration_expiry"],
                qualification=n["qualification"],
                experience_years=n["experience_years"],
                gender=n["gender"],
                bio=n["bio"],
                languages=n["languages"],
                extra={"ward": n["dept"]},
            )

        # ── Front desk / pharmacist / lab tech ──────────────────────────
        for o in [FRONT_DESK, PHARMACIST, LAB_TECH]:
            staff = make_staff(o["first"], o["last"], o["gender"], o["phone"], o["role"],
                                o["dept"], o["dob"],
                                email_domain)
            if not staff:
                continue
            StaffProfile.objects.using(db).create(
                staff=staff,
                registration_no=o["registration_no"],
                council_name=o["council_name"],
                registration_expiry=o["registration_expiry"],
                qualification=o["qualification"],
                experience_years=o["experience_years"],
                gender=o["gender"],
                bio=o["bio"],
                languages=o["languages"],
                extra={},
            )

        # ── Summary ──────────────────────────────────────────────────────
        self.stdout.write(self.style.SUCCESS(f"\n{len(created)} staff created, {len(skipped)} skipped.\n"))
        if created:
            self.stdout.write("Login credentials (mobile number + password — same password for everyone below):")
            self.stdout.write(f"  password = {password}\n")
            self.stdout.write(f"  {'Name':<20} {'Role':<12} {'Mobile':<12} {'Email'}")
            for staff, role, _ in created:
                self.stdout.write(f"  {staff.get_full_name():<20} {role:<12} {staff.phone:<12} {staff.email}")
        if skipped:
            self.stdout.write("\nSkipped (already present):")
            for line in skipped:
                self.stdout.write(f"  - {line}")
        self.stdout.write("")
