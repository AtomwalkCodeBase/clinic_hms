"""
Management command: set_investor_demo_photos

Generalized version of set_demo_doctor_photos.py — that script only works
for the exact 12 hardcoded doctors seed_full_demo creates. This one takes
any tenant db_name, finds every doctor in it, and downloads a gender-matched
Unsplash portrait for anyone who doesn't already have a StaffUser.photo set
(so it's safe to re-run — it only fills gaps, never overwrites a photo a
real staff member uploaded themselves, unless --overwrite is passed).

IMPORTANT: this must be run somewhere with real internet access to
unsplash.com (your own machine, not this sandbox) — run it after
seed_investor_demo.

Licensing note: these are real Unsplash stock photos (free to use for any
purpose under the Unsplash License, no attribution required), standing in
as fictional demo doctor identities. To swap any one doctor's photo
individually instead:
  python manage.py set_staff_photo --tenant <db_name> --email <email> --image <file>

Usage:
  python manage.py set_investor_demo_photos --tenant aw_atomwalk_flagship
  python manage.py set_investor_demo_photos --tenant aw_atomwalk_flagship --overwrite
"""

import base64
import itertools
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.org.models import StaffUser
from apps.tenants.models import Tenant
from apps.tenants.utils import _make_db_config

MALE_PHOTOS = [
    "https://images.unsplash.com/photo-1612349317150-e413f6a5b16d?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1612531386530-97286d97c2d2?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1730597842283-943c7986ee2c?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1612349316228-5942a9b489c2?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1612531385446-f7e6d131e1d0?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1659353888096-cc5e333db5e0?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1622253692010-333f2da6031d?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1537368910025-700350fe46c7?crop=faces&fit=crop&w=400&h=400&q=80",
]
FEMALE_PHOTOS = [
    "https://images.unsplash.com/photo-1741707039536-113e200f9e0d?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1741275269731-83526786bb93?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1741707038935-0bf1f8eda81c?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1741707040287-7c0228b2fca7?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1749017818421-aadb344f32d8?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1741707039571-f1c3f957a2e8?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1580489944761-15a19d654956?crop=faces&fit=crop&w=400&h=400&q=80",
    "https://images.unsplash.com/photo-1594824476967-48c8b964273f?crop=faces&fit=crop&w=400&h=400&q=80",
]


class Command(BaseCommand):
    help = "Download gender-matched Unsplash portraits for every doctor in a tenant that doesn't already have a photo."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", dest="db_name", required=True,
                             help="Tenant db_name to target (e.g. aw_atomwalk_flagship).")
        parser.add_argument("--overwrite", action="store_true",
                             help="Replace existing photos too, not just fill blank ones.")

    def handle(self, *args, **options):
        db_name = options["db_name"]
        overwrite = options["overwrite"]

        if not Tenant.objects.using("default").filter(db_name=db_name).exists():
            raise CommandError(f"No tenant found with db_name='{db_name}'.")

        if db_name not in settings.DATABASES:
            settings.DATABASES[db_name] = _make_db_config(db_name)

        doctors = StaffUser.objects.using(db_name).filter(role="doctor").select_related("doctor_profile").order_by("id")
        if not overwrite:
            doctors = doctors.filter(photo="")

        if not doctors.exists():
            self.stdout.write(self.style.WARNING(
                "No doctors need a photo (all already have one — pass --overwrite to replace them)."
            ))
            return

        male_pool = itertools.cycle(MALE_PHOTOS)
        female_pool = itertools.cycle(FEMALE_PHOTOS)

        total = 0
        for staff in doctors:
            gender = getattr(getattr(staff, "doctor_profile", None), "gender", "") or "M"
            url = next(female_pool) if gender == "F" else next(male_pool)

            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    raw = resp.read()
                    content_type = resp.headers.get("Content-Type", "image/jpeg")
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"  Failed to download photo for {staff.email}: {exc}"))
                continue

            data_uri = f"data:{content_type};base64,{base64.b64encode(raw).decode('ascii')}"
            staff.photo = data_uri
            staff.save(using=db_name, update_fields=["photo"])
            self.stdout.write(self.style.SUCCESS(f"  {staff.get_full_name()} <{staff.email}> — photo set ({len(raw):,} bytes)"))
            total += 1

        self.stdout.write(f"\nDone — {total} doctor photo(s) set.")
