"""Management command: assign_employee_ids"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.hospital_master.models import Hospital
from apps.hospital_master.services import ensure_hospital_db
from apps.hospital_setup.models import StaffUser
from apps.hospital_setup.rbac import api_role

ROLE_PREFIX = {
    "doctor":         "DOC",
    "nurse":          "NUR",
    "front_desk":     "FD",
    "hospital_admin": "ADM",
}
DEFAULT_PREFIX = "STF"  # custom roles, or anything not in the map above
ROLE_LABEL = {
    "doctor": "Doctor", "nurse": "Nurse", "front_desk": "Front Desk",
    "hospital_admin": "Hospital Admin",
}


class Command(BaseCommand):
    help = "Assign role-prefixed employee IDs to staff who don't have one yet, for hospital-code + employee-ID login."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--hospital", dest="db_name", help="Hospital db_name to process (e.g. aw_novacare_flagship).")
        group.add_argument("--all", action="store_true", help="Process every active hospital on the platform.")

    def handle(self, *args, **options):
        if options["all"]:
            hospitals = list(Hospital.objects.using("default").filter(is_active=True).order_by("name"))
            if not hospitals:
                raise CommandError("No active hospitals found.")
        else:
            db = options["db_name"]
            try:
                hospitals = [Hospital.objects.using("default").get(db_name=db)]
            except Hospital.DoesNotExist:
                raise CommandError(f"No hospital found with db_name='{db}'.")

        sections = []
        for hospital in hospitals:
            sections.append(self._process_hospital(hospital))

        out_path = Path(settings.BASE_DIR) / "EMPLOYEE_LOGIN_CODES.md"
        existing = out_path.read_text(encoding="utf-8") if out_path.exists() else (
            "# Employee ID Login Codes\n\n"
            "Login as staff with **hospital code + employee ID + password** instead of "
            "a mobile number — hospital code is the hospital_code shown under each hospital below.\n"
        )
        stamp = f"\n\n<!-- assign_employee_ids run: {timezone.now().strftime('%d-%b-%Y %H:%M')} -->\n"
        out_path.write_text(existing + stamp + "".join(sections), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"\nWritten to: {out_path}"))

    def _process_hospital(self, hospital):
        db = hospital.db_name
        ensure_hospital_db(db)

        self.stdout.write(f"\n{'=' * 70}\n  {hospital.name} ({hospital.hospital_code})\n{'=' * 70}")

        # Seed next-available sequence number per prefix from whatever's
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
                .select_related("user_group")
                .order_by("user_group__role", "pk")
            )
            for staff in staff_needing_id:
                prefix = ROLE_PREFIX.get(api_role(staff), DEFAULT_PREFIX)
                next_seq[prefix] = next_seq.get(prefix, 0) + 1
                staff.employee_id = f"{prefix}-{next_seq[prefix]:03d}"
                staff.save(using=db, update_fields=["employee_id"])
                rows.append((ROLE_LABEL.get(api_role(staff), api_role(staff).title()), staff.get_full_name(), staff.employee_id, staff.phone))
                self.stdout.write(f"  {staff.employee_id}  {staff.get_full_name()} ({api_role(staff)})")

        # Also list staff who already had an employee_id, so the printed
        already = (
            StaffUser.objects.using(db).filter(is_active=True)
            .exclude(employee_id__isnull=True).exclude(employee_id="")
            .select_related("user_group")
            .order_by("user_group__role", "employee_id")
        )
        already_rows = [
            (ROLE_LABEL.get(api_role(s), api_role(s).title()), s.get_full_name(), s.employee_id, s.phone)
            for s in already if s.employee_id not in {r[2] for r in rows}
        ]

        all_rows = sorted(already_rows + rows, key=lambda r: (r[0], r[2]))
        if not all_rows:
            self.stdout.write(self.style.WARNING("  No staff to list."))
            return f"\n## {hospital.name}\n\nHospital code: `{hospital.hospital_code}`\n\n_No staff found._\n"

        lines = [
            f"\n## {hospital.name}\n\n",
            f"Hospital code: `{hospital.hospital_code}`  |  Password: unchanged from however each account was created\n\n",
            "| Role | Name | Employee ID | Mobile (fallback login) |\n",
            "|---|---|---|---|\n",
        ]
        for role_label, name, eid, mobile in all_rows:
            lines.append(f"| {role_label} | {name} | `{eid}` | {mobile} |\n")

        self.stdout.write(self.style.SUCCESS(f"  {len(rows)} new, {len(already_rows)} already had one — {len(all_rows)} total."))
        return "".join(lines)
