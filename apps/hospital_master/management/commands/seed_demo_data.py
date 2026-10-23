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

# Aarav's demo health history (birth record, clinical events, growth and immunisations) — no source
# MedicalDocument/files, these are the clinical rows the Health Journey / Insights Timeline reads directly.
DEPENDENT_BIRTH_HISTORY = {
    "gestational_age_weeks": 36, "birth_weight_kg": "2.500", "nicu_admission": False, "source": "EXTRACTED",
}
# (event_date, condition_text, icd10, condition_group, category, severity)
DEPENDENT_CLINICAL_EVENTS = [
    ("2010-10-29", "Neonatal jaundice", "P59.9", "NEONATAL_JAUNDICE", "ACUTE", "CRITICAL"),
    ("2012-06-18", "Simple febrile seizure", "R56.0", "FEBRILE_SEIZURE", "ACUTE", "NORMAL"),
    ("2012-12-05", "Wheeze-associated lower respiratory tract infection (WALRI)", "R06.2", "WHEEZE", "ACUTE", "NORMAL"),
    ("2013-01-28", "Community acquired pneumonia, right lower lobe", "J18.9", "PNEUMONIA", "ACUTE", "CRITICAL"),
    ("2013-03-19", "Wheeze-associated lower respiratory tract infection (WALRI)", "R06.2", "WHEEZE", "ACUTE", "NORMAL"),
    ("2013-08-27", "Wheeze-associated lower respiratory tract infection (WALRI)", "R06.2", "WHEEZE", "ACUTE", "NORMAL"),
    ("2013-11-10", "Community acquired pneumonia, left lower lobe", "J18.9", "PNEUMONIA", "ACUTE", "CRITICAL"),
    ("2014-06-09", "Hand, foot and mouth disease", "B08.4", "HFMD", "ACUTE", "NORMAL"),
    ("2016-08-11", "Bronchial asthma", "J45.909", "ASTHMA", "CHRONIC", "NORMAL"),
    ("2016-08-11", "Atopic dermatitis", "L20.9", "ATOPIC_DERMATITIS", "CHRONIC", "NORMAL"),
    ("2019-03-14", "Enteric fever (typhoid fever)", "A01.0", "TYPHOID", "ACUTE", "NORMAL"),
    ("2019-09-23", "Dengue fever with warning signs and thrombocytopenia", "A97.1", "DENGUE", "ACUTE", "ABNORMAL"),
    ("2021-12-04", "Fracture of the distal end of the left radius", "S52.5", "INJURY", "ACUTE", "NORMAL"),
    ("2021-12-07", "Fracture of the distal end of the left radius", "S52.5", "INJURY", "ACUTE", "ABNORMAL"),
    ("2025-11-18", "Acute upper respiratory tract infection (URTI)", "J06.9", "URTI", "ACUTE", "NORMAL"),
    ("2026-03-02", "Acute gastroenteritis", "A09", "GASTROENTERITIS", "ACUTE", "NORMAL"),
    ("2026-09-22", "bronchial asthma", "J45.909", "ASTHMA", "CHRONIC", "NORMAL"),
    ("2026-09-22", "iron deficiency anaemia", "D50.9", "ICD_D50", "ACUTE", "NORMAL"),
]
# (measured_on, weight_kg, height_cm, head_circumference_cm)
DEPENDENT_GROWTH = [
    ("2010-10-25", "2.500", "46.0", "32.5"), ("2010-10-28", "3.000", None, None), ("2010-10-29", "2.400", None, None),
    ("2010-12-06", "3.800", "53.0", "36.6"), ("2011-01-25", "5.300", "60.0", "40.0"), ("2011-04-25", "7.600", "67.0", "43.5"),
    ("2011-07-25", "8.900", "72.0", "45.2"), ("2011-10-25", "9.800", "75.0", "46.3"), ("2012-04-25", "11.200", "81.0", "47.4"),
    ("2012-06-18", "11.600", "83.0", "47.6"), ("2012-10-25", "12.500", "87.0", "48.2"), ("2012-12-05", "12.700", "88.0", "48.3"),
    ("2013-01-22", "13.000", None, None), ("2013-01-28", "12.200", None, None), ("2013-03-19", "13.300", "91.0", "48.6"),
    ("2013-08-27", "14.300", "95.0", "49.0"), ("2013-11-10", "14.700", None, None), ("2013-11-16", "14.000", None, None),
    ("2014-06-09", "15.800", "100.0", "49.6"), ("2016-08-11", "20.400", "115.0", None), ("2017-01-12", "21.400", "117.0", None),
    ("2019-03-14", "27.200", "130.0", None), ("2019-12-10", "29.400", "134.0", None), ("2021-12-04", "36.000", "144.0", None),
    ("2021-12-05", "36.100", None, None), ("2022-12-14", "41.300", "151.0", None), ("2025-11-18", "58.200", "169.0", None),
    ("2026-03-02", "59.100", "170.0", None), ("2026-09-22", "60.700", "171.0", None),
]
# (vaccine_name, administered_date)
DEPENDENT_IMMUNIZATIONS = [
    ("Hepatitis B", "2010-10-29"), ("BCG", "2010-10-29"), ("OPV 0 (oral polio)", "2010-10-29"),
    ("BCG, OPV 0 and hepatitis B vaccine", "2010-11-05"), ("Rotavirus (Rotavac)", "2010-12-06"),
    ("Pentavalent (DTwP, Hib, Hep B)", "2010-12-06"), ("IPV", "2010-12-06"), ("PCV", "2010-12-06"),
    ("Rotavirus (Rotavac)", "2011-01-04"), ("Pentavalent (DTwP, Hib, Hep B)", "2011-01-04"), ("IPV", "2011-01-04"),
    ("PCV", "2011-01-04"), ("PCV", "2011-02-01"), ("Pentavalent (DTwP, Hib, Hep B)", "2011-02-01"), ("IPV", "2011-02-01"),
    ("Rotavirus (Rotavac)", "2011-02-01"), ("Typhoid conjugate vaccine (TCV)", "2011-04-26"), ("MMR", "2011-07-26"),
    ("Hepatitis A", "2011-10-28"), ("Varicella", "2012-01-25"), ("MMR", "2012-01-25"), ("PCV booster", "2012-01-25"),
    ("IPV booster", "2012-02-27"), ("DTwP booster", "2012-02-27"), ("Hib booster", "2012-02-27"),
    ("Hepatitis A", "2012-04-25"), ("Influenza (annual)", "2013-10-14"), ("Varicella", "2014-10-28"),
    ("IPV booster", "2014-10-28"), ("MMR", "2014-10-28"), ("DTwP booster", "2014-10-28"),
    ("Influenza (annual)", "2019-10-14"), ("Influenza (annual)", "2020-10-12"), ("Tdap", "2020-11-02"),
]


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
        self._dependent_history(dependent)

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

    # ── dependent's demo health history (drives the Health Journey / Insights Timeline) ──
    def _dependent_history(self, dependent):
        from decimal import Decimal
        from apps.patients.models import Patient
        from apps.documents.models import BirthHistory, ClinicalEvent, ImmunizationRecord
        from apps.documents.lib_vitals import GrowthMeasurement
        from apps.documents.lib_processing import rebuild_patient

        patient = Patient.objects.using("default").get(awpid=dependent["awpid"])

        BirthHistory.objects.using("default").get_or_create(
            patient=patient, defaults={
                "gestational_age_weeks": DEPENDENT_BIRTH_HISTORY["gestational_age_weeks"],
                "birth_weight_kg": Decimal(DEPENDENT_BIRTH_HISTORY["birth_weight_kg"]),
                "nicu_admission": DEPENDENT_BIRTH_HISTORY["nicu_admission"],
                "source": DEPENDENT_BIRTH_HISTORY["source"],
            })

        for event_date, text, icd10, group, category, severity in DEPENDENT_CLINICAL_EVENTS:
            qs = ClinicalEvent.objects.using("default").filter(
                patient=patient, event_date=event_date, icd10=icd10, event_type="DIAGNOSIS")
            if not qs.exists():
                ClinicalEvent.objects.using("default").create(
                    patient=patient, event_date=event_date, icd10=icd10, event_type="DIAGNOSIS",
                    condition_text=text, condition_group=group, category=category,
                    severity=severity, clinical_status="active", source="EXTRACTED")

        for measured_on, weight, height, head in DEPENDENT_GROWTH:
            qs = GrowthMeasurement.objects.using("default").filter(
                patient=patient, measured_on=measured_on, source_id=None)
            if not qs.exists():
                GrowthMeasurement.objects.using("default").create(
                    patient=patient, measured_on=measured_on,
                    weight_kg=Decimal(weight) if weight else None,
                    height_cm=Decimal(height) if height else None,
                    head_circumference_cm=Decimal(head) if head else None, source="extracted")

        for vaccine_name, administered_date in DEPENDENT_IMMUNIZATIONS:
            qs = ImmunizationRecord.objects.using("default").filter(
                patient=patient, vaccine_name=vaccine_name, administered_date=administered_date)
            if not qs.exists():
                ImmunizationRecord.objects.using("default").create(
                    patient=patient, vaccine_name=vaccine_name, administered_date=administered_date,
                    verification_status="pending_review", source="extracted")

        rebuild_patient(patient.pk)

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
