"""
process_document_batches
------------------------
Drains My Reports folder / multi-file uploads.

Two ways to run it:

  * one-shot (cron) — a single drain pass, then exit:
        * * * * *  cd /srv/hms && python manage.py process_document_batches

  * daemon (recommended) — stays resident so the OCR model loads once and
    stays warm, no per-run cold start, no overlapping runs:
        python manage.py process_document_batches --forever --interval 5
    (run under systemd / supervisor with Restart=always — see
    docs/MY_REPORTS_DEPLOY.md).

Either way a Postgres advisory lock serialises drains: a second invocation
(a cron tick firing while the previous run is still going, or a stray second
daemon) no-ops instead of racing on the same item.

For each DocumentUploadBatch in status 'processing', and each of its items
still pending, this:
  1. reads the staged object from S3 (incoming/…)
  2. verifies the real magic bytes (PDF / JPEG / PNG) and the 20 MB cap
  3. de-duplicates against the patient's existing documents (content hash)
  4. classifies it (page text / OCR) into prescription | lab_report | unsorted
  5. normalises it to a PDF and writes it to patients/…
  6. creates the SharedDocument row and updates the batch counters

Nothing is deleted: unrecognised files become 'unsorted' SharedDocument rows
for the patient to confirm; only genuinely broken / oversize / infected files
end as item.status='failed' with no row. Staged objects in incoming/ are left
for the bucket's 24 h lifecycle rule to clean up.

Idempotent: an item already past 'scanning' is skipped, so a crashed run can
be re-run safely.
"""

import base64
import hashlib
import logging
import signal
import time

from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

logger = logging.getLogger(__name__)

_PENDING_ITEM_STATES = ("uploading", "scanning")
_ITEM_MAX_BYTES = 20 * 1024 * 1024

# Arbitrary but stable 64-bit key for pg_advisory_lock — only this command
# uses it. "rdbt" = registry document batches.
_DRAIN_LOCK_KEY = 0x7264_6274


