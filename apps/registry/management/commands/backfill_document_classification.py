"""
backfill_document_classification
--------------------------------
One-time re-segregation of documents that already exist in My Reports.

The 0027 schema migration only adds columns (fast, safe, in a transaction).
Actually re-typing existing rows means fetching each file from S3 and running
the classifier — network + CPU work that must NOT live inside a migration.
This command does it out of band, and is safe to run repeatedly.

What it does, per existing registry.SharedDocument row that has not been
processed yet (classification_method == ""):

  * hospital-issued prescriptions / lab reports  (doc_type already set,
    source_tenant_id present)
        -> just stamped verification_status="verified",
           classification_method="staff". Already segregated; nothing moves.

  * patient uploads filed as "other" / "" / "scan"
        -> bytes fetched (S3 key, or inline data: URI for pre-S3 rows),
           doc_classifier.classify() run:
             confident   -> doc_type set to prescription | lab_report,
                            document_date filled if empty, review_state="filed"
             not confident -> left as-is; with --unsorted-low-confidence it is
                            moved to the Unsorted tray for a one-tap fix
        -> classification_method="ocr_keyword" recorded either way, so the row
           is not reprocessed on the next run.

Resumable: it only ever looks at classification_method == "". Use --limit to
process in chunks; the next run continues from where it stopped.

    python manage.py backfill_document_classification --dry-run
    python manage.py backfill_document_classification --limit 500
    python manage.py backfill_document_classification --awpid AWPID-...   # one patient
"""

import base64
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)

_NEEDS_TYPING = ("other", "", "scan")


class Command(BaseCommand):
    help = "Re-classify existing My Reports documents into Prescriptions / Lab reports."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would change; write nothing.")
        parser.add_argument("--limit", type=int, default=0,
                            help="Max rows to process this run (0 = all).")
        parser.add_argument("--awpid", type=str, default="",
                            help="Restrict to one patient (for testing).")
        parser.add_argument("--reclassify", action="store_true",
                            help="Also re-run on patient uploads already typed as "
                                 "prescription/lab_report (default: only 'other').")
        parser.add_argument("--unsorted-low-confidence", action="store_true",
                            help="Park rows the classifier is unsure about in the "
                                 "Unsorted tray instead of leaving them untouched.")

    def handle(self, *args, **opts):
        from apps.registry.models import SharedDocument
        from core import doc_classifier, file_validation
        from core import storage

        dry = opts["dry_run"]
        limit = opts["limit"] or 0
        park = opts["unsorted_low_confidence"]

        qs = SharedDocument.objects.using("default").filter(
            classification_method="", deleted_at__isnull=True,
        )
        if opts["awpid"]:
            qs = qs.filter(awpid=opts["awpid"])
        qs = qs.order_by("id")
        if limit:
            qs = qs[:limit]

        n_total = n_hospital = n_typed = n_low = n_skip = n_err = 0

        for doc in qs.iterator(chunk_size=200):
            n_total += 1
            hospital_issued = bool(doc.source_tenant_id) and doc.doc_type in ("prescription", "lab_report")

            # ── hospital-issued: already segregated, just mark verified ──
            if hospital_issued and not opts["reclassify"]:
                n_hospital += 1
                if not dry:
                    doc.classification_method = "staff"
                    doc.verification_status = "verified"
                    doc.save(using="default",
                             update_fields=["classification_method", "verification_status"])
                continue

            # ── decide whether this row needs re-typing ──
            if not opts["reclassify"] and doc.doc_type not in _NEEDS_TYPING:
                # a patient upload already typed prescription/lab_report — trust it
                if not dry:
                    doc.classification_method = "patient_confirmed"
                    doc.save(using="default", update_fields=["classification_method"])
                continue

            # ── fetch bytes ──
            try:
                raw = self._bytes_for(doc, storage)
            except Exception as exc:
                n_err += 1
                logger.warning("backfill: could not read doc %s: %s", doc.id, exc)
                if not dry:
                    doc.classification_method = "skip"
                    doc.save(using="default", update_fields=["classification_method"])
                continue

            try:
                mime = file_validation.validate_bytes(raw)
            except file_validation.FileValidationError:
                n_skip += 1
                if not dry:
                    doc.classification_method = "skip"
                    doc.save(using="default", update_fields=["classification_method"])
                continue

            # ── classify ──
            try:
                cr = doc_classifier.classify(raw, mime)
            except Exception:
                n_err += 1
                logger.exception("backfill: classify failed for doc %s", doc.id)
                continue

            fields = ["classification_method", "classification_confidence"]
            doc.classification_method = "ocr_keyword"
            doc.classification_confidence = cr.confidence
            if cr.doc_date and not doc.document_date:
                doc.document_date = cr.doc_date
                fields.append("document_date")

            if cr.collection_date and not doc.collection_date:
                doc.collection_date = cr.collection_date
                doc.date_source = cr.date_source
                fields += ["collection_date", "date_source"]

            if cr.confident and not cr.unreadable:
                n_typed += 1
                if doc.doc_type != cr.doc_type:
                    doc.doc_type = cr.doc_type
                    fields.append("doc_type")
                if doc.review_state != "filed":
                    doc.review_state = "filed"
                    fields.append("review_state")
                if cr.doc_type == "lab_report" and cr.categories and not doc.report_categories:
                    doc.report_categories = list(cr.categories)
                    doc.category_method = "keyword"
                    doc.category_confidence = cr.category_confidence
                    fields += ["report_categories", "category_method", "category_confidence"]
                cats = f"  [{', '.join(cr.categories)}]" if cr.categories else ""
                self.stdout.write(f"  {doc.id}: {doc.awpid}  ->  {cr.doc_type}{cats}  ({cr.confidence})")
            else:
                n_low += 1
                if park:
                    doc.review_state = "unsorted"
                    doc.verification_status = "needs_review"
                    fields += ["review_state", "verification_status"]

            if not dry:
                doc.save(using="default", update_fields=fields)

        prefix = "[dry-run] " if dry else ""
        self.stdout.write(
            f"{prefix}{n_total} scanned  |  {n_typed} re-typed  |  {n_low} low-confidence"
            f"{' (parked in Unsorted)' if park else ' (left as-is)'}  |  "
            f"{n_hospital} hospital-issued marked verified  |  {n_skip} unreadable/skipped  |  {n_err} errors"
        )
        if limit and n_total == limit:
            self.stdout.write("Hit --limit; re-run to continue.")

    # ------------------------------------------------------------------
    @staticmethod
    def _bytes_for(doc, storage):
        fd = doc.file_data or ""
        if fd.startswith("data:"):
            return base64.b64decode(fd.split(",", 1)[1])
        return storage.get_bytes(fd)
