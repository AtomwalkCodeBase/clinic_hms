"""
Management command: seed_recent_hospitals_staff

Fills out the hospitals that were provisioned recently with a real
per-tenant database but little or no staff yet:

    Abhaya Clinic, Sunrise Clinic, Manipal Hospital, Kaveri Hospital,
    Brookefield Hospitals, Mahanandi Hospitals, Care & Cure Clinic,
    Krishna Healthcare, Nationwide Family Doctors, Sri Lakshmi Family
    Dental Clinic, Pushpa Nursing Home

The last 5 only got a real database via provision_pending_hospital_dbs
(apps/tenants/management/commands) — before that they were registry-only
"hospitals near me" listing rows with no staff possible at all.

For each hospital this creates (idempotent — matched by phone, so safe to
re-run):
  - An active Branch, if the tenant doesn't already have one.
  - 4 doctors (3 at Kaveri, which already has one General Physician):
      1. Pediatrics          — works Mon + Wed
      2. General Physician   — works Thu + Fri
      3. a "no weekends" specialisation (Mon-Fri)
      4. a "weekends only" specialisation (Sat + Sun)
    Every doctor ALSO gets Monday added/overridden to a full working day
    (08:00-20:00) regardless of their normal pattern, per the demo
    requirement that every doctor at every hospital is bookable on Monday.
  - 1 nurse, 1 front desk, 1 lab technician, 1 pharmacist (skipped at
    Kaveri, which already has a nurse).
  - Every field on StaffUser / DoctorProfile / StaffProfile is filled in,
    not just what the admin invite form requires (registration numbers,
    council names, bios, languages, known-for, follow-up fee, gender,
    date of birth, a generated digital signature, and a best-effort
    profile photo).

Also patches Kaveri's pre-existing doctor (Prashant Sharma) so Monday is a
full working day for him too, and bumps Brookefield's starter-tier
Subscription doctor/staff caps (it was provisioned at 3/5, which the new
roster below exceeds) so nothing in the UI trips over the new headcount.

Usage:
  python manage.py seed_recent_hospitals_staff --settings=atomwalk.settings.development
  python manage.py seed_recent_hospitals_staff --no-photos
  python manage.py seed_recent_hospitals_staff --password "Different@123"
"""

import base64
import io
import logging
import urllib.request
from datetime import date, time as dtime

from django.conf import settings as dj_settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.org.models import Branch, Department, StaffUser, DoctorProfile, StaffProfile, DoctorSchedule, DoctorAvailabilitySlot
from apps.registry.models import StaffMobileIndex
from apps.tenants.models import Tenant, Subscription
from apps.tenants.utils import _make_db_config
from core.utils.nntm import get_next_number

logger = logging.getLogger(__name__)

DEFAULT_PASSWORD = "Hms@1234"
STARTING_MOBILE = 9810000001

MALE_PHOTOS = [
    "https://images.unsplash.com/photo-1612349317150-e413f6a5b16d?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1612531386530-97286d97c2d2?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1730597842283-943c7986ee2c?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1612349316228-5942a9b489c2?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1612276529731-4b21494e6d71?crop=faces&fit=crop&w=400&h=400&q=80",
]
FEMALE_PHOTOS = [
    "https://images.unsplash.com/photo-1741707039536-113e200f9e0d?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1741275269731-83526786bb93?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1741707038935-0bf1f8eda81c?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1741707040287-7c0228b2fca7?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1749017818421-aadb344f32d8?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1741707039571-f1c3f957a2e8?crop=faces&fit=crop&w=400&h=400&q=80",
]

MONDAY_FULL_DAY = (dtime(8, 0), dtime(20, 0))

# day_of_week: 0=Mon 1=Tue 2=Wed 3=Thu 4=Fri 5=Sat 6=Sun
# Each pattern lists (day, start, end) for the doctor's own working days.
# Monday is injected/overridden separately by _build_schedule so it's
# always MONDAY_FULL_DAY and always is_available=True.
SLOT_PATTERNS = {
    "mon_wed":       lambda w: [(0, *MONDAY_FULL_DAY), (2, *w)],
    "thu_fri":       lambda w: [(3, *w), (4, *w)],
    "no_weekends":   lambda w: [(0, *MONDAY_FULL_DAY), (1, *w), (2, *w), (3, *w), (4, *w)],
    "weekends_only": lambda w: [(5, *w), (6, *w)],
}

WINDOWS = {
    "mon_wed":       [(dtime(11, 0), dtime(15, 0)), (dtime(12, 0), dtime(16, 0)), (dtime(10, 0), dtime(14, 0))],
    "thu_fri":       [(dtime(12, 0), dtime(16, 0)), (dtime(11, 0), dtime(15, 0)), (dtime(13, 0), dtime(17, 0))],
    "no_weekends":   [(dtime(10, 0), dtime(18, 0)), (dtime(9, 0), dtime(17, 0)), (dtime(10, 30), dtime(18, 30))],
    "weekends_only": [(dtime(11, 0), dtime(22, 0)), (dtime(10, 0), dtime(20, 0)), (dtime(12, 0), dtime(21, 0))],
}


def _window(pattern, idx):
    pool = WINDOWS[pattern]
    return pool[idx % len(pool)]


