"""
Management command: set_demo_doctor_photos

Downloads a free-to-use Unsplash portrait for each seed_full_demo doctor
(gender-matched to DoctorProfile.gender) and sets it as their profile photo
— the same field set_staff_photo.py writes to, just fetched straight from
Unsplash instead of a local file.

IMPORTANT: this must be run somewhere with real internet access to
unsplash.com (your own machine) — it cannot run from a network-sandboxed
environment. Run it after seed_full_demo.

Licensing note: these are real Unsplash stock photos (free to use for any
purpose under the Unsplash License, no attribution required), standing in
as fictional demo doctor identities. If you'd rather use different images
for a client-facing demo, swap any doctor's photo individually with:
  python manage.py set_staff_photo --tenant <db_name> --email <email> --image <file>

Usage:
  python manage.py set_demo_doctor_photos --settings=atomwalk.settings.development
"""

import base64
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.org.models import StaffUser
from apps.tenants.utils import _make_db_config

MALE_PHOTOS = [
    "https://images.unsplash.com/photo-1612349317150-e413f6a5b16d?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1612531386530-97286d97c2d2?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1730597842283-943c7986ee2c?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1612349316228-5942a9b489c2?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1612531385446-f7e6d131e1d0?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1659353888096-cc5e333db5e0?crop=faces&fit=crop&w=400&h=400&q=80",
]
FEMALE_PHOTOS = [
    "https://images.unsplash.com/photo-1741707039536-113e200f9e0d?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1741275269731-83526786bb93?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1741707038935-0bf1f8eda81c?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1741707040287-7c0228b2fca7?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1749017818421-aadb344f32d8?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1741707039571-f1c3f957a2e8?crop=faces&fit=crop&w=400&h=400&q=80",
]

# (tenant db_name, staff email, photo url) — matches the 12 doctors created
# by seed_full_demo, in the order they were created (3 per hospital).
DOCTOR_PHOTOS = [
    ("aw_lakeview_demo",       "vikram.doctor1@lakeview-demo.demo",       MALE_PHOTOS[0]),
    ("aw_lakeview_demo",       "ananya.doctor2@lakeview-demo.demo",       FEMALE_PHOTOS[0]),
    ("aw_lakeview_demo",       "karan.doctor3@lakeview-demo.demo",        MALE_PHOTOS[1]),
    ("aw_horizon_care_demo",   "meera.doctor1@horizon-care-demo.demo",    FEMALE_PHOTOS[1]),
    ("aw_horizon_care_demo",   "rohan.doctor2@horizon-care-demo.demo",    MALE_PHOTOS[2]),
    ("aw_horizon_care_demo",   "divya.doctor3@horizon-care-demo.demo",    FEMALE_PHOTOS[2]),
    ("aw_cedar_health_demo",   "aditya.doctor1@cedar-health-demo.demo",   MALE_PHOTOS[3]),
    ("aw_cedar_health_demo",   "priya.doctor2@cedar-health-demo.demo",    FEMALE_PHOTOS[3]),
    ("aw_cedar_health_demo",   "suresh.doctor3@cedar-health-demo.demo",   MALE_PHOTOS[4]),
    ("aw_metro_wellness_demo", "neha.doctor1@metro-wellness-demo.demo",   FEMALE_PHOTOS[4]),
    ("aw_metro_wellness_demo", "farhan.doctor2@metro-wellness-demo.demo", MALE_PHOTOS[5]),
    ("aw_metro_wellness_demo", "kavya.doctor3@metro-wellness-demo.demo",  FEMALE_PHOTOS[5]),
]


class Command(BaseCommand):
    help = "Download gender-matched Unsplash portraits and set them as photos for every seed_full_demo doctor."

    def handle(self, *args, **options):
        total = 0
        for db_name, email, url in DOCTOR_PHOTOS:
            if db_name not in settings.DATABASES:
                settings.DATABASES[db_name] = _make_db_config(db_name)
            try:
                staff = StaffUser.objects.using(db_name).get(email=email)
            except StaffUser.DoesNotExist:
                self.stdout.write(self.style.WARNING(
                    f"  Skipped {email} — not found in {db_name} (run seed_full_demo first?)."
                ))
                continue

            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    raw = resp.read()
                    content_type = resp.headers.get("Content-Type", "image/jpeg")
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"  Failed to download photo for {email}: {exc}"))
                continue

            data_uri = f"data:{content_type};base64,{base64.b64encode(raw).decode('ascii')}"
            staff.photo = data_uri
            staff.save(using=db_name, update_fields=["photo"])
            self.stdout.write(self.style.SUCCESS(f"  {staff.get_full_name()} <{email}> — photo set ({len(raw):,} bytes)"))
            total += 1

        self.stdout.write(f"\nDone — {total}/{len(DOCTOR_PHOTOS)} doctor photo(s) set.")
