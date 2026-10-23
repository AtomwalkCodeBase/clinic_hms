"""Seed the fixed demo accounts used for manual testing: the hospital_admin/doctor/nurse/front_desk logins at
Novacare Hospital and Mahanandi Hospitals (mobile number + "demo@123"), and a patient persona — Ruchitha Gowda —
with a dependent, Aarav, registered at both hospitals. Idempotent: safe to re-run, only creates what's missing.

Assumes both hospital databases already exist (provisioned the normal way, e.g. `provision_hospital` or a
restored dev DB); this command does not create a hospital's Postgres database from scratch."""
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

DEMO_PASSWORD = "demo@123"

HOSPITALS = [
    {
        "hospital_code": "novacare-flagship", "name": "Novacare Hospital", "db_name": "aw_novacare_flagship",
        "city": "Bengaluru", "state": "Karnataka",
        "staff": [
            {"role": "hospital_admin", "first_name": "Radhika", "last_name": "Nambiar",
             "phone": "9600000001", "email": "radhika.admin@novacare-flagship.demo"},
            {"role": "doctor", "first_name": "Ananya", "last_name": "Rao",
             "phone": "9810011001", "email": "ananya.rao@novacare-hospital.demo"},
            {"role": "doctor", "first_name": "Rohan", "last_name": "Mehta",
             "phone": "9810011002", "email": "rohan.mehta@novacare-hospital.demo"},
            {"role": "nurse", "first_name": "Meena", "last_name": "Joseph",
             "phone": "9810011003", "email": "meena.joseph@novacare-hospital.demo"},
            {"role": "front_desk", "first_name": "Priya", "last_name": "Shetty",
             "phone": "9810011004", "email": "priya.shetty@novacare-hospital.demo"},
        ],
    },
    {
        "hospital_code": "mahanandi-hospitals", "name": "Mahanandi Hospitals", "db_name": "aw_mahanandi_hospitals",
        "city": "Bengaluru", "state": "Karnataka",
        "staff": [
            {"role": "hospital_admin", "first_name": "Hospital", "last_name": "Admin",
             "phone": "9000000009", "email": "ruchitha@atomwalk.com"},
            {"role": "doctor", "first_name": "Kavya", "last_name": "Reddy",
             "phone": "9820022001", "email": "kavya.reddy@mahanandi-hospitals.demo"},
            {"role": "doctor", "first_name": "Suresh", "last_name": "Naidu",
             "phone": "9820022002", "email": "suresh.naidu@mahanandi-hospitals.demo"},
            {"role": "nurse", "first_name": "Lakshmi", "last_name": "Gowda",
             "phone": "9820022003", "email": "lakshmi.gowda@mahanandi-hospitals.demo"},
            {"role": "front_desk", "first_name": "Harish", "last_name": "Kumar",
             "phone": "9820022004", "email": "harish.kumar@mahanandi-hospitals.demo"},
        ],
    },
]

GUARDIAN = {"full_name": "Ruchitha Gowda", "email": "rnd@atomwalk.com", "mobile": "9000030000",
            "gender": "female", "date_of_birth": date(2003, 10, 25)}
DEPENDENT = {"full_name": "Aarav", "date_of_birth": date(2010, 10, 25), "gender": "M", "relationship": "child"}


