"""
Management command: repair_patient_identities

Every hospital patient row must have a shared identity (patient_identity) with the same AWPID; the documents, bookings and
family links all point at the identity. This finds hospital patients that have none and restores it from the hospital's own
row (name, date of birth, sex, dependent flag, and the mobile's scrambled form when no one else already has it).
It only adds missing identities; it never changes or deletes anything. A dependent restored this way has no guardian link,
because the hospital row does not say who the guardian was.

Usage:
  python manage.py repair_patient_identities                 # report only
  python manage.py repair_patient_identities --apply         # restore the missing identities
  python manage.py repair_patient_identities --db aw_x --apply
"""
from django.core.management.base import BaseCommand

from apps.patients.models import Patient
from apps.registry.models import PatientIdentity
from apps.tenants.models import Tenant
from apps.tenants.utils import ensure_tenant_db
from core.utils.hashing import hash_mobile, normalize_mobile


def restore_identities(db_name, apply=False):
    """The hospital patients in `db_name` with no shared identity; restores them when `apply`. Returns the list."""
    missing = []
    for patient in Patient.objects.using(db_name).order_by("id"):
        if PatientIdentity.objects.using("default").filter(awpid=patient.awpid).exists():
            continue
        missing.append(patient)
        if not apply:
            continue
        mobile_hash = None
        if patient.mobile and not patient.is_dependent:
            candidate = hash_mobile(normalize_mobile(patient.mobile))
            if not PatientIdentity.objects.using("default").filter(mobile_hash=candidate).exists():
                mobile_hash = candidate
        PatientIdentity.objects.using("default").create(
            awpid=patient.awpid, full_name=patient.full_name, date_of_birth=patient.date_of_birth,
            gender=(patient.gender or "")[:10], is_dependent=patient.is_dependent, mobile_hash=mobile_hash,
            email=patient.email or "", blood_group=patient.blood_group or "")
    return missing


class Command(BaseCommand):
    help = "Restore the shared identity of hospital patients that have none"

    def add_arguments(self, parser):
        parser.add_argument("--db", dest="db_name", default=None, help="Only this hospital database")
        parser.add_argument("--apply", action="store_true", help="Restore the identities (default: only report)")

    def handle(self, *args, **options):
        tenants = Tenant.objects.filter(db_name=options["db_name"]) if options["db_name"] else Tenant.objects.filter(is_active=True)
        total = 0
        for tenant in tenants:
            try:
                ensure_tenant_db(tenant.db_name)
                missing = restore_identities(tenant.db_name, apply=options["apply"])
            except Exception as exc:                       # a hospital database that is not reachable here
                self.stdout.write(self.style.WARNING(f"  {tenant.db_name}: skipped ({str(exc)[:60]})"))
                continue
            total += len(missing)
            self.stdout.write(f"  {tenant.db_name}: {len(missing)} patient(s) without a shared identity")
        verb = "restored" if options["apply"] else "found (run again with --apply to restore them)"
        self.stdout.write(self.style.SUCCESS(f"{total} {verb}."))
