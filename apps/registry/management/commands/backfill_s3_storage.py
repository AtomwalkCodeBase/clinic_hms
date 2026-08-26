"""
Management command: backfill_s3_storage

One-time migration for every field that used to store a file as a base64
data URI directly in Postgres (see core/storage.py's module docstring for
the full rationale). Uploads each existing blob to S3 and rewrites the row
to store the resulting object key instead — after this runs, nothing in the
database should hold raw base64 file content anymore.

Fields covered:
  Registry DB ("default"):
    - registry.PatientAccount.photo
    - tenants.Tenant.logo
    - registry.SharedDocument.file_data
    - registry.SharedLabResult.file_data
    - registry.SharedVaccination.file_data
  Per tenant DB:
    - org.StaffUser.photo
    - org.DoctorProfile.digital_signature
    - lab.LabReport.file_url

Safe to re-run: any value that doesn't start with "data:" is assumed to
already be an S3 key (or blank) and is skipped, so a partial/interrupted
run can just be run again.

Usage:
  python manage.py backfill_s3_storage
  python manage.py backfill_s3_storage --dry-run
  python manage.py backfill_s3_storage --db aw_sunrise_clinic
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from core import storage as blob_storage
from core.file_validation import validate_data_uri, FileValidationError
from apps.tenants.models import Tenant
from apps.tenants.utils import _make_db_config


class Command(BaseCommand):
    help = "Backfill every base64-in-Postgres blob field to S3, storing the object key instead."

    def add_arguments(self, parser):
        parser.add_argument(
            "--db", dest="db_name", default=None,
            help="Only backfill this tenant's per-tenant fields (registry-level fields always run). "
                 "Default: all active tenants.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would be migrated without uploading or writing anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        db_name = options.get("db_name")

        if not settings.AWS_S3_BUCKET and not dry_run:
            self.stderr.write(self.style.ERROR(
                "AWS_S3_BUCKET isn't configured — set the AWS_S3_* environment variables "
                "before running this for real, or pass --dry-run to preview."
            ))
            return

        totals = {"migrated": 0, "skipped": 0, "failed": 0}

        self.stdout.write(self.style.MIGRATE_HEADING("Registry DB (default)"))
        self._backfill_registry(dry_run, totals)

        if db_name:
            tenants = Tenant.objects.using("default").filter(db_name=db_name)
            if not tenants.exists():
                self.stderr.write(self.style.ERROR(f"No tenant found with db_name='{db_name}'"))
                return
        else:
            tenants = Tenant.objects.using("default").filter(is_active=True)

        for tenant in tenants:
            db = tenant.db_name
            if db not in settings.DATABASES:
                settings.DATABASES[db] = _make_db_config(db)
            self.stdout.write(self.style.MIGRATE_HEADING(f"{tenant.name} ({db})"))
            self._backfill_tenant(tenant, dry_run, totals)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"Done. migrated={totals['migrated']} skipped={totals['skipped']} failed={totals['failed']}"
            + (" (dry run — nothing was written)" if dry_run else "")
        ))

    # ── field-level helper ───────────────────────────────────────────────────

    def _migrate_field(self, obj, field, prefix, category, using, dry_run, totals, label, name_field=None,
                        identity="", detail="", raw_name="", raw_identifier=""):
        value = getattr(obj, field)
        if not value or not value.startswith("data:"):
            totals["skipped"] += 1
            return

        try:
            mime_type = validate_data_uri(value)
        except FileValidationError as exc:
            totals["failed"] += 1
            self.stdout.write(self.style.ERROR(f"  [{label}] id={obj.pk} invalid file data: {exc}"))
            return

        if dry_run:
            totals["migrated"] += 1
            self.stdout.write(f"  [{label}] id={obj.pk} would migrate ({mime_type}, {len(value)} chars)")
            return

        try:
            key = blob_storage.upload_data_uri(value, prefix=prefix, mime_type=mime_type, category=category, identity=identity)
        except blob_storage.StorageError as exc:
            totals["failed"] += 1
            self.stdout.write(self.style.ERROR(f"  [{label}] id={obj.pk} upload failed: {exc}"))
            return

        setattr(obj, field, key)
        update_fields = [field]
        # For models with their own user-facing file_name (LabReport,
        # SharedDocument, SharedVaccination), rename that too — a file
        # migrated from the old base64 convention keeps whatever the
        # original uploader named it otherwise, which is exactly the
        # inconsistency this backfill is meant to clean up. `detail` (the
        # specific test/vaccine/document title) plus `raw_name`/
        # `raw_identifier` (unslugged, unlike `identity` above which is
        # already S3-folder-safe) bake who-and-what into the visible
        # filename itself — see display_file_name()'s docstring.
        if name_field is not None:
            setattr(obj, name_field, blob_storage.display_file_name(
                category, mime_type, detail=detail, name=raw_name, identifier=raw_identifier,
            ))
            update_fields.append(name_field)
        obj.save(using=using, update_fields=update_fields)
        totals["migrated"] += 1
        self.stdout.write(f"  [{label}] id={obj.pk} -> {key}")

    # ── registry DB ──────────────────────────────────────────────────────────

    def _backfill_registry(self, dry_run, totals):
        from apps.registry.models import PatientAccount, SharedDocument, SharedLabResult, SharedVaccination, PatientIdentity

        # awpid -> full_name, looked up once rather than per-row — this is a
        # one-time script, but the Shared* tables can have thousands of rows
        # sharing a small number of patients.
        names_by_awpid = dict(PatientIdentity.objects.using("default").values_list("awpid", "full_name"))

        def name_for(awpid, name=""):
            return name or names_by_awpid.get(awpid, "")

        def ident(awpid, name=""):
            return blob_storage.identity_slug(name=name_for(awpid, name), identifier=awpid)

        for acct in PatientAccount.objects.using("default").exclude(photo=""):
            self._migrate_field(acct, "photo", "patient-photos", "patient-photo", "default", dry_run, totals,
                                 "PatientAccount.photo", identity=ident(acct.awpid, acct.full_name))

        for tenant in Tenant.objects.using("default").exclude(logo=""):
            self._migrate_field(tenant, "logo", f"hospital-logos/{blob_storage.tenant_folder(tenant)}", "hospital-logo", "default", dry_run, totals, "Tenant.logo")

        for doc in SharedDocument.objects.using("default").exclude(file_data=""):
            self._migrate_field(doc, "file_data", "patient-documents", "patient-document", "default", dry_run, totals,
                                 "SharedDocument.file_data", name_field="file_name", identity=ident(doc.awpid),
                                 detail=doc.title, raw_name=name_for(doc.awpid), raw_identifier=doc.awpid)

        for r in SharedLabResult.objects.using("default").exclude(file_data=""):
            self._migrate_field(r, "file_data", "shared-lab-results", "shared-lab-result", "default", dry_run, totals,
                                 "SharedLabResult.file_data", identity=ident(r.awpid))

        for v in SharedVaccination.objects.using("default").exclude(file_data=""):
            self._migrate_field(v, "file_data", "vaccination-certs", "vaccination-certificate", "default", dry_run, totals,
                                 "SharedVaccination.file_data", name_field="file_name", identity=ident(v.awpid),
                                 detail=v.vaccine_name, raw_name=name_for(v.awpid), raw_identifier=v.awpid)

    # ── per-tenant DB ────────────────────────────────────────────────────────

    def _backfill_tenant(self, tenant, dry_run, totals):
        from apps.org.models import StaffUser, DoctorProfile
        from apps.lab.models import LabReport

        db = tenant.db_name
        folder = blob_storage.tenant_folder(tenant)
        try:
            for staff in StaffUser.objects.using(db).exclude(photo=""):
                identity = blob_storage.identity_slug(name=staff.get_full_name(), identifier=staff.email)
                self._migrate_field(staff, "photo", f"staff-photos/{folder}", "staff-photo", db, dry_run, totals,
                                     "StaffUser.photo", identity=identity)

            for profile in DoctorProfile.objects.using(db).select_related("staff").exclude(digital_signature=""):
                identity = blob_storage.identity_slug(name=profile.staff.get_full_name(), identifier=profile.staff.email)
                self._migrate_field(profile, "digital_signature", f"doctor-signatures/{folder}", "doctor-signature", db, dry_run, totals,
                                     "DoctorProfile.digital_signature", identity=identity)

            for report in LabReport.objects.using(db).select_related("patient", "request__test").exclude(file_url=""):
                identity = blob_storage.identity_slug(name=report.patient.full_name, identifier=report.patient.awpid)
                self._migrate_field(report, "file_url", f"lab-reports/{folder}", "lab-report", db, dry_run, totals,
                                     "LabReport.file_url", name_field="file_name", identity=identity,
                                     detail=report.request.test.name,
                                     raw_name=report.patient.full_name, raw_identifier=report.patient.awpid)
        except Exception as exc:
            totals["failed"] += 1
            self.stdout.write(self.style.ERROR(f"  Tenant DB error: {exc}"))