class Command(BaseCommand):
    help = "Seed the fixed demo hospital staff logins and the Ruchitha/Aarav patient persona (idempotent)."

    def handle(self, *args, **options):
        for h in HOSPITALS:
            hospital = self._hospital(h)
            branch = self._branch(h["db_name"])
            for s in h["staff"]:
                self._staff(hospital, h["db_name"], branch, s)

        guardian = self._guardian()
        dependent = self._dependent(guardian)
        for h in HOSPITALS:
            self._register_at_hospital(h["db_name"], guardian["awpid"])
            self._register_at_hospital(h["db_name"], dependent["awpid"])

        self.stdout.write(self.style.SUCCESS(
            "Demo data ready: Novacare + Mahanandi staff logins (mobile + demo@123), "
            f"guardian {guardian['awpid']} and dependent {dependent['awpid']}."
        ))

    # ── hospitals ────────────────────────────────────────────────────────────
    def _hospital(self, h):
        from apps.hospital_master.models import Hospital
        from apps.hospital_master.services import ensure_hospital_db

        hospital = Hospital.objects.filter(hospital_code=h["hospital_code"]).first()
        if hospital is None:
            raise CommandError(
                f"Hospital '{h['hospital_code']}' not found and this command does not provision a new "
                f"hospital database. Run `provision_hospital` first, or restore the dev database.")
        ensure_hospital_db(h["db_name"])
        return hospital

    def _branch(self, db_name):
        from apps.hospital_setup.models import Branch
        branch = Branch.objects.using(db_name).filter(is_active=True).order_by("id").first()
        if branch is None:
            raise CommandError(f"{db_name} has no active branch set up yet.")
        return branch

    # ── staff ────────────────────────────────────────────────────────────────
    def _staff(self, hospital, db_name, branch, s):
        from apps.patients.models import StaffMobileIndex
        from apps.hospital_setup.branch_utils import ensure_default_place
        from apps.hospital_setup.models import StaffBranchDepartment, StaffUser
        from apps.hospital_setup.rbac import system_role
        from apps.hospital_setup.staff_services import next_employee_id

        staff = StaffUser.objects.using(db_name).filter(phone=s["phone"]).first()
        if staff is not None:
            if not staff.check_password(DEMO_PASSWORD):
                staff.set_password(DEMO_PASSWORD)
                staff.must_change_password = False
                staff.save(using=db_name, update_fields=["password", "must_change_password", "updated_at"])
            return staff

        staff = StaffUser(
            phone=s["phone"], email=s["email"], first_name=s["first_name"], last_name=s["last_name"],
            employee_id=next_employee_id(db_name), group=system_role(db_name, s["role"]),
            must_change_password=False,
        )
        staff.set_password(DEMO_PASSWORD)
        staff.save(using=db_name)

        StaffMobileIndex.objects.using("default").update_or_create(
            mobile=s["phone"], defaults={"hospital_id": hospital.id})

        if s["role"] != "hospital_admin":
            place = ensure_default_place(db_name, branch)
            StaffBranchDepartment.objects.using(db_name).get_or_create(
                staff=staff, branch_department=place, defaults={"is_primary": True})
        return staff

    # ── patient + dependent ─────────────────────────────────────────────────
    def _guardian(self):
        from apps.patients.models import Patient
        from apps.patients.services import set_password

        acct = Patient.objects.using("default").filter(email__iexact=GUARDIAN["email"]).first()
        if acct is not None:
            if not acct.password:
                set_password(acct, DEMO_PASSWORD)
                acct.save(using="default", update_fields=["password"])
            return {"awpid": acct.awpid, "record": acct}

        from core.utils.awpid import generate_unique_awpid
        acct = Patient(
            awpid=generate_unique_awpid(), full_name=GUARDIAN["full_name"], email=GUARDIAN["email"],
            mobile=GUARDIAN["mobile"], gender=GUARDIAN["gender"], date_of_birth=GUARDIAN["date_of_birth"],
            is_dependent=False,
        )
        set_password(acct, DEMO_PASSWORD)
        acct.save(using="default")
        return {"awpid": acct.awpid, "record": acct}

    def _dependent(self, guardian):
        from apps.patients.models import Patient, PatientRelationship

        existing = PatientRelationship.objects.using("default").select_related("dependent").filter(
            guardian__awpid=guardian["awpid"], dependent__full_name=DEPENDENT["full_name"]).first()
        if existing is not None:
            return {"awpid": existing.dependent.awpid}

        from apps.opd.patient_services import PatientService
        member = PatientService.add_family_member(
            guardian_awpid=guardian["awpid"], guardian_mobile=guardian["record"].mobile,
            data={"full_name": DEPENDENT["full_name"], "date_of_birth": str(DEPENDENT["date_of_birth"]),
                  "gender": DEPENDENT["gender"], "relationship": DEPENDENT["relationship"]})
        return {"awpid": member["awpid"]}

    def _register_at_hospital(self, db_name, awpid):
        from apps.opd.models import HospitalPatient

        if HospitalPatient.objects.using(db_name).filter(awpid=awpid).exists():
            return

        from apps.hospital_setup.compliance_services import record_consent
        from apps.hospital_setup.models import ConsentRecord
        from core.utils.nntm import get_next_number

        branch = self._branch(db_name)
        uhid, _ = get_next_number(branch_id=branch.id, entity="uhid", using=db_name)
        patient = HospitalPatient.objects.using(db_name).create(
            awpid=awpid, uhid=uhid, hie_consent_given=True, hie_consent_at=timezone.now(),
            dpdp_consent_captured=True, dpdp_consent_at=timezone.now(),
        )
        record_consent(db_name, patient, ConsentRecord.CONSENT_DPDP_PROCESSING, ConsentRecord.SOURCE_PORTAL)
        record_consent(db_name, patient, ConsentRecord.CONSENT_HIE_SHARING, ConsentRecord.SOURCE_PORTAL, granted=True)