# ── Per-hospital doctor rosters ─────────────────────────────────────────
# Each doctor dict: first, last, gender, specialisation, qualification,
# experience_years, consultation_fee, followup_fee, registration_no,
# known_for, bio, languages, dob, pattern.
HOSPITALS = {
    "abhaya-clinic": {
        "branch_name": "Abhaya Clinic - Main",
        "doctors": [
            dict(first="Kavitha", last="Reddy", gender="F", specialisation="Pediatrics",
                 qualification="MBBS, DCH", experience_years=9, consultation_fee=500, followup_fee=350,
                 registration_no="KMC/2015/50231",
                 known_for="Child immunization, Growth concerns, Common infections",
                 bio="Kavitha cares for infants through teenagers, with a focus on immunization "
                     "schedules and tracking healthy growth and development.",
                 languages="English, Hindi, Telugu", dob=date(1989, 5, 14), pattern="mon_wed"),
            dict(first="Ramesh", last="Gowda", gender="M", specialisation="General Physician",
                 qualification="MBBS, MD (General Medicine)", experience_years=11, consultation_fee=450, followup_fee=300,
                 registration_no="KMC/2013/44120",
                 known_for="Fever, Diabetes, Hypertension, General checkups",
                 bio="Ramesh handles everyday adult medicine — fevers, infections, diabetes and "
                     "hypertension management, and routine health checkups.",
                 languages="English, Hindi, Kannada", dob=date(1985, 2, 20), pattern="thu_fri"),
            dict(first="Divya", last="Shetty", gender="F", specialisation="Cardiology",
                 qualification="MBBS, MD (Medicine), DM (Cardiology)", experience_years=13, consultation_fee=900, followup_fee=650,
                 registration_no="KMC/2011/38870",
                 known_for="Chest pain, Hypertension, Heart checkups, ECG",
                 bio="Divya is a cardiologist focused on preventive heart care, hypertension "
                     "management and post-cardiac-event follow-up.",
                 languages="English, Hindi, Kannada", dob=date(1983, 8, 3), pattern="no_weekends"),
            dict(first="Suresh", last="Kumar", gender="M", specialisation="Orthopedics",
                 qualification="MBBS, MS (Orthopedics)", experience_years=10, consultation_fee=700, followup_fee=500,
                 registration_no="KMC/2014/42980",
                 known_for="Joint pain, Fractures, Back pain, Sports injuries",
                 bio="Suresh treats fractures, joint pain and sports injuries, covering both "
                     "trauma and elective orthopedic care.",
                 languages="English, Hindi, Kannada", dob=date(1986, 11, 9), pattern="weekends_only"),
        ],
    },
    "sunrise-clinic": {
        "branch_name": "Sunrise Clinic - Main",
        "doctors": [
            dict(first="Anitha", last="Prabhu", gender="F", specialisation="Pediatrics",
                 qualification="MBBS, DCH", experience_years=6, consultation_fee=450, followup_fee=300,
                 registration_no="KMC/2018/54410",
                 known_for="Child immunization, Growth concerns, Newborn care",
                 bio="Anitha specialises in newborn and child care, with an emphasis on "
                     "vaccination schedules and developmental milestones.",
                 languages="English, Hindi, Kannada", dob=date(1992, 1, 27), pattern="mon_wed"),
            dict(first="Vikram", last="Rao", gender="M", specialisation="General Physician",
                 qualification="MBBS, MD (General Medicine)", experience_years=14, consultation_fee=500, followup_fee=350,
                 registration_no="KMC/2010/36540",
                 known_for="Fever, Diabetes, Hypertension, General checkups",
                 bio="Vikram has 14 years of experience in general adult medicine, chronic "
                     "disease management and preventive health checkups.",
                 languages="English, Hindi, Kannada, Tulu", dob=date(1982, 6, 30), pattern="thu_fri"),
            dict(first="Shalini", last="Bhat", gender="F", specialisation="Gynecology & Obstetrics",
                 qualification="MBBS, MS (OBG)", experience_years=12, consultation_fee=750, followup_fee=550,
                 registration_no="KMC/2012/40015",
                 known_for="Pregnancy care, PCOS, Menstrual disorders, Deliveries",
                 bio="Shalini manages high- and low-risk pregnancies, deliveries and general "
                     "gynecological care.",
                 languages="English, Hindi, Kannada", dob=date(1984, 3, 15), pattern="no_weekends"),
            dict(first="Ashwin", last="Pai", gender="M", specialisation="Dermatology",
                 qualification="MBBS, MD (Dermatology)", experience_years=8, consultation_fee=600, followup_fee=400,
                 registration_no="KMC/2016/48870",
                 known_for="Acne, Skin allergies, Hair loss, Cosmetic dermatology",
                 bio="Ashwin treats acne, eczema, hair loss and skin allergies, and offers "
                     "cosmetic dermatology consultations.",
                 languages="English, Hindi, Kannada, Konkani", dob=date(1988, 9, 22), pattern="weekends_only"),
        ],
    },
    "manipal-hospital": {
        "branch_name": "Manipal Hospital - Main",
        "doctors": [
            dict(first="Lakshmi", last="Iyer", gender="F", specialisation="Pediatrics",
                 qualification="MBBS, MD (Pediatrics)", experience_years=10, consultation_fee=550, followup_fee=400,
                 registration_no="KMC/2014/43210",
                 known_for="Child immunization, Growth concerns, Asthma in children",
                 bio="Lakshmi manages pediatric asthma, allergies and routine immunization, "
                     "along with growth and nutrition tracking.",
                 languages="English, Hindi, Kannada, Tamil", dob=date(1986, 4, 5), pattern="mon_wed"),
            dict(first="Arvind", last="Nayak", gender="M", specialisation="General Physician",
                 qualification="MBBS, MD (General Medicine)", experience_years=9, consultation_fee=500, followup_fee=350,
                 registration_no="KMC/2015/46780",
                 known_for="Fever, Diabetes, Hypertension, General checkups",
                 bio="Arvind provides comprehensive adult primary care — infections, diabetes, "
                     "hypertension and annual health checkups.",
                 languages="English, Hindi, Kannada", dob=date(1990, 7, 19), pattern="thu_fri"),
            dict(first="Nandini", last="Kamath", gender="F", specialisation="ENT",
                 qualification="MBBS, MS (ENT)", experience_years=11, consultation_fee=600, followup_fee=420,
                 registration_no="KMC/2013/41560",
                 known_for="Sinusitis, Hearing loss, Tonsillitis, Ear infections",
                 bio="Nandini treats ear, nose and throat conditions across all ages, from "
                     "chronic sinusitis to hearing evaluations.",
                 languages="English, Hindi, Kannada, Konkani", dob=date(1985, 10, 11), pattern="no_weekends"),
            dict(first="Mahesh", last="Bhandary", gender="M", specialisation="General Surgery",
                 qualification="MBBS, MS (General Surgery)", experience_years=15, consultation_fee=800, followup_fee=600,
                 registration_no="KMC/2009/34450",
                 known_for="Hernia, Gallbladder, Appendix, Laparoscopic surgery",
                 bio="Mahesh performs general and laparoscopic surgery, from day-care "
                     "procedures to major abdominal surgery.",
                 languages="English, Hindi, Kannada, Tulu", dob=date(1980, 12, 1), pattern="weekends_only"),
        ],
    },
    "kaveri-hospital": {
        "branch_name": None,  # already has an active branch
        "doctors": [
            dict(first="Swathi", last="Hegde", gender="F", specialisation="Pediatrics",
                 qualification="MBBS, DCH", experience_years=7, consultation_fee=500, followup_fee=350,
                 registration_no="KA-561230",
                 known_for="Child immunization, Growth concerns, Common infections",
                 bio="Swathi cares for infants through teenagers, with a focus on vaccination "
                     "schedules and healthy growth tracking.",
                 languages="English, Hindi, Kannada", dob=date(1991, 2, 8), pattern="mon_wed"),
            dict(first="Ganesh", last="Rao", gender="M", specialisation="Cardiology",
                 qualification="MBBS, MD (Medicine), DM (Cardiology)", experience_years=16, consultation_fee=950, followup_fee=700,
                 registration_no="KA-548821",
                 known_for="Chest pain, Hypertension, Heart checkups, Angioplasty",
                 bio="Ganesh is an interventional cardiologist experienced in coronary "
                     "angiography, angioplasty and long-term heart-failure care.",
                 languages="English, Hindi, Kannada", dob=date(1980, 5, 26), pattern="no_weekends"),
            dict(first="Pallavi", last="Desai", gender="F", specialisation="Orthopedics",
                 qualification="MBBS, MS (Orthopedics)", experience_years=9, consultation_fee=650, followup_fee=450,
                 registration_no="KA-553012",
                 known_for="Joint pain, Fractures, Back pain, Sports injuries",
                 bio="Pallavi treats fractures, joint pain and sports injuries, covering both "
                     "trauma and elective orthopedic care.",
                 languages="English, Hindi, Kannada, Marathi", dob=date(1987, 9, 17), pattern="weekends_only"),
        ],
    },
    "brookefield-hospitals": {
        "branch_name": "Brookefield Hospitals - ITPL Main Road",
        "doctors": [
            dict(first="Rekha", last="Menon", gender="F", specialisation="Pediatrics",
                 qualification="MBBS, DCH", experience_years=8, consultation_fee=550, followup_fee=380,
                 registration_no="KMC/2016/49870",
                 known_for="Child immunization, Growth concerns, Newborn care",
                 bio="Rekha specialises in newborn and child care, with an emphasis on "
                     "vaccination schedules and developmental milestones.",
                 languages="English, Hindi, Kannada, Malayalam", dob=date(1990, 3, 2), pattern="mon_wed"),
            dict(first="Karthik", last="Subramani", gender="M", specialisation="General Physician",
                 qualification="MBBS, MD (General Medicine)", experience_years=10, consultation_fee=500, followup_fee=350,
                 registration_no="KMC/2014/43980",
                 known_for="Fever, Diabetes, Hypertension, General checkups",
                 bio="Karthik provides comprehensive adult primary care — infections, "
                     "diabetes, hypertension and annual health checkups.",
                 languages="English, Hindi, Kannada, Tamil", dob=date(1987, 8, 14), pattern="thu_fri"),
            dict(first="Deepa", last="Acharya", gender="F", specialisation="Dermatology",
                 qualification="MBBS, MD (Dermatology)", experience_years=7, consultation_fee=600, followup_fee=420,
                 registration_no="KMC/2017/51890",
                 known_for="Acne, Skin allergies, Hair loss, Cosmetic dermatology",
                 bio="Deepa treats acne, eczema, hair loss and skin allergies, and offers "
                     "cosmetic dermatology consultations.",
                 languages="English, Hindi, Kannada", dob=date(1991, 12, 9), pattern="no_weekends"),
            dict(first="Naveen", last="Shenoy", gender="M", specialisation="Gastroenterology",
                 qualification="MBBS, MD (Medicine), DM (Gastroenterology)", experience_years=13, consultation_fee=850, followup_fee=600,
                 registration_no="KMC/2011/39210",
                 known_for="Acidity, Liver disease, IBS, Endoscopy",
                 bio="Naveen manages digestive and liver conditions, including diagnostic and "
                     "therapeutic endoscopy.",
                 languages="English, Hindi, Kannada, Tulu", dob=date(1984, 6, 21), pattern="weekends_only"),
        ],
    },
    "mahanandi-hospitals": {
        "branch_name": None,  # already has an active branch
        "doctors": [
            dict(first="Sowmya", last="Patil", gender="F", specialisation="Pediatrics",
                 qualification="MBBS, MD (Pediatrics)", experience_years=6, consultation_fee=500, followup_fee=350,
                 registration_no="KMC/2019/56410",
                 known_for="Child immunization, Growth concerns, Common infections",
                 bio="Sowmya cares for infants through teenagers, tracking immunization "
                     "schedules and healthy growth.",
                 languages="English, Hindi, Kannada", dob=date(1993, 4, 30), pattern="mon_wed"),
            dict(first="Manjunath", last="Hiremath", gender="M", specialisation="General Physician",
                 qualification="MBBS, MD (General Medicine)", experience_years=12, consultation_fee=500, followup_fee=350,
                 registration_no="KMC/2013/41870",
                 known_for="Fever, Diabetes, Hypertension, General checkups",
                 bio="Manjunath handles everyday adult medicine — fevers, infections, "
                     "diabetes and hypertension management.",
                 languages="English, Hindi, Kannada", dob=date(1984, 1, 16), pattern="thu_fri"),
            dict(first="Chaitra", last="Gowda", gender="F", specialisation="ENT",
                 qualification="MBBS, MS (ENT)", experience_years=9, consultation_fee=580, followup_fee=400,
                 registration_no="KMC/2015/47320",
                 known_for="Sinusitis, Hearing loss, Tonsillitis, Ear infections",
                 bio="Chaitra treats ear, nose and throat conditions across all ages, from "
                     "chronic sinusitis to hearing evaluations.",
                 languages="English, Hindi, Kannada", dob=date(1989, 11, 4), pattern="no_weekends"),
            dict(first="Ravikiran", last="Naik", gender="M", specialisation="Endocrinology",
                 qualification="MBBS, MD (Medicine), DM (Endocrinology)", experience_years=11, consultation_fee=750, followup_fee=550,
                 registration_no="KMC/2014/44650",
                 known_for="Diabetes, Thyroid disorders, PCOS, Hormonal imbalance",
                 bio="Ravikiran manages diabetes, thyroid disorders and other hormonal "
                     "conditions, with a focus on long-term metabolic health.",
                 languages="English, Hindi, Kannada", dob=date(1985, 7, 27), pattern="weekends_only"),
        ],
    },
    "care-cure-clinic": {
        "branch_name": "Care & Cure Clinic - Bellandur",
        "doctors": [
            dict(first="Aishwarya", last="Rao", gender="F", specialisation="Pediatrics",
                 qualification="MBBS, DCH", experience_years=7, consultation_fee=450, followup_fee=300,
                 registration_no="KMC/2017/50980",
                 known_for="Child immunization, Growth concerns, Common infections",
                 bio="Aishwarya cares for infants through teenagers, focusing on immunization "
                     "schedules and tracking healthy growth.",
                 languages="English, Hindi, Kannada", dob=date(1991, 3, 11), pattern="mon_wed"),
            dict(first="Basavaraj", last="Patil", gender="M", specialisation="General Physician",
                 qualification="MBBS, MD (General Medicine)", experience_years=13, consultation_fee=500, followup_fee=350,
                 registration_no="KMC/2011/38210",
                 known_for="Fever, Diabetes, Hypertension, General checkups",
                 bio="Basavaraj handles everyday adult medicine — fevers, infections, diabetes "
                     "and hypertension management.",
                 languages="English, Hindi, Kannada", dob=date(1983, 9, 5), pattern="thu_fri"),
            dict(first="Meenal", last="Joshi", gender="F", specialisation="Dermatology",
                 qualification="MBBS, MD (Dermatology)", experience_years=8, consultation_fee=600, followup_fee=420,
                 registration_no="KMC/2016/49330",
                 known_for="Acne, Skin allergies, Hair loss, Cosmetic dermatology",
                 bio="Meenal treats acne, eczema, hair loss and skin allergies, and offers "
                     "cosmetic dermatology consultations.",
                 languages="English, Hindi, Marathi, Kannada", dob=date(1990, 6, 28), pattern="no_weekends"),
            dict(first="Chandrashekar", last="Bhat", gender="M", specialisation="Orthopedics",
                 qualification="MBBS, MS (Orthopedics)", experience_years=12, consultation_fee=700, followup_fee=500,
                 registration_no="KMC/2012/40655",
                 known_for="Joint pain, Fractures, Back pain, Sports injuries",
                 bio="Chandrashekar treats fractures, joint pain and sports injuries, covering "
                     "both trauma and elective orthopedic care.",
                 languages="English, Hindi, Kannada, Tulu", dob=date(1985, 12, 19), pattern="weekends_only"),
        ],
    },
    "krishna-healthcare": {
        "branch_name": "Krishna Healthcare - Mahadevapura",
        "doctors": [
            dict(first="Vidya", last="Ganapathy", gender="F", specialisation="Pediatrics",
                 qualification="MBBS, MD (Pediatrics)", experience_years=9, consultation_fee=500, followup_fee=350,
                 registration_no="KMC/2015/46980",
                 known_for="Child immunization, Growth concerns, Asthma in children",
                 bio="Vidya manages pediatric asthma, allergies and routine immunization, "
                     "along with growth and nutrition tracking.",
                 languages="English, Hindi, Kannada, Tamil", dob=date(1988, 2, 6), pattern="mon_wed"),
            dict(first="Nagesh", last="Kulkarni", gender="M", specialisation="General Physician",
                 qualification="MBBS, MD (General Medicine)", experience_years=10, consultation_fee=500, followup_fee=350,
                 registration_no="KMC/2014/43470",
                 known_for="Fever, Diabetes, Hypertension, General checkups",
                 bio="Nagesh provides comprehensive adult primary care — infections, diabetes, "
                     "hypertension and annual health checkups.",
                 languages="English, Hindi, Kannada", dob=date(1987, 4, 23), pattern="thu_fri"),
            dict(first="Radhika", last="Shenoy", gender="F", specialisation="Cardiology",
                 qualification="MBBS, MD (Medicine), DM (Cardiology)", experience_years=14, consultation_fee=900, followup_fee=650,
                 registration_no="KMC/2010/37110",
                 known_for="Chest pain, Hypertension, Heart checkups, Angioplasty",
                 bio="Radhika is an interventional cardiologist with 14 years of experience in "
                     "coronary angiography, angioplasty and heart-failure care.",
                 languages="English, Hindi, Kannada, Tulu", dob=date(1983, 10, 14), pattern="no_weekends"),
            dict(first="Yashwant", last="Deshpande", gender="M", specialisation="ENT",
                 qualification="MBBS, MS (ENT)", experience_years=9, consultation_fee=580, followup_fee=400,
                 registration_no="KMC/2015/47810",
                 known_for="Sinusitis, Hearing loss, Tonsillitis, Ear infections",
                 bio="Yashwant treats ear, nose and throat conditions across all ages, from "
                     "chronic sinusitis to hearing evaluations.",
                 languages="English, Hindi, Marathi, Kannada", dob=date(1989, 8, 17), pattern="weekends_only"),
        ],
    },
    "nationwide-family-doctors": {
        "branch_name": "Nationwide Family Doctors - Mahadevapura",
        "doctors": [
            dict(first="Sowmya", last="Bhandari", gender="F", specialisation="Pediatrics",
                 qualification="MBBS, DCH", experience_years=6, consultation_fee=450, followup_fee=300,
                 registration_no="KMC/2018/53870",
                 known_for="Child immunization, Growth concerns, Newborn care",
                 bio="Sowmya specialises in newborn and child care, with an emphasis on "
                     "vaccination schedules and developmental milestones.",
                 languages="English, Hindi, Kannada", dob=date(1993, 1, 9), pattern="mon_wed"),
            dict(first="Ibrahim", last="Sait", gender="M", specialisation="General Physician",
                 qualification="MBBS, MD (General Medicine)", experience_years=15, consultation_fee=550, followup_fee=380,
                 registration_no="KMC/2009/35220",
                 known_for="Fever, Diabetes, Hypertension, General checkups",
                 bio="Ibrahim has 15 years of experience in general adult medicine, chronic "
                     "disease management and preventive health checkups.",
                 languages="English, Hindi, Urdu, Kannada", dob=date(1981, 11, 2), pattern="thu_fri"),
            dict(first="Farha", last="Ansari", gender="F", specialisation="Gynecology & Obstetrics",
                 qualification="MBBS, MS (OBG)", experience_years=11, consultation_fee=750, followup_fee=550,
                 registration_no="KMC/2013/41990",
                 known_for="Pregnancy care, PCOS, Menstrual disorders, Deliveries",
                 bio="Farha manages high- and low-risk pregnancies, deliveries and general "
                     "gynecological care.",
                 languages="English, Hindi, Urdu, Kannada", dob=date(1985, 5, 30), pattern="no_weekends"),
            dict(first="Ravindranath", last="Achar", gender="M", specialisation="General Surgery",
                 qualification="MBBS, MS (General Surgery)", experience_years=13, consultation_fee=800, followup_fee=600,
                 registration_no="KMC/2011/39640",
                 known_for="Hernia, Gallbladder, Appendix, Laparoscopic surgery",
                 bio="Ravindranath performs general and laparoscopic surgery, from day-care "
                     "procedures to major abdominal surgery.",
                 languages="English, Hindi, Kannada, Tulu", dob=date(1984, 7, 21), pattern="weekends_only"),
        ],
    },
    "sri-lakshmi-family-dental-clinic": {
        "branch_name": "Sri Lakshmi Family Dental Clinic - Mahadevapura",
        "doctors": [
            dict(first="Keerthana", last="Rai", gender="F", specialisation="Pediatrics",
                 qualification="MBBS, DCH", experience_years=6, consultation_fee=450, followup_fee=300,
                 registration_no="KMC/2018/54120",
                 known_for="Child immunization, Growth concerns, Common infections",
                 bio="Keerthana cares for infants through teenagers, tracking immunization "
                     "schedules and healthy growth.",
                 languages="English, Hindi, Kannada, Tulu", dob=date(1992, 9, 24), pattern="mon_wed"),
            dict(first="Manohar", last="Pai", gender="M", specialisation="General Physician",
                 qualification="MBBS, MD (General Medicine)", experience_years=10, consultation_fee=500, followup_fee=350,
                 registration_no="KMC/2014/44010",
                 known_for="Fever, Diabetes, Hypertension, General checkups",
                 bio="Manohar handles everyday adult medicine — fevers, infections, diabetes "
                     "and hypertension management.",
                 languages="English, Hindi, Kannada, Konkani", dob=date(1987, 12, 13), pattern="thu_fri"),
            dict(first="Ashritha", last="Shetty", gender="F", specialisation="Dentistry",
                 qualification="BDS, MDS (Conservative Dentistry)", experience_years=8, consultation_fee=500, followup_fee=350,
                 registration_no="KDC/2016/28710",
                 known_for="Root canal, Fillings, Teeth cleaning, Cavities",
                 bio="Ashritha handles general and restorative dentistry — root canals, "
                     "fillings, extractions and routine dental checkups.",
                 languages="English, Hindi, Kannada, Tulu", dob=date(1990, 4, 2), pattern="no_weekends"),
            dict(first="Rohan", last="D'Silva", gender="M", specialisation="Orthodontics",
                 qualification="BDS, MDS (Orthodontics)", experience_years=7, consultation_fee=650, followup_fee=450,
                 registration_no="KDC/2017/29940",
                 known_for="Braces, Teeth alignment, Bite correction",
                 bio="Rohan specialises in braces, aligners and correcting bite and teeth "
                     "alignment issues for both teenagers and adults.",
                 languages="English, Hindi, Konkani, Kannada", dob=date(1991, 8, 8), pattern="weekends_only"),
        ],
    },
    "pushpa-nursing-home": {
        "branch_name": "Pushpa Nursing Home - Whitefield",
        "doctors": [
            dict(first="Lavanya", last="Reddy", gender="F", specialisation="Pediatrics",
                 qualification="MBBS, MD (Pediatrics)", experience_years=8, consultation_fee=500, followup_fee=350,
                 registration_no="KMC/2016/48540",
                 known_for="Child immunization, Growth concerns, Common infections",
                 bio="Lavanya cares for infants through teenagers, with a focus on immunization "
                     "schedules and tracking healthy growth and development.",
                 languages="English, Hindi, Telugu, Kannada", dob=date(1990, 10, 17), pattern="mon_wed"),
            dict(first="Srinivasa", last="Murthy", gender="M", specialisation="General Physician",
                 qualification="MBBS, MD (General Medicine)", experience_years=17, consultation_fee=550, followup_fee=380,
                 registration_no="KMC/2007/32110",
                 known_for="Fever, Diabetes, Hypertension, General checkups",
                 bio="Srinivasa has 17 years of experience in general adult medicine, chronic "
                     "disease management and preventive health checkups.",
                 languages="English, Hindi, Kannada, Telugu", dob=date(1979, 6, 4), pattern="thu_fri"),
            dict(first="Padmavathi", last="Iyengar", gender="F", specialisation="Gynecology & Obstetrics",
                 qualification="MBBS, MS (OBG)", experience_years=15, consultation_fee=800, followup_fee=580,
                 registration_no="KMC/2009/35810",
                 known_for="Pregnancy care, PCOS, Menstrual disorders, Deliveries",
                 bio="Padmavathi has delivered generations of families in Whitefield, managing "
                     "high- and low-risk pregnancies and general gynecological care.",
                 languages="English, Hindi, Kannada, Telugu", dob=date(1981, 1, 28), pattern="no_weekends"),
            dict(first="Harish", last="Chandran", gender="M", specialisation="Orthopedics",
                 qualification="MBBS, MS (Orthopedics)", experience_years=11, consultation_fee=700, followup_fee=500,
                 registration_no="KMC/2013/42340",
                 known_for="Joint pain, Fractures, Back pain, Sports injuries",
                 bio="Harish treats fractures, joint pain and sports injuries, covering both "
                     "trauma and elective orthopedic care.",
                 languages="English, Hindi, Malayalam, Kannada", dob=date(1986, 3, 15), pattern="weekends_only"),
        ],
    },
}

