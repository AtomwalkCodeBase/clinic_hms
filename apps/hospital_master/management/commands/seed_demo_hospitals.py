"""Seed ten demo hospitals, each with a branch, the usual departments, a hospital admin and 12 doctors (one per
department) who have a profile, a place of work and a weekly schedule, so every hospital is bookable from the
patient app. Idempotent: re-running only creates what is missing, and never touches a hospital's other data.

    python manage.py seed_demo_hospitals               # all ten
    python manage.py seed_demo_hospitals --limit 2     # first two only
    python manage.py seed_demo_hospitals --dry-run     # print the plan, change nothing

A hospital that does not exist yet is provisioned the same way `provision_hospital` does it (Hospital row,
parameters, enterprise subscription, its own Postgres database, migrations). Logins are the mobile number
printed at the end + DEMO_PASSWORD."""
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

DEMO_PASSWORD = "demo@123"

# (hospital_code, name, city, state, pincode, base consultation fee)
HOSPITALS = [
    ("sunrise-hospital", "Sunrise Multispeciality Hospital", "Bengaluru", "Karnataka", "560034", 600),
    ("lotus-care-hospital", "Lotus Care Hospital", "Hyderabad", "Telangana", "500034", 550),
    ("apex-medical-centre", "Apex Medical Centre", "Mumbai", "Maharashtra", "400050", 800),
    ("greenleaf-hospital", "Greenleaf Hospital", "Chennai", "Tamil Nadu", "600020", 500),
    ("riverside-hospital", "Riverside Clinic & Hospital", "Pune", "Maharashtra", "411001", 500),
    ("harmony-health", "Harmony Health Institute", "Kolkata", "West Bengal", "700019", 450),
    ("silverline-hospital", "Silverline Hospital", "Delhi", "Delhi", "110024", 750),
    ("pearl-city-hospital", "Pearl City Hospital", "Ahmedabad", "Gujarat", "380015", 450),
    ("coastal-care", "Coastal Care Hospital", "Kochi", "Kerala", "682016", 500),
    ("evergreen-medicity", "Evergreen Medicity", "Bhubaneswar", "Odisha", "751010", 400),
]

# One doctor per department: (department, specialisation, qualification, fee multiplier, known_for)
SPECIALITIES = [
    ("Paediatrics", "Paediatrics", "MBBS, MD (Paediatrics)", 1.0, "Newborn care and childhood vaccination"),
    ("General Medicine", "General Medicine", "MBBS, MD (General Medicine)", 0.8, "Fever, diabetes and blood pressure care"),
    ("Obstetrics & Gynaecology", "Obstetrics & Gynaecology", "MBBS, MS (OBG)", 1.2, "High-risk pregnancy and antenatal care"),
    ("Cardiology", "Cardiology", "MBBS, MD, DM (Cardiology)", 1.6, "Heart failure and preventive cardiology"),
    ("Orthopaedics", "Orthopaedics", "MBBS, MS (Orthopaedics)", 1.3, "Joint replacement and sports injuries"),
    ("Dermatology", "Dermatology", "MBBS, MD (Dermatology)", 1.1, "Skin allergies and paediatric dermatology"),
    ("ENT", "ENT", "MBBS, MS (ENT)", 1.0, "Sinus, ear and throat disorders"),
    ("Ophthalmology", "Ophthalmology", "MBBS, MS (Ophthalmology)", 1.0, "Cataract and paediatric eye care"),
    ("Neurology", "Neurology", "MBBS, MD, DM (Neurology)", 1.6, "Epilepsy and headache disorders"),
    ("Gastroenterology", "Gastroenterology", "MBBS, MD, DM (Gastroenterology)", 1.5, "Liver and digestive disorders"),
    ("Pulmonology", "Pulmonology", "MBBS, MD (Pulmonary Medicine)", 1.3, "Asthma and chest infections"),
    ("Psychiatry", "Psychiatry", "MBBS, MD (Psychiatry)", 1.2, "Child and adolescent mental health"),
]

FIRST_F = ["Ananya", "Kavya", "Priya", "Meera", "Divya", "Lakshmi", "Sneha", "Radhika", "Nisha", "Pooja",
           "Aishwarya", "Shruti", "Neha", "Swati", "Anjali", "Deepa", "Rekha", "Sunita", "Tanvi", "Ishita"]
FIRST_M = ["Rohan", "Suresh", "Arjun", "Vikram", "Karthik", "Rahul", "Sanjay", "Amit", "Naveen", "Prakash",
           "Manoj", "Rajesh", "Harish", "Gaurav", "Siddharth", "Varun", "Anil", "Mohan", "Ashok", "Pranav"]
LAST = ["Rao", "Mehta", "Reddy", "Naidu", "Nair", "Iyer", "Sharma", "Gupta", "Kulkarni", "Patil",
        "Menon", "Shetty", "Banerjee", "Chatterjee", "Desai", "Joshi", "Pillai", "Das", "Kapoor", "Bhat",
        "Singh", "Verma", "Agarwal", "Kumar", "Hegde", "Mishra", "Panda", "Thomas", "Fernandes", "Saxena"]