class Command(BaseCommand):
    help = "Validate, classify and file every staged item in processing document-upload batches."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0,
                            help="Max items to process per drain pass (0 = no limit).")
        parser.add_argument("--forever", action="store_true",
                            help="Run as a resident daemon: drain, sleep, repeat "
                                 "(keeps the OCR model warm). Use under systemd/supervisor.")
        parser.add_argument("--interval", type=float, default=5.0,
                            help="--forever only: seconds to sleep between drain passes.")

    def handle(self, *args, **opts):
        limit = opts.get("limit") or 0
        if not opts.get("forever"):
            n = self._drain(limit)
            self.stdout.write(f"processed {n} item(s)")
            return
        self._run_forever(limit, max(0.5, opts.get("interval") or 5.0))

    # --------------------------------------------------------------- daemon
    def _run_forever(self, limit, interval):
        stop = {"flag": False}

        def _sig(_signum, _frame):
            stop["flag"] = True

        # SIGTERM is what systemd sends on `stop`; SIGINT is Ctrl-C; SIGBREAK
        # is the Windows-console equivalent. Registering is harmless where a
        # given signal can't actually be delivered.
        for _name in ("SIGTERM", "SIGINT", "SIGBREAK"):
            _s = getattr(signal, _name, None)
            if _s is not None:
                try:
                    signal.signal(_s, _sig)
                except (ValueError, OSError):
                    pass

        # Warm the OCR model, but never let a misbehaving load wedge the
        # daemon — if it's not done in 45 s, start draining anyway and let the
        # first real item trigger the (lazy) load.
        try:
            from core import ocr
            import threading as _t
            self.stdout.write(f"warming OCR ({ocr.available()}) ...", ending="\n")
            self.stdout.flush()
            w = _t.Thread(target=ocr.warmup, name="ocr-warmup", daemon=True)
            w.start()
            w.join(45)
            self.stdout.write("warm" if not w.is_alive() else "warmup still running; draining anyway")
        except Exception:
            logger.warning("process_document_batches: OCR warmup failed", exc_info=True)

        msg = f"daemon up - interval {interval}s, limit {limit or 'unlimited'}"
        self.stdout.write(msg)
        self.stdout.flush()
        logger.info("process_document_batches %s", msg)
        while not stop["flag"]:
            try:
                connection.close_if_unusable_or_obsolete()
                self._drain(limit)
            except Exception:
                logger.exception("process_document_batches: drain pass failed; continuing")
            slept = 0.0
            while slept < interval and not stop["flag"]:
                time.sleep(0.1)
                slept += 0.1
        self.stdout.write("daemon stopped")
        self.stdout.flush()
        logger.info("process_document_batches daemon stopped")

    # --------------------------------------------------------------- drain
    def _drain(self, limit):
        """
        One pass over every batch in status 'processing'. Guarded by a PG
        advisory lock: if another drain already holds it, this call no-ops
        (returns 0) instead of double-processing items. The lock is session-
        scoped, so it auto-releases if the process is killed mid-pass.
        """
        from apps.registry.models import DocumentUploadBatch

        with connection.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", [_DRAIN_LOCK_KEY])
            got = cur.fetchone()[0]
        if not got:
            self.stdout.write("another drain holds the lock; skipping this pass")
            return 0

        done_items = 0
        try:
            batches = (DocumentUploadBatch.objects.using("default")
                       .filter(status="processing").order_by("created_at"))
            for batch in batches:
                items = batch.items.filter(status__in=_PENDING_ITEM_STATES).order_by("id")
                for item in items:
                    if limit and done_items >= limit:
                        self.stdout.write(f"limit {limit} reached; {batch.id} left partial")
                        return done_items
                    self._process_item(item, batch)
                    done_items += 1
                self._finalise(batch)
        finally:
            with connection.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", [_DRAIN_LOCK_KEY])
        return done_items

    # ------------------------------------------------------------------ item
    def _process_item(self, item, batch):
        from apps.registry.models import SharedDocument
        from core import storage, normalise, doc_classifier, file_validation

        item.status = "scanning"
        item.save(using="default", update_fields=["status"])

        try:
            raw = storage.get_bytes(item.staging_key)
        except Exception:
            logger.exception("batch %s item %s: cannot read staged object", batch.id, item.id)
            return self._fail(item, "Upload not found in storage.")

        if len(raw) > _ITEM_MAX_BYTES:
            return self._fail(item, "File is over the 20 MB limit.")

        try:
            mime_type = file_validation.validate_bytes(raw)
        except file_validation.FileValidationError as exc:
            return self._fail(item, str(exc))

        # TODO(hook): virus scan `raw` here before it is copied out of incoming/.

        content_hash = hashlib.sha256(raw).hexdigest()

        dup = (SharedDocument.objects.using("default")
               .filter(awpid=batch.awpid, deleted_at__isnull=True, content_hash=content_hash)
               .first())
        if dup is not None:
            item.status = "duplicate"
            item.content_hash = content_hash
            item.result_document = dup
            item.processed_at = timezone.now()
            item.save(using="default", update_fields=["status", "content_hash", "result_document", "processed_at"])
            return

        # classify on the ORIGINAL bytes, then normalise to PDF
        try:
            cr = doc_classifier.classify(raw, mime_type)
        except Exception:
            logger.exception("batch %s item %s: classify failed", batch.id, item.id)
            cr = None

        # Clearly not a medical document (an invoice, an ID, a boarding pass):
        # do NOT store it. No SharedDocument row — just record why it was
        # skipped so the patient's summary can say "N files weren't medical".
        if cr is not None and getattr(cr, "non_medical", False):
            item.status = "ignored"
            item.classified_as = "not_medical"
            item.reason = "Not a medical document — skipped."
            item.content_hash = content_hash
            item.processed_at = timezone.now()
            item.save(using="default", update_fields=["status", "classified_as",
                                                      "reason", "content_hash", "processed_at"])
            return

        report_categories = []
        category_method = ""
        category_confidence = None
        collection_date = None
        date_source = ""
        if cr is not None and not cr.unreadable and cr.confident:
            doc_type = cr.doc_type
            review_state = "filed" if not cr.needs else "unsorted"
            verification = "unverified" if not cr.needs else "needs_review"
            if cr.doc_type == "lab_report":
                report_categories = list(cr.categories)
                category_confidence = cr.category_confidence
                category_method = "keyword" if cr.method == "ocr_keyword" else cr.method
        else:
            doc_type = "other"
            review_state = "unsorted"
            verification = "needs_review"
        method = (cr.method if cr is not None else "ocr_keyword")
        confidence = (cr.confidence if cr is not None else None)
        doc_date = (cr.doc_date if cr is not None else None)
        if cr is not None:
            collection_date = cr.collection_date
            date_source = cr.date_source

        try:
            pdf_bytes, stored_mime = normalise.to_pdf(raw, mime_type)
        except Exception:
            logger.exception("batch %s item %s: normalise failed; storing original", batch.id, item.id)
            pdf_bytes, stored_mime = raw, mime_type

        # Same key layout as the single-upload path (core.storage.upload_data_uri):
        #   patient-documents/<name-slug-awpid>/patient-document-<hex>.<ext>
        # The DB (SharedDocument.doc_type) is the source of truth for type;
        # the S3 path is only for human browsing, so it is NOT split by type.
        slug = storage.identity_slug(name="", identifier=batch.awpid) or batch.awpid
        ext = "pdf" if stored_mime == "application/pdf" else stored_mime.split("/")[-1]
        final_key = f"patient-documents/{slug}/patient-document-{item.id.hex[:16]}.{ext}"
        try:
            storage.put_bytes(final_key, pdf_bytes, mime_type=stored_mime)
        except Exception:
            logger.exception("batch %s item %s: S3 put failed", batch.id, item.id)
            return self._fail(item, "Could not save the file. Try again.")

        title = _title_for(doc_type, item.original_filename)
        file_name = storage.display_file_name("patient-document", stored_mime, detail=title, identifier=batch.awpid)
        doc = SharedDocument.objects.using("default").create(
            awpid=batch.awpid, title=title, doc_type=doc_type,
            file_name=file_name, mime_type=stored_mime, file_data=final_key,
            uploaded_by="patient", source_tenant_id=None,
            review_notes=(cr.quality_message if (cr is not None and cr.unreadable) else ""),
            content_hash=content_hash, classification_method=method,
            classification_confidence=confidence, verification_status=verification,
            review_state=review_state, document_date=doc_date, batch=batch,
            collection_date=collection_date, date_source=date_source,
            report_categories=report_categories, category_method=category_method,
            category_confidence=category_confidence,
        )
        item.status = "filed" if review_state == "filed" else "unsorted"
        if review_state == "filed":
            item.classified_as = doc_type
            item.reason = ""
        elif cr is not None and cr.unreadable:
            item.classified_as = "unreadable"
            item.reason = (cr.quality_message or "We couldn't read this document.")[:160]
        else:
            item.classified_as = doc_type          # "other" / a low-confidence guess
            item.reason = "We couldn't classify this confidently — please check its type and date."
        item.content_hash = content_hash
        item.result_document = doc
        item.processed_at = timezone.now()
        item.save(using="default", update_fields=["status", "classified_as", "reason",
                                                  "content_hash", "result_document", "processed_at"])

    def _fail(self, item, reason):
        item.status = "failed"
        item.reason = reason[:160]
        item.processed_at = timezone.now()
        item.save(using="default", update_fields=["status", "reason", "processed_at"])

    # --------------------------------------------------------------- finalise
    def _finalise(self, batch):
        items = list(batch.items.values_list("status", flat=True))
        if any(s in _PENDING_ITEM_STATES for s in items):
            return  # still work left
        batch.accepted = sum(1 for s in items if s == "filed")
        batch.unsorted = sum(1 for s in items if s == "unsorted")
        batch.failed = sum(1 for s in items if s == "failed")
        # 'ignored' starts with the manifest-time count (non-document
        # extensions / oversize). Add the runtime skips: exact duplicates and
        # files the classifier judged non-medical.
        batch.ignored = batch.ignored + sum(1 for s in items if s in ("duplicate", "ignored"))
        batch.status = "partial" if batch.failed else "done"
        batch.finished_at = timezone.now()
        batch.save(using="default", update_fields=["accepted", "unsorted", "failed",
                                                   "ignored", "status", "finished_at"])
        self.stdout.write(f"batch {batch.id}: {batch.accepted} filed, {batch.unsorted} unsorted, "
                          f"{batch.failed} failed, {batch.ignored} ignored")


def _title_for(doc_type, filename):
    if doc_type == "prescription":
        return "Prescription"
    if doc_type == "lab_report":
        return "Lab report"
    return (filename or "Uploaded document")[:200]