# ── 1 nurse, 1 front desk, 1 lab tech, 1 pharmacist per hospital ────────
# (skip_nurse=True for Kaveri, which already has one)
SUPPORT_STAFF = {
    "abhaya-clinic": dict(
        nurse=dict(first="Meghana", last="Poojary", gender="F", qualification="B.Sc Nursing", experience_years=4,
                   registration_no="KSNC/2021/25630", council_name="Karnataka State Nursing Council",
                   registration_expiry=date(2029, 4, 30),
                   bio="Meghana handles vitals, ward rounds and medication administration.",
                   languages="English, Hindi, Kannada", dob=date(1998, 5, 9)),
        front_desk=dict(first="Yogesh", last="Salian", gender="M", qualification="BBA (Hospital Administration)",
                        experience_years=3, bio="Yogesh runs front-desk operations — registration, "
                        "appointment booking, check-in and billing initiation.",
                        languages="English, Hindi, Kannada", dob=date(1997, 8, 21)),
        lab_tech=dict(first="Prakash", last="Bhat", gender="M", qualification="B.Sc Medical Laboratory Technology",
                     experience_years=5, registration_no="IAMLS/KA/2020/3311",
                     council_name="Indian Association of Medical Laboratory Scientists",
                     registration_expiry=date(2028, 2, 28),
                     bio="Prakash handles sample collection, lab order processing and report verification.",
                     languages="English, Kannada, Hindi", dob=date(1994, 10, 3)),
        pharmacist=dict(first="Sindhu", last="Kulkarni", gender="F", qualification="B.Pharm", experience_years=6,
                        registration_no="KSPC/2019/62910", council_name="Karnataka State Pharmacy Council",
                        registration_expiry=date(2027, 9, 30),
                        bio="Sindhu handles prescription processing, dispensing and pharmacy stock management.",
                        languages="English, Hindi, Kannada", dob=date(1993, 6, 12)),
    ),
    "sunrise-clinic": dict(
        nurse=dict(first="Ayesha", last="Khan", gender="F", qualification="GNM", experience_years=5,
                   registration_no="KSNC/2020/24870", council_name="Karnataka State Nursing Council",
                   registration_expiry=date(2028, 8, 31),
                   bio="Ayesha manages patient vitals, ward care and medication rounds.",
                   languages="English, Hindi, Urdu, Kannada", dob=date(1996, 1, 19)),
        front_desk=dict(first="Deepak", last="Shetty", gender="M", qualification="B.Com",
                        experience_years=2, bio="Deepak manages patient registration, appointment "
                        "scheduling and front-desk billing.",
                        languages="English, Hindi, Kannada", dob=date(1999, 3, 27)),
        lab_tech=dict(first="Farhan", last="Ahmed", gender="M", qualification="B.Sc Medical Laboratory Technology",
                     experience_years=4, registration_no="IAMLS/KA/2021/3402",
                     council_name="Indian Association of Medical Laboratory Scientists",
                     registration_expiry=date(2028, 6, 30),
                     bio="Farhan handles sample collection, lab order processing and result entry.",
                     languages="English, Hindi, Urdu", dob=date(1995, 12, 15)),
        pharmacist=dict(first="Rashmi", last="Nayak", gender="F", qualification="B.Pharm", experience_years=5,
                        registration_no="KSPC/2020/63488", council_name="Karnataka State Pharmacy Council",
                        registration_expiry=date(2028, 1, 31),
                        bio="Rashmi handles prescription processing, dispensing and stock/expiry tracking.",
                        languages="English, Hindi, Kannada", dob=date(1995, 4, 8)),
    ),
    "manipal-hospital": dict(
        nurse=dict(first="Pavithra", last="Achar", gender="F", qualification="B.Sc Nursing", experience_years=6,
                   registration_no="KSNC/2018/23110", council_name="Karnataka State Nursing Council",
                   registration_expiry=date(2027, 12, 31),
                   bio="Pavithra coordinates ward nursing care, vitals and medication administration.",
                   languages="English, Hindi, Kannada, Tulu", dob=date(1994, 9, 5)),
        front_desk=dict(first="Rohit", last="D'Souza", gender="M", qualification="BBA (Hospital Administration)",
                        experience_years=4, bio="Rohit runs front-desk operations — registration, "
                        "appointment booking and queue management.",
                        languages="English, Hindi, Konkani, Kannada", dob=date(1995, 11, 30)),
        lab_tech=dict(first="Harsha", last="Vardhan", gender="M", qualification="B.Sc Medical Laboratory Technology",
                     experience_years=6, registration_no="IAMLS/KA/2018/3025",
                     council_name="Indian Association of Medical Laboratory Scientists",
                     registration_expiry=date(2027, 5, 31),
                     bio="Harsha handles sample collection, lab order processing and report verification.",
                     languages="English, Kannada, Hindi", dob=date(1992, 2, 24)),
        pharmacist=dict(first="Anusha", last="Kamath", gender="F", qualification="B.Pharm", experience_years=7,
                        registration_no="KSPC/2017/60215", council_name="Karnataka State Pharmacy Council",
                        registration_expiry=date(2026, 12, 31),
                        bio="Anusha handles prescription processing, dispensing and pharmacy inventory.",
                        languages="English, Hindi, Kannada", dob=date(1991, 7, 16)),
    ),
    "kaveri-hospital": dict(
        nurse=None,  # already has a nurse (Riza Sharma)
        front_desk=dict(first="Manoj", last="Hegde", gender="M", qualification="B.Com",
                        experience_years=3, bio="Manoj manages patient registration, appointment "
                        "scheduling and front-desk billing.",
                        languages="English, Hindi, Kannada", dob=date(1997, 5, 2)),
        lab_tech=dict(first="Divya", last="Kulkarni", gender="F", qualification="B.Sc Medical Laboratory Technology",
                     experience_years=5, registration_no="IAMLS/KA/2019/3155",
                     council_name="Indian Association of Medical Laboratory Scientists",
                     registration_expiry=date(2028, 3, 31),
                     bio="Divya handles sample collection, lab order processing and result entry.",
                     languages="English, Kannada, Hindi", dob=date(1994, 8, 19)),
        pharmacist=dict(first="Santosh", last="Gowda", gender="M", qualification="B.Pharm", experience_years=6,
                        registration_no="KSPC/2018/61455", council_name="Karnataka State Pharmacy Council",
                        registration_expiry=date(2027, 7, 31),
                        bio="Santosh handles prescription processing, dispensing and stock/expiry tracking.",
                        languages="English, Hindi, Kannada", dob=date(1993, 10, 28)),
    ),
    "brookefield-hospitals": dict(
        nurse=dict(first="Priyanka", last="Nair", gender="F", qualification="B.Sc Nursing", experience_years=5,
                   registration_no="KSNC/2019/24012", council_name="Karnataka State Nursing Council",
                   registration_expiry=date(2028, 10, 31),
                   bio="Priyanka manages patient vitals, ward care and medication administration.",
                   languages="English, Hindi, Malayalam, Kannada", dob=date(1995, 2, 14)),
        front_desk=dict(first="Abhishek", last="Kulkarni", gender="M", qualification="BBA (Hospital Administration)",
                        experience_years=3, bio="Abhishek runs front-desk operations — registration, "
                        "appointment booking and billing initiation.",
                        languages="English, Hindi, Kannada, Marathi", dob=date(1996, 6, 23)),
        lab_tech=dict(first="Vinay", last="Kamath", gender="M", qualification="B.Sc Medical Laboratory Technology",
                     experience_years=4, registration_no="IAMLS/KA/2021/3455",
                     council_name="Indian Association of Medical Laboratory Scientists",
                     registration_expiry=date(2028, 9, 30),
                     bio="Vinay handles sample collection, lab order processing and report verification.",
                     languages="English, Kannada, Hindi", dob=date(1996, 3, 11)),
        pharmacist=dict(first="Nisha", last="Shetty", gender="F", qualification="B.Pharm", experience_years=5,
                        registration_no="KSPC/2020/63910", council_name="Karnataka State Pharmacy Council",
                        registration_expiry=date(2028, 4, 30),
                        bio="Nisha handles prescription processing, dispensing and pharmacy stock management.",
                        languages="English, Hindi, Kannada", dob=date(1995, 9, 1)),
    ),
    "mahanandi-hospitals": dict(
        nurse=dict(first="Bhavana", last="Rao", gender="F", qualification="GNM", experience_years=4,
                   registration_no="KSNC/2021/25710", council_name="Karnataka State Nursing Council",
                   registration_expiry=date(2029, 1, 31),
                   bio="Bhavana handles vitals, ward rounds and medication administration.",
                   languages="English, Hindi, Kannada", dob=date(1997, 12, 6)),
        front_desk=dict(first="Chetan", last="Poojary", gender="M", qualification="B.Com",
                        experience_years=2, bio="Chetan manages patient registration, appointment "
                        "scheduling and front-desk billing.",
                        languages="English, Hindi, Kannada, Tulu", dob=date(1998, 7, 17)),
        lab_tech=dict(first="Supriya", last="Hegde", gender="F", qualification="B.Sc Medical Laboratory Technology",
                     experience_years=3, registration_no="IAMLS/KA/2022/3520",
                     council_name="Indian Association of Medical Laboratory Scientists",
                     registration_expiry=date(2029, 5, 31),
                     bio="Supriya handles sample collection, lab order processing and result entry.",
                     languages="English, Kannada, Hindi", dob=date(1997, 4, 25)),
        pharmacist=dict(first="Girish", last="Kamath", gender="M", qualification="B.Pharm", experience_years=4,
                        registration_no="KSPC/2021/64530", council_name="Karnataka State Pharmacy Council",
                        registration_expiry=date(2028, 11, 30),
                        bio="Girish handles prescription processing, dispensing and pharmacy inventory.",
                        languages="English, Hindi, Kannada", dob=date(1996, 2, 9)),
    ),
    "care-cure-clinic": dict(
        nurse=dict(first="Anjali", last="Naik", gender="F", qualification="B.Sc Nursing", experience_years=5,
                   registration_no="KSNC/2019/24330", council_name="Karnataka State Nursing Council",
                   registration_expiry=date(2028, 7, 31),
                   bio="Anjali handles vitals, ward rounds and medication administration.",
                   languages="English, Hindi, Kannada", dob=date(1995, 5, 20)),
        front_desk=dict(first="Vikas", last="Gowda", gender="M", qualification="B.Com",
                        experience_years=3, bio="Vikas manages patient registration, appointment "
                        "scheduling and front-desk billing.",
                        languages="English, Hindi, Kannada", dob=date(1996, 10, 8)),
        lab_tech=dict(first="Shwetha", last="Rao", gender="F", qualification="B.Sc Medical Laboratory Technology",
                     experience_years=4, registration_no="IAMLS/KA/2020/3340",
                     council_name="Indian Association of Medical Laboratory Scientists",
                     registration_expiry=date(2028, 5, 31),
                     bio="Shwetha handles sample collection, lab order processing and result entry.",
                     languages="English, Kannada, Hindi", dob=date(1996, 1, 12)),
        pharmacist=dict(first="Mohammed", last="Rafi", gender="M", qualification="B.Pharm", experience_years=6,
                        registration_no="KSPC/2018/61990", council_name="Karnataka State Pharmacy Council",
                        registration_expiry=date(2027, 6, 30),
                        bio="Mohammed handles prescription processing, dispensing and pharmacy stock management.",
                        languages="English, Hindi, Urdu, Kannada", dob=date(1993, 3, 27)),
    ),
    "krishna-healthcare": dict(
        nurse=dict(first="Deepthi", last="Kamath", gender="F", qualification="GNM", experience_years=4,
                   registration_no="KSNC/2020/24980", council_name="Karnataka State Nursing Council",
                   registration_expiry=date(2028, 9, 30),
                   bio="Deepthi manages patient vitals, ward care and medication rounds.",
                   languages="English, Hindi, Kannada, Tulu", dob=date(1996, 6, 15)),
        front_desk=dict(first="Praveen", last="Shetty", gender="M", qualification="BBA (Hospital Administration)",
                        experience_years=3, bio="Praveen runs front-desk operations — registration, "
                        "appointment booking and queue management.",
                        languages="English, Hindi, Kannada, Tulu", dob=date(1995, 2, 11)),
        lab_tech=dict(first="Ananya", last="Bhat", gender="F", qualification="B.Sc Medical Laboratory Technology",
                     experience_years=5, registration_no="IAMLS/KA/2019/3210",
                     council_name="Indian Association of Medical Laboratory Scientists",
                     registration_expiry=date(2027, 12, 31),
                     bio="Ananya handles sample collection, lab order processing and report verification.",
                     languages="English, Kannada, Hindi", dob=date(1994, 11, 3)),
        pharmacist=dict(first="Girisha", last="Poojary", gender="M", qualification="B.Pharm", experience_years=7,
                        registration_no="KSPC/2017/60650", council_name="Karnataka State Pharmacy Council",
                        registration_expiry=date(2026, 10, 31),
                        bio="Girisha handles prescription processing, dispensing and pharmacy inventory.",
                        languages="English, Hindi, Kannada, Tulu", dob=date(1992, 4, 19)),
    ),
    "nationwide-family-doctors": dict(
        nurse=dict(first="Nazia", last="Khatoon", gender="F", qualification="B.Sc Nursing", experience_years=6,
                   registration_no="KSNC/2018/23440", council_name="Karnataka State Nursing Council",
                   registration_expiry=date(2027, 11, 30),
                   bio="Nazia coordinates ward nursing care, vitals and medication administration.",
                   languages="English, Hindi, Urdu, Kannada", dob=date(1994, 7, 9)),
        front_desk=dict(first="Shashank", last="Rao", gender="M", qualification="B.Com",
                        experience_years=2, bio="Shashank manages patient registration, appointment "
                        "scheduling and front-desk billing.",
                        languages="English, Hindi, Kannada", dob=date(1998, 1, 30)),
        lab_tech=dict(first="Fathima", last="Sadiq", gender="F", qualification="B.Sc Medical Laboratory Technology",
                     experience_years=4, registration_no="IAMLS/KA/2021/3480",
                     council_name="Indian Association of Medical Laboratory Scientists",
                     registration_expiry=date(2028, 8, 31),
                     bio="Fathima handles sample collection, lab order processing and result entry.",
                     languages="English, Hindi, Urdu, Kannada", dob=date(1995, 9, 22)),
        pharmacist=dict(first="Ramachandra", last="Hegde", gender="M", qualification="B.Pharm", experience_years=8,
                        registration_no="KSPC/2016/59870", council_name="Karnataka State Pharmacy Council",
                        registration_expiry=date(2026, 6, 30),
                        bio="Ramachandra handles prescription processing, dispensing and pharmacy inventory.",
                        languages="English, Hindi, Kannada", dob=date(1990, 12, 24)),
    ),
    "sri-lakshmi-family-dental-clinic": dict(
        nurse=dict(first="Vinutha", last="Kamath", gender="F", qualification="GNM", experience_years=3,
                   registration_no="KSNC/2022/25890", council_name="Karnataka State Nursing Council",
                   registration_expiry=date(2029, 3, 31),
                   bio="Vinutha assists with dental chairside procedures, vitals and patient prep.",
                   languages="English, Hindi, Kannada, Tulu", dob=date(1997, 8, 5)),
        front_desk=dict(first="Akshay", last="Prabhu", gender="M", qualification="B.Com",
                        experience_years=2, bio="Akshay manages patient registration, appointment "
                        "scheduling and front-desk billing.",
                        languages="English, Hindi, Kannada, Konkani", dob=date(1998, 4, 14)),
        lab_tech=dict(first="Sneha", last="Rai", gender="F", qualification="B.Sc Medical Laboratory Technology",
                     experience_years=3, registration_no="IAMLS/KA/2022/3540",
                     council_name="Indian Association of Medical Laboratory Scientists",
                     registration_expiry=date(2029, 4, 30),
                     bio="Sneha handles sample collection, lab order processing and result entry.",
                     languages="English, Kannada, Hindi", dob=date(1997, 2, 18)),
        pharmacist=dict(first="Deepak", last="Shenoy", gender="M", qualification="B.Pharm", experience_years=5,
                        registration_no="KSPC/2019/62410", council_name="Karnataka State Pharmacy Council",
                        registration_expiry=date(2027, 10, 31),
                        bio="Deepak handles prescription processing, dispensing and stock/expiry tracking.",
                        languages="English, Hindi, Kannada, Konkani", dob=date(1994, 5, 30)),
    ),
    "pushpa-nursing-home": dict(
        nurse=dict(first="Roopa", last="Chandran", gender="F", qualification="B.Sc Nursing", experience_years=7,
                   registration_no="KSNC/2017/22990", council_name="Karnataka State Nursing Council",
                   registration_expiry=date(2027, 4, 30),
                   bio="Roopa handles vitals, ward rounds and medication administration, with a "
                       "focus on maternity and postnatal care.",
                   languages="English, Hindi, Malayalam, Kannada", dob=date(1993, 11, 11)),
        front_desk=dict(first="Naveen", last="Kumar", gender="M", qualification="BBA (Hospital Administration)",
                        experience_years=4, bio="Naveen runs front-desk operations — registration, "
                        "appointment booking and billing initiation.",
                        languages="English, Hindi, Kannada, Telugu", dob=date(1994, 9, 3)),
        lab_tech=dict(first="Kavya", last="Murthy", gender="F", qualification="B.Sc Medical Laboratory Technology",
                     experience_years=6, registration_no="IAMLS/KA/2017/3010",
                     council_name="Indian Association of Medical Laboratory Scientists",
                     registration_expiry=date(2026, 11, 30),
                     bio="Kavya handles sample collection, lab order processing and report verification.",
                     languages="English, Kannada, Telugu, Hindi", dob=date(1992, 7, 26)),
        pharmacist=dict(first="Suresh", last="Babu", gender="M", qualification="B.Pharm", experience_years=9,
                        registration_no="KSPC/2015/58320", council_name="Karnataka State Pharmacy Council",
                        registration_expiry=date(2026, 3, 31),
                        bio="Suresh handles prescription processing, dispensing and pharmacy inventory.",
                        languages="English, Hindi, Kannada, Telugu", dob=date(1988, 8, 20)),
    ),
}


