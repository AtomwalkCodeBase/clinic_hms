"""
Management command: set_staff_photo

Sets a staff member's profile photo (StaffUser.photo — the same field the
staff's own self-service "My Profile" photo upload writes to) from a local
image file, base64-encoded as a data URI exactly like the upload endpoint
does. This is the field _doctor_card() in portal_views.py reads for the
patient-portal doctor photo, so setting it here immediately shows up on
doctor cards and profile pages across the app.

Meant for one-off admin/demo-data touch-ups (e.g. dropping in a real photo
for a seeded doctor) — staff normally set their own via the app.

Usage:
  python manage.py set_staff_photo --tenant aw_greenleaf_clinic --name "Arjun Mehta" --image seed_assets/doctor_arjun_mehta.png
  python manage.py set_staff_photo --tenant aw_greenleaf_clinic --email arjun@greenleaf.com --image photo.jpg
"""

import base64
import mimetypes

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from apps.tenants.models import Tenant
from apps.tenants.utils import _make_db_config
from apps.org.models import StaffUser


class Command(BaseCommand):
    help = "Set a staff member's profile photo from a local image file."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", dest="db_name", required=True,
                             help="Tenant db_name to target (e.g. aw_greenleaf_clinic).")
        parser.add_argument("--image", dest="image_path", required=True,
                             help="Path to the image file.")
        parser.add_argument("--name", dest="name", default=None,
                             help="Match staff by full name (case-insensitive, partial ok).")
        parser.add_argument("--email", dest="email", default=None,
                             help="Match staff by exact email instead of name.")

    def handle(self, *args, **options):
        db_name    = options["db_name"]
        image_path = options["image_path"]
        name       = options.get("name")
        email      = options.get("email")

        if not name and not email:
            raise CommandError("Specify --name or --email to identify the staff member.")

        try:
            tenant = Tenant.objects.get(db_name=db_name)
        except Tenant.DoesNotExist:
            raise CommandError(f"No tenant found with db_name='{db_name}'")

        if tenant.db_name not in settings.DATABASES:
            settings.DATABASES[tenant.db_name] = _make_db_config(tenant.db_name)
        db = tenant.db_name

        qs = StaffUser.objects.using(db)
        if email:
            matches = list(qs.filter(email__iexact=email))
        else:
            parts = name.strip().split()
            matches = list(qs.filter(first_name__icontains=parts[0]))
            if len(parts) > 1:
                matches = [s for s in matches if parts[-1].lower() in (s.last_name or "").lower()]

        if not matches:
            raise CommandError(f"No staff member found matching {'email='+email if email else 'name='+name} at {tenant.name}.")
        if len(matches) > 1:
            listing = "\n".join(f"  - {s.get_full_name()} <{s.email}> (id={s.id})" for s in matches)
            raise CommandError(f"Multiple staff members matched — be more specific:\n{listing}")

        staff = matches[0]

        try:
            with open(image_path, "rb") as f:
                raw = f.read()
        except OSError as exc:
            raise CommandError(f"Could not read '{image_path}': {exc}")

        mime, _ = mimetypes.guess_type(image_path)
        mime = mime or "image/jpeg"
        data_uri = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"

        staff.photo = data_uri
        staff.save(using=db, update_fields=["photo"])

        self.stdout.write(self.style.SUCCESS(
            f"Set photo for {staff.get_full_name()} <{staff.email}> at {tenant.name} "
            f"({len(raw):,} bytes, {mime})."
        ))
