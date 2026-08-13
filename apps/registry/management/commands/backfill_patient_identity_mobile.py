"""
Management command: backfill_patient_identity_mobile

One-time repair for two related bugs that both leave a patient invisible to
front desk's cross-hospital "Find Patient" search (PatientService.lookup_by_mobile),
even though their own portal profile looks completely normal:

  1. Missing PatientIdentity row entirely. The very first version of the
     public self-signup flow (PortalRegisterView) created only a
     PatientAccount and never touched PatientIdentity — the registry table
     front desk actually searches. Fixed going forward, but any account
     created before that fix has no identity row at all, so it never shows
     up in ANY hospital's dedup search, ever — not even a stale-number
     mismatch, just nothing.
  2. Stale mobile_hash. PortalProfileView.patch() (My Profile → edit mobile)
     used to update PatientAccount.mobile without updating the matching
     PatientIdentity.mobile_hash. Also fixed going forward, but a patient
     who changed their number before that fix still shows their new number
     on their own profile while front desk's search still looks for the
     old one.

This walks every PatientAccount and, per row:
  - if there's no PatientIdentity for its awpid at all, creates one from the
    account's own name/dob/gender/mobile;
  - if there is one but its mobile_hash doesn't match the account's current
    mobile, updates it.
Skips (and reports) any case where the target mobile_hash is already taken
by a different identity — mobile_hash is unique at the DB level, so those
need a human to look at rather than being silently overwritten or merged.

Usage:
  python manage.py backfill_patient_identity_mobile           # apply
  python manage.py backfill_patient_identity_mobile --dry-run  # report only
"""

from django.core.management.base import BaseCommand

from apps.registry.models import PatientAccount, PatientIdentity
from core.utils.hashing import hash_mobile, normalize_mobile


class Command(BaseCommand):
    help = "Create/repair PatientIdentity rows for any patient invisible to front-desk dedup search (missing identity or stale mobile_hash)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing anything.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        created, fixed, already_ok, skipped_conflict, no_mobile = 0, 0, 0, 0, 0

        for acct in PatientAccount.objects.using("default").all():
            if not acct.mobile:
                no_mobile += 1
                continue

            try:
                mobile_hash = hash_mobile(normalize_mobile(acct.mobile))
            except ValueError:
                self.stdout.write(self.style.WARNING(
                    f"  Skipping {acct.awpid} ({acct.full_name}) — mobile '{acct.mobile}' won't normalize."
                ))
                continue

            identity = PatientIdentity.objects.using("default").filter(awpid=acct.awpid).first()

            if not identity:
                conflict = PatientIdentity.objects.using("default").filter(mobile_hash=mobile_hash).first()
                if conflict:
                    skipped_conflict += 1
                    self.stdout.write(self.style.ERROR(
                        f"  CONFLICT: {acct.awpid} ({acct.full_name}, mobile {acct.mobile}) has no identity row, and "
                        f"creating one would collide with existing identity {conflict.awpid} ({conflict.full_name}) — "
                        f"needs a human to sort out, not auto-fixed."
                    ))
                    continue

                created += 1
                self.stdout.write(
                    f"  {'[dry-run] ' if dry_run else ''}{acct.awpid} ({acct.full_name}): "
                    f"no PatientIdentity row at all — {'would create' if dry_run else 'creating'} one."
                )
                if not dry_run:
                    PatientIdentity.objects.using("default").create(
                        awpid=acct.awpid, full_name=acct.full_name, date_of_birth=acct.date_of_birth,
                        gender=acct.gender, mobile_hash=mobile_hash, email=acct.email or "",
                    )
                continue

            if identity.mobile_hash == mobile_hash:
                already_ok += 1
                continue

            conflict = PatientIdentity.objects.using("default").filter(mobile_hash=mobile_hash).exclude(pk=identity.pk).first()
            if conflict:
                skipped_conflict += 1
                self.stdout.write(self.style.ERROR(
                    f"  CONFLICT: {acct.awpid} ({acct.full_name}, mobile {acct.mobile}) would collide with "
                    f"identity {conflict.awpid} ({conflict.full_name}) — needs a human to sort out, not auto-fixed."
                ))
                continue

            fixed += 1
            self.stdout.write(
                f"  {'[dry-run] ' if dry_run else ''}{acct.awpid} ({acct.full_name}): "
                f"mobile_hash out of sync with current mobile {acct.mobile} — {'would fix' if dry_run else 'fixing'}."
            )
            if not dry_run:
                identity.mobile_hash = mobile_hash
                identity.save(using="default", update_fields=["mobile_hash"])

        self.stdout.write(self.style.SUCCESS(
            f"\n{'Would create' if dry_run else 'Created'} {created} missing identity row(s) — "
            f"{'would fix' if dry_run else 'fixed'} {fixed} stale hash(es) — already in sync: {already_ok} — "
            f"no mobile on file: {no_mobile} — skipped due to hash conflict: {skipped_conflict}."
        ))