def _generate_signature_base64(full_name):
    """Render a plausible-looking signature PNG for digital_signature. Best
    effort — returns "" if Pillow / fonts aren't available."""
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
    """Best-effort download + base64-encode for StaffUser.photo."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
        return "data:image/jpeg;base64," + base64.b64encode(data).decode()
    except Exception as exc:
        logger.warning("Photo download skipped for %s: %s", url, exc)
        return ""


class Command(BaseCommand):
    help = "Seed doctors + nurse/front-desk/lab-tech/pharmacist into the 6 recently-provisioned, near-empty hospitals."

    def add_arguments(self, parser):
        parser.add_argument("--password", default=DEFAULT_PASSWORD,
                             help=f"Password for every new staff member (default: {DEFAULT_PASSWORD}).")
        parser.add_argument("--no-photos", action="store_true",
                             help="Skip downloading Unsplash profile photos (no network needed).")
        parser.add_argument("--backfill-photos", action="store_true",
                             help="Don't create anyone — just download+set photo/photo_url for staff "
                                  "this command already created (matched by name+role) that are missing one.")

    def handle(self, *args, **options):
        password = options["password"]
        with_photos = not options["no_photos"]

        self._mobile_counter = STARTING_MOBILE
        self._photo_counters = {"M": 0, "F": 0}
        self._credentials = []

        if options["backfill_photos"]:
            self._backfill_photos()
            return

        for subdomain, spec in HOSPITALS.items():
            self._seed_one_hospital(subdomain, spec, SUPPORT_STAFF[subdomain], password, with_photos)

        self._fix_kaveri_monday()
        self._bump_starter_tier_subscriptions()

        self.stdout.write(self.style.SUCCESS(f"\n{len(self._credentials)} staff created.\n"))
        if self._credentials:
            self.stdout.write(f"Password for every account below: {password}\n")
            self.stdout.write(f"  {'Hospital':<24} {'Name':<20} {'Role':<24} {'Mobile':<12} {'Email'}")
            for row in self._credentials:
                self.stdout.write(f"  {row['hospital']:<24} {row['name']:<20} {row['role']:<24} {row['mobile']:<12} {row['email']}")
        self.stdout.write("")

    # ── per-hospital ─────────────────────────────────────────────────────
    def _seed_one_hospital(self, subdomain, spec, support, password, with_photos):
        tenant = Tenant.objects.using("default").filter(subdomain=subdomain).first()
        if not tenant:
            raise CommandError(f"No tenant with subdomain={subdomain!r}.")
        db = tenant.db_name
        if db not in dj_settings.DATABASES:
            dj_settings.DATABASES[db] = _make_db_config(db)

        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{tenant.name} ({subdomain}, {db})"))

        branch = Branch.objects.using(db).filter(is_active=True).order_by("id").first()
        if not branch:
            branch = Branch.objects.using(db).create(
                name=spec["branch_name"] or f"{tenant.name} - Main",
                address="", city=tenant.city or "Bengaluru", state=tenant.state or "Karnataka",
                pincode="", phone="", is_active=True,
            )
            self.stdout.write(f"  Created branch: {branch.name} (id={branch.id})")
        else:
            self.stdout.write(f"  Using existing branch: {branch.name} (id={branch.id})")

        email_domain = f"{subdomain}.demo"
        dept_cache = {}

        def get_dept(name):
            if name not in dept_cache:
                dept, _ = Department.objects.using(db).get_or_create(
                    branch=branch, name=name, defaults={"is_active": True}
                )
                dept_cache[name] = dept
            return dept_cache[name]

        def next_employee_id():
            from apps.org.models import NextNumber
            NextNumber.objects.using(db).get_or_create(
                branch_id=0, entity="employee_id",
                defaults={"prefix": "EMP-", "pad_length": 6, "last_number": 0},
            )
            formatted_id, _ = get_next_number(0, "employee_id", using=db)
            return formatted_id

        def next_mobile():
            while True:
                candidate = str(self._mobile_counter)
                self._mobile_counter += 1
                if not StaffMobileIndex.objects.using("default").filter(mobile=candidate).exists():
                    return candidate

        def make_staff(first, last, gender, role, dept_name, dob):
            full_name = f"{first} {last}"
            existing = StaffUser.objects.using(db).filter(
                first_name=first, last_name=last, role=role
            ).first()
            if existing:
                self.stdout.write(f"    = {role:<12} {full_name:<20} already exists — skipping")
                self._credentials.append(dict(
                    hospital=tenant.name, name=full_name, role=role, mobile=existing.phone,
                    email=existing.email or "",
                ))
                existing._demo_photo_url = ""
                existing._already_existed = True
                return existing

            phone = next_mobile()
            email = f"{first}.{last}".lower().replace(" ", "").replace("'", "") + f"@{email_domain}"

            photo_url, photo_b64 = "", ""
            if with_photos:
                pool = MALE_PHOTOS if gender == "M" else FEMALE_PHOTOS
                idx = self._photo_counters[gender] % len(pool)
                self._photo_counters[gender] += 1
                photo_url = pool[idx]
                photo_b64 = _download_photo_base64(photo_url)

            with transaction.atomic(using=db):
                staff = StaffUser(
                    email=email, first_name=first, last_name=last, role=role,
                    branch=branch, department=get_dept(dept_name) if dept_name else None,
                    phone=phone, employee_id=next_employee_id(), date_of_birth=dob,
                    is_active=True, must_change_password=False, photo=photo_b64,
                )
                staff.set_password(password)
                staff.save(using=db)

            StaffMobileIndex.objects.using("default").update_or_create(
                mobile=phone, defaults={"tenant_id": tenant.id, "db_name": db, "email": email},
            )
            staff._demo_photo_url = photo_url
            self._credentials.append(dict(
                hospital=tenant.name, name=full_name, role=role, mobile=phone, email=email,
            ))
            self.stdout.write(f"    + {role:<12} {full_name:<20} {phone}")
            return staff

        # ── Doctors ──────────────────────────────────────────────────────
        for d in spec["doctors"]:
            staff = make_staff(d["first"], d["last"], d["gender"], "doctor", d["specialisation"], d["dob"])
            if getattr(staff, "_already_existed", False):
                continue
            DoctorProfile.objects.using(db).create(
                staff=staff, registration_no=d["registration_no"], specialisation=d["specialisation"],
                qualification=d["qualification"], gender=d["gender"], experience_years=d["experience_years"],
                consultation_fee=d["consultation_fee"], followup_fee=d["followup_fee"],
                digital_signature=_generate_signature_base64(f"Dr. {d['first']} {d['last']}"),
                bio=d["bio"], photo_url=staff._demo_photo_url or "", languages=d["languages"],
                known_for=d["known_for"],
            )
            self._build_schedule(db, staff, d["pattern"], HOSPITALS_INDEX[subdomain])

        # ── Nurse / front desk / lab tech / pharmacist ──────────────────
        role_map = [("nurse", "nurse", "Nursing"), ("front_desk", "front_desk", "Front Desk"),
                    ("lab_tech", "lab_tech", "Laboratory"), ("pharmacist", "pharmacist", "Pharmacy")]
        extra_map = {
            "nurse": {"ward": "General Ward"},
            "front_desk": {"desk": "Main Reception"},
            "lab_tech": {"lab_section": "General Lab"},
            "pharmacist": {"counter": "OPD Pharmacy"},
        }
        for key, role, dept_name in role_map:
            o = support.get(key)
            if not o:
                self.stdout.write(f"    (skipping {role} — already present)")
                continue
            staff = make_staff(o["first"], o["last"], o["gender"], role, dept_name, o["dob"])
            if getattr(staff, "_already_existed", False):
                continue
            StaffProfile.objects.using(db).create(
                staff=staff, registration_no=o.get("registration_no", ""),
                council_name=o.get("council_name", ""), registration_expiry=o.get("registration_expiry"),
                qualification=o["qualification"], experience_years=o["experience_years"], gender=o["gender"],
                bio=o["bio"], languages=o["languages"], extra=extra_map[role],
            )

    def _build_schedule(self, db, staff, pattern, hospital_idx):
        schedule = DoctorSchedule.objects.using(db).create(doctor=staff, slot_duration_minutes=15)
        window = _window(pattern, hospital_idx)
        rows = SLOT_PATTERNS[pattern](window)
        working_days = {d for d, *_ in rows}
        working_days.add(0)  # Monday is always on, regardless of pattern
        for day in range(7):
            if day == 0:
                start, end = MONDAY_FULL_DAY
                is_available = True
            else:
                match = next((r for r in rows if r[0] == day), None)
                if match:
                    _, start, end = match
                    is_available = True
                else:
                    start, end = window
                    is_available = False
            DoctorAvailabilitySlot.objects.using(db).create(
                schedule=schedule, day_of_week=day, is_available=is_available,
                start_time=start, end_time=end,
            )

    def _backfill_photos(self):
        for subdomain, spec in HOSPITALS.items():
            tenant = Tenant.objects.using("default").filter(subdomain=subdomain).first()
            if not tenant:
                continue
            db = tenant.db_name
            if db not in dj_settings.DATABASES:
                dj_settings.DATABASES[db] = _make_db_config(db)
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n{tenant.name} ({subdomain})"))

            all_people = list(spec["doctors"])
            for o in SUPPORT_STAFF[subdomain].values():
                if o:
                    all_people.append(o)

            for p in all_people:
                staff = StaffUser.objects.using(db).filter(
                    first_name=p["first"], last_name=p["last"]
                ).first()
                if not staff:
                    self.stdout.write(f"  ! {p['first']} {p['last']} not found — skipping")
                    continue
                pool = MALE_PHOTOS if p["gender"] == "M" else FEMALE_PHOTOS
                idx = self._photo_counters[p["gender"]] % len(pool)
                self._photo_counters[p["gender"]] += 1
                photo_url = pool[idx]
                if staff.photo:
                    self.stdout.write(f"  = {p['first']} {p['last']} already has a photo — skipping")
                    continue
                photo_b64 = _download_photo_base64(photo_url)
                if not photo_b64:
                    self.stdout.write(self.style.WARNING(f"  x {p['first']} {p['last']} — download failed"))
                    continue
                staff.photo = photo_b64
                staff.save(using=db, update_fields=["photo"])
                if staff.role == "doctor":
                    DoctorProfile.objects.using(db).filter(staff=staff).update(photo_url=photo_url)
                self.stdout.write(f"  + {p['first']} {p['last']} — photo set")

    def _fix_kaveri_monday(self):
        """Kaveri's pre-existing doctor (Prashant Sharma) had Monday marked
        off — override it to a full working day like every other doctor."""
        db = "aw_kaveri_hospital"
        if db not in dj_settings.DATABASES:
            dj_settings.DATABASES[db] = _make_db_config(db)
        staff = StaffUser.objects.using(db).filter(role="doctor", first_name="Prashant", last_name="Sharma").first()
        if not staff:
            return
        schedule = DoctorSchedule.objects.using(db).filter(doctor=staff).first()
        if not schedule:
            return
        start, end = MONDAY_FULL_DAY
        DoctorAvailabilitySlot.objects.using(db).filter(schedule=schedule, day_of_week=0).update(
            is_available=True, start_time=start, end_time=end,
        )
        self.stdout.write(self.style.SUCCESS(f"\nPatched {staff.get_full_name()}'s Monday slot to full-day (Kaveri Hospital)."))

    def _bump_starter_tier_subscriptions(self):
        """Several hospitals in this roster were provisioned on the starter
        tier (max_doctors=3, max_staff=5) — the roster below (4 doctors + 4
        support staff each) exceeds both soft caps, so raise them to avoid
        UI limit warnings. Only touches tenants actually seeded above."""
        for subdomain in HOSPITALS.keys():
            tenant = Tenant.objects.using("default").filter(subdomain=subdomain).first()
            if not tenant:
                continue
            sub = Subscription.objects.using("default").filter(tenant=tenant).first()
            if not sub or sub.license_tier != "starter":
                continue
            changed = []
            if sub.max_doctors < 10:
                sub.max_doctors = 10
                changed.append("max_doctors")
            if sub.max_staff < 20:
                sub.max_staff = 20
                changed.append("max_staff")
            if changed:
                sub.save(using="default", update_fields=changed)
                self.stdout.write(self.style.SUCCESS(f"Bumped {tenant.name} subscription: {', '.join(changed)}."))


HOSPITALS_INDEX = {name: i for i, name in enumerate(HOSPITALS.keys())}