LANGUAGES = ["English, Hindi", "English, Kannada, Hindi", "English, Telugu, Hindi", "English, Tamil",
             "English, Marathi, Hindi", "English, Bengali, Hindi", "English, Malayalam", "English, Gujarati, Hindi"]
FLOORS = [("Ground", 0), ("First Floor", 1), ("Second Floor", 2)]
COUNCILS = ["Karnataka Medical Council", "Telangana Medical Council", "Maharashtra Medical Council", "Tamil Nadu Medical Council",
            "West Bengal Medical Council", "Delhi Medical Council", "Gujarat Medical Council", "Kerala State Medical Council",
            "Odisha Council of Medical Registration"]
# (start, end) windows Monday to Saturday; the pattern depends on the doctor so the rota is not identical
SHIFTS = [[("09:00", "13:00"), ("16:00", "19:00")], [("10:00", "14:00")], [("09:00", "12:30"), ("15:00", "17:30")], [("14:00", "20:00")]]


def _doctor(h, d):
    """Deterministic profile of the d-th (0-based) doctor of the h-th (0-based) hospital."""
    idx = h * 12 + d
    female = (idx % 2 == 0)
    first = (FIRST_F if female else FIRST_M)[(idx // 2) % 20]
    last = LAST[(idx * 7 + idx // 30) % len(LAST)]
    dept, spec, qual, mult, known = SPECIALITIES[d]
    base = HOSPITALS[h][5]
    fee = int(round(base * mult / 50.0)) * 50
    return {
        "first_name": first, "last_name": last, "gender": "F" if female else "M",
        "phone": f"97{h + 1:02d}00{d + 1:04d}",
        "department": dept, "specialisation": spec, "qualification": qual,
        "experience_years": 6 + (idx * 5) % 22,
        "consultation_fee": Decimal(fee), "followup_fee": Decimal(int(fee * 0.6 // 50 * 50) or 100),
        "known_for": known, "languages": LANGUAGES[idx % len(LANGUAGES)],
        "council_name": COUNCILS[h % len(COUNCILS)], "registration_no": f"REG{h + 1:02d}{d + 1:02d}{10000 + idx * 37}",
        "bio": f"Dr. {first} {last} is a {spec.lower()} specialist with {6 + (idx * 5) % 22} years of experience, known for {known.lower()}.",
        "shift": SHIFTS[idx % len(SHIFTS)], "slot": (15, 20, 30)[idx % 3],
    }


class Command(BaseCommand):
    help = "Seed 10 demo hospitals with 12 doctors each (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=len(HOSPITALS), help="Seed only the first N hospitals")
        parser.add_argument("--dry-run", action="store_true", help="Print what would be created and change nothing")

    def handle(self, *args, **options):
        limit = max(1, min(options["limit"], len(HOSPITALS)))
        if options["dry_run"]:
            for h in range(limit):
                code, name, city = HOSPITALS[h][:3]
                self.stdout.write(f"{name} [{code}] {city}: admin 97{h + 1:02d}000000, doctors 97{h + 1:02d}000001..12")
            self.stdout.write("Dry run: nothing changed.")
            return

        summary = []
        for h in range(limit):
            summary.append(self._seed_hospital(h))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Done. {limit} hospital(s). Password for every login below: {DEMO_PASSWORD}"))
        for name, code, admin, created in summary:
            self.stdout.write(f"  {name} [{code}]  admin mobile {admin}  ({created} new doctor(s))")
        self.stdout.write("  Doctor mobiles: 97<hospital 01-10>00<doctor 0001-0012>, e.g. 9701000001.")

    # ── one hospital ─────────────────────────────────────────────────────────
    def _seed_hospital(self, h):
        code, name, city, state, pincode, _fee = HOSPITALS[h]
        self.stdout.write(f"\n== {name} ({city})")
        hospital, db_name = self._hospital(code, name, city, state)
        branch = self._branch(db_name, name, city, state, pincode, h)
        places = self._places(db_name, branch)
        admin_phone = self._admin(hospital, db_name, h, code)

        created = 0
        for d in range(12):
            if self._doctor_staff(hospital, db_name, branch, places, h, d, code):
                created += 1
        self.stdout.write(self.style.SUCCESS(f"   {created} doctor(s) created, {12 - created} already there"))
        return name, code, admin_phone, created

    def _hospital(self, code, name, city, state):
        """Get or create the hospital, its subscription and its database. Every step is skipped when already done, so a run that
        stopped half way (the hospital row exists but not its database) is finished by running the command again."""
        from apps.hospital_master.models import Hospital, Subscription
        from apps.hospital_master.services import TIER_FEATURE_DEFAULTS, parameters_of

        hospital = Hospital.objects.using("default").filter(hospital_code=code).first()
        if hospital is None:
            db_name = "aw_" + code.replace("-", "_").lower()
            if Hospital.objects.using("default").filter(db_name=db_name).exists():
                raise CommandError(f"db_name '{db_name}' is already used by another hospital.")
            hospital = Hospital.objects.using("default").create(
                hospital_code=code, name=name, db_name=db_name, city=city, state=state, is_active=True)
            self.stdout.write("   hospital record created")
        parameters_of(hospital)
        if not Subscription.objects.using("default").filter(hospital=hospital).exists():
            Subscription.objects.using("default").create(
                hospital=hospital, license_tier="enterprise", status="active", **TIER_FEATURE_DEFAULTS["enterprise"])
            self.stdout.write("   enterprise subscription created")
        self._database(hospital.db_name)
        return hospital, hospital.db_name

    def _database(self, db_name):
        from apps.hospital_master.services import create_hospital_database, ensure_hospital_db, run_hospital_migrations
        from apps.hospital_setup.models import Role

        ensure_hospital_db(db_name)
        try:
            Role.objects.using(db_name).exists()
            self.stdout.write(f"   database {db_name} ready")
            return
        except Exception:
            pass
        try:
            create_hospital_database(db_name)
        except Exception as exc:
            self.stdout.write(f"   (database not created, assuming it exists: {str(exc)[:80]})")
        try:
            run_hospital_migrations(db_name)
        except Exception as exc:
            raise CommandError(f"Could not set up database {db_name}: {exc}")
        self.stdout.write(f"   database {db_name} created and migrated")

    def _branch(self, db_name, name, city, state, pincode, h):
        from apps.hospital_setup.models import Branch

        branch = Branch.objects.using(db_name).filter(is_active=True).order_by("id").first()
        if branch is not None:
            return branch
        return Branch.objects.using(db_name).create(
            name="Main Campus", address=f"{10 + h} Hospital Road, {city}", city=city, state=state, pincode=pincode,
            phone=f"080{h + 1:02d}0000{h + 1:02d}"[:12])

    def _places(self, db_name, branch):
        """{department name: BranchDepartment} for all twelve departments, spread over three floors."""
        from apps.hospital_setup.models import BranchDepartment, Department, Floor

        floors = [Floor.objects.using(db_name).get_or_create(branch=branch, name=n, defaults={"level": lv})[0] for n, lv in FLOORS]
        places = {}
        for i, (dept_name, *_rest) in enumerate(SPECIALITIES):
            dept, _ = Department.objects.using(db_name).get_or_create(name=dept_name)
            place, _ = BranchDepartment.objects.using(db_name).get_or_create(
                branch=branch, department=dept, defaults={"floor": floors[i % 3], "is_active": True})
            places[dept_name] = place
        return places

    def _staff(self, hospital, db_name, phone, email, first, last, role, extra):
        from apps.hospital_setup.rbac import system_role
        from apps.hospital_setup.models import StaffUser
        from apps.hospital_setup.staff_services import next_employee_id
        from apps.patients.models import StaffMobileIndex

        staff = StaffUser.objects.using(db_name).filter(phone=phone).first()
        created = staff is None
        if created:
            staff = StaffUser(
                phone=phone, email=email, first_name=first, last_name=last, group=system_role(db_name, role),
                employee_id=next_employee_id(db_name), must_change_password=False, **extra)
            staff.set_password(DEMO_PASSWORD)
            staff.save(using=db_name)
        # also for a member made by an earlier run that stopped before this row was written: login finds the hospital through it
        StaffMobileIndex.objects.using("default").update_or_create(
            mobile=phone, defaults={"hospital_id": hospital.id, "email": staff.email})
        return staff, created

    def _admin(self, hospital, db_name, h, code):
        phone = f"97{h + 1:02d}000000"
        self._staff(hospital, db_name, phone, f"admin@{code}.demo", "Hospital", "Admin", "hospital_admin", {})
        return phone

    def _doctor_staff(self, hospital, db_name, branch, places, h, d, code):
        from apps.hospital_setup.models import DoctorSchedule, StaffBranchDepartment

        p = _doctor(h, d)
        email = f"{p['first_name']}.{p['last_name']}.{h + 1:02d}{d + 1:02d}@{code}.demo".lower()
        staff, created = self._staff(
            hospital, db_name, p["phone"], email, p["first_name"], p["last_name"], "doctor",
            {k: p[k] for k in ("gender", "registration_no", "council_name", "qualification", "experience_years", "specialisation",
                               "consultation_fee", "followup_fee", "known_for", "languages", "bio")})
        link, _ = StaffBranchDepartment.objects.using(db_name).get_or_create(
            staff=staff, branch_department=places[p["department"]], defaults={"is_primary": True})
        weekly = [{"day_of_week": day, "start_time": s, "end_time": e, "is_active": True}
                  for day in range(6) for s, e in p["shift"]]
        DoctorSchedule.objects.using(db_name).get_or_create(
            staff_branch_department=link, defaults={"slot_duration_minutes": p["slot"], "weekly_hours": weekly})
        return created
