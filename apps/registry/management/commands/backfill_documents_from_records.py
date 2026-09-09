"""
backfill_documents_from_records
-------------------------------
Mirrors EXISTING prescriptions and delivered lab reports into the My Reports
document vault (registry.SharedDocument), so they show for the patient
alongside anything they upload. Type is known (the HMS wrote the record), so
these rows are created verification_status="verified", review_state="filed" —
no classification needed.

New records already mirror automatically:
  - prescriptions  -> apps/opd/views.EncounterSignView (on sign)
  - lab reports     -> apps/lab/signals.on_report_delivered

This command is the one-time catch-up for everything that predates that.
Run it once after deploy:

    python manage.py backfill_documents_from_records --dry-run
    python manage.py backfill_documents_from_records --limit 500
    python manage.py backfill_documents_from_records

Idempotent and resumable — each prescription / lab report is skipped once a
SharedDocument with its source_ref ("encounter:<id>" / "labreport:<id>")
exists, so a partial run just continues on the next invocation.
"""

import logging

from django.conf import settings
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Mirror existing prescriptions and lab reports into the My Reports vault."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report counts; write nothing.")
        parser.add_argument("--limit", type=int, default=0, help="Max rows to mirror this run (0 = all).")
        parser.add_argument("--tenant", default="", help="Restrict to one tenant db_name.")
        parser.add_argument("--kind", choices=["prescription", "lab_report", "all"], default="all")

    def handle(self, *args, **opts):
        from apps.tenants.models import Tenant
        from apps.tenants.utils import _make_db_config

        dry = opts["dry_run"]
        limit = opts["limit"] or 0
        kind = opts["kind"]
        n = {"rx": 0, "lab": 0, "skip": 0, "err": 0}

        tenants = Tenant.objects.using("default").filter(is_active=True)
        if opts["tenant"]:
            tenants = tenants.filter(db_name=opts["tenant"])

        for t in tenants:
            db = t.db_name
            if db and db not in settings.DATABASES:
                settings.DATABASES[db] = _make_db_config(db)
            if limit and (n["rx"] + n["lab"]) >= limit:
                break
            if kind in ("prescription", "all"):
                self._prescriptions(db, t.id, dry, limit, n)
            if kind in ("lab_report", "all") and not (limit and (n["rx"] + n["lab"]) >= limit):
                self._lab_reports(db, t.id, dry, limit, n)

        prefix = "[dry-run] " if dry else ""
        self.stdout.write(
            f"{prefix}mirrored {n['rx']} prescription(s), {n['lab']} lab report(s)  |  "
            f"{n['skip']} already present  |  {n['err']} errors"
        )
        if limit and (n["rx"] + n["lab"]) >= limit:
            self.stdout.write("Hit --limit; re-run to continue.")

    # ------------------------------------------------------------------
    def _prescriptions(self, db, tenant_id, dry, limit, n):
        from apps.opd.models import Prescription
        from apps.registry.models import SharedDocument
        from apps.opd.archive import store_prescription_document

        try:
            qs = Prescription.objects.using(db).all().order_by("id")
        except Exception:
            logger.warning("backfill: %s has no opd_prescription table; skipping", db)
            return
        for rx in qs.iterator(chunk_size=100):
            if limit and (n["rx"] + n["lab"]) >= limit:
                return
            already = SharedDocument.objects.using("default").filter(
                source_ref=f"encounter:{rx.encounter_id}").exists()
            if dry:
                n["skip" if already else "rx"] += 1
                continue
            try:
                res = store_prescription_document(rx, db, tenant_id)  # creates OR self-heals
                if res is None:
                    continue
                if already:
                    n["skip"] += 1
                else:
                    n["rx"] += 1
                    self.stdout.write(f"  rx  {rx.rx_number or rx.id}")
            except Exception:
                logger.exception("backfill: prescription %s in %s", rx.id, db)
                n["err"] += 1

    def _lab_reports(self, db, tenant_id, dry, limit, n):
        from apps.lab.models import LabReport
        from apps.registry.models import SharedDocument
        from apps.lab.archive import store_lab_report_document

        try:
            qs = LabReport.objects.using(db).filter(status="delivered").order_by("id")
        except Exception:
            logger.warning("backfill: %s has no lab_report table; skipping", db)
            return
        for r in qs.iterator(chunk_size=100):
            if limit and (n["rx"] + n["lab"]) >= limit:
                return
            already = SharedDocument.objects.using("default").filter(
                source_ref=f"labreport:{r.id}").exists()
            if dry:
                n["skip" if already else "lab"] += 1
                continue
            try:
                res = store_lab_report_document(r, db, tenant_id)  # creates OR self-heals
                if res is None:
                    continue
                if already:
                    n["skip"] += 1
                else:
                    n["lab"] += 1
                    self.stdout.write(f"  lab {r.report_number or r.id}")
            except Exception:
                logger.exception("backfill: lab report %s in %s", r.id, db)
                n["err"] += 1
