"""
Management command: assign_employee_ids

Populates StaffUser.employee_id for staff who don't have one yet, so login
can use the {hospital code, employee ID, password} path (StaffLoginView /
StaffLoginSerializer) instead of a mobile number or email — easier to hand
out and remember for a demo or a front-desk cheat sheet.

employee_id is only unique WITHIN a tenant (see StaffUser.employee_id's own
docstring), so this assigns role-prefixed, per-tenant sequential IDs:
DOC-001, DOC-002, ... for doctors, NUR-001... for nurses, FD-001... for
front desk, LAB-001... for lab techs, PHR-001... for pharmacists, ADM-001...
for hospital admins, and STF-001... for anyone with a custom role. The
"hospital code" you log in with alongside the employee ID is the tenant's
own subdomain (e.g. novacare-flagship) — printed in the output table below,
so there's nothing else to look up.

Idempotent and additive: only fills in staff who currently have
employee_id=None. Never touches, renumbers, or reassigns an employee_id
that's already set (by this command or by hand), so it's safe to re-run
after adding new staff — they'll just get the next number in their role's
sequence.

Usage:
  # One hospital:
  python manage.py assign_employee_ids --tenant aw_novacare_flagship --settings=atomwalk.settings.development

  # Every active hospital on the platform in one pass:
  python manage.py assign_employee_ids --all --settings=atomwalk.settings.development

Also writes EMPLOYEE_LOGIN_CODES.md (same directory convention as
INVESTOR_DEMO_CREDENTIALS.md) with one section per hospital processed,
appending to the file rather than overwriting it — running this for one
hospital today and another tomorrow builds up one combined reference
instead of each run erasing the last.
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.tenants.models import Tenant
from apps.tenants.utils import _make_db_config
from apps.org.models import StaffUser

ROLE_PREFIX = {
    "doctor":         "DOC",
    "nurse":          "NUR",
    "front_desk":     "FD",
    "lab_tech":       "LAB",
    "pharmacist":     "PHR",
    "hospital_admin": "ADM",
}
DEFAULT_PREFIX = "STF"  # custom roles, or anything not in the map above
ROLE_LABEL = {
    "doctor": "Doctor", "nurse": "Nurse", "front_desk": "Front Desk",
    "lab_tech": "Lab Technician", "pharmacist": "Pharmacist",
    "hospital_admin": "Hospital Admin",
}


class Command(BaseCommand):
    help = "Assign role-prefixed employee IDs to staff who don't have one yet, for hospital-code + employee-ID login."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--tenant", dest="db_name", help="Tenant db_name to process (e.g. aw_novacare_flagship).")
        group.add_argument("--all", action="store_true", help="Process every active tenant on the platform.")

    def handle(self, *args, **options):
        if options["all"]:
            tenants = list(Tenant.objects.using("default").filter(is_active=True).order_by("name"))
            if not tenants:
                raise CommandError("No active tenants found.")
        else:
            db = options["db_name"]
            try:
                tenants = [Tenant.objects.using("default").get(db_name=db)]
            except Tenant.DoesNotExist:
                raise CommandError(f"No tenant found with db_name='{db}'.")

        sections = []
        for tenant in tenants:
            sections.append(self._process_tenant(tenant))

        out_path = Path(settings.BASE_DIR) / "EMPLOYEE_LOGIN_CODES.md"
        existing = out_path.read_text(encoding="utf-8") if out_path.exists() else (
            "# Employee ID Login Codes\n\n"
            "Login as staff with **hospital code + employee ID + password** instead of "
            "a mobile number — hospital code is the subdomain shown under each hospital below.\n"
        )
        stamp = f"\n\n<!-- assign_employee_ids run: {timezone.now().strftime('%d-%b-%Y %H:%M')} -->\n"
        out_path.write_text(existing + stamp + "".join(sections), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"\nWritten to: {out_path}"))

    def _process_tenant(self, tenant):
        db = tenant.db_name
        if db not in settings.DATABASES:
            settings.DATABASES[db] = _make_db_config(db)

        self.stdout.write(f"\n{'=' * 70}\n  {tenant.name} ({tenant.subdomain})\n{'=' * 70}")

        # Seed next-available sequence number per prefix from whatever's
        # already assigned, so a re-run (or staff added by hand with their
        # own employee_id) never collides with an existing one.
        next_seq = {}
        for eid in StaffUser.objects.using(db).exclude(employee_id__isnull=True).exclude(employee_id="").values_list("employee_id", flat=True):
            prefix, _, num = eid.rpartition("-")
            if prefix and num.isdigit():
                next_seq[prefix] = max(next_seq.get(prefix, 0), int(num))

        rows = []  # (role_label, name, employee_id, mobile)
        with transaction.atomic(using=db):
            staff_needing_id = (
                StaffUser.objects.using(db)
                .filter(is_active=True)
                .filter(Q(employee_id__isnull=True) | Q(employee_id=""))
                .order_by("role", "id")
            )
            for staff in staff_needing_id:
                prefix = ROLE_PREFIX.get(staff.role, DEFAULT_PREFIX)
                next_seq[prefix] = next_seq.get(prefix, 0) + 1
                staff.employee_id = f"{prefix}-{next_seq[prefix]:03d}"
                staff.save(using=db, update_fields=["employee_id"])
                rows.append((ROLE_LABEL.get(staff.role, staff.role.title()), staff.get_full_name(), staff.employee_id, staff.phone))
                self.stdout.write(f"  {staff.employee_id}  {staff.get_full_name()} ({staff.role})")

        # Also list staff who already had an employee_id, so the printed
        # table/doc is a complete login sheet, not just what changed today.
        already = (
            StaffUser.objects.using(db).filter(is_active=True)
            .exclude(employee_id__isnull=True).exclude(employee_id="")
            .order_by("role", "employee_id")
        )
        already_rows = [
            (ROLE_LABEL.get(s.role, s.role.title()), s.get_full_name(), s.employee_id, s.phone)
            for s in already if s.employee_id not in {r[2] for r in rows}
        ]

        all_rows = sorted(already_rows + rows, key=lambda r: (r[0], r[2]))
        if not all_rows:
            self.stdout.write(self.style.WARNING("  No staff to list."))
            return f"\n## {tenant.name}\n\nHospital code (subdomain): `{tenant.subdomain}`\n\n_No staff found._\n"

        lines = [
            f"\n## {tenant.name}\n\n",
            f"Hospital code (subdomain): `{tenant.subdomain}`  |  Password: unchanged from however each account was created\n\n",
            "| Role | Name | Employee ID | Mobile (fallback login) |\n",
            "|---|---|---|---|\n",
        ]
        for role_label, name, eid, mobile in all_rows:
            lines.append(f"| {role_label} | {name} | `{eid}` | {mobile} |\n")

        self.stdout.write(self.style.SUCCESS(f"  {len(rows)} new, {len(already_rows)} already had one — {len(all_rows)} total."))
        return "".join(lines)
