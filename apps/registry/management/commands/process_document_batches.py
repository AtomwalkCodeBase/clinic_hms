"""
process_document_batches
------------------------
Drains My Reports folder / multi-file uploads. Run every ~60 s from cron:

    * * * * *  cd /srv/hms && python manage.py process_document_batches

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

from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)

_PENDING_ITEM_STATES = ("uploading", "scanning")
_ITEM_MAX_BYTES = 20 * 1024 * 1024


class Command(BaseCommand):
    help = "Validate, classify and file every staged item in processing document-upload batches."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0,
                            help="Max items to process this run (0 = no limit).")

    def handle(self, *args, **opts):
        from apps.registry.models import DocumentUploadBatch

        limit = opts.get("limit") or 0
        done_items = 0
        batches = (DocumentUploadBatch.objects.using("default")
                   .filter(status="processing").order_by("created_at"))
        for batch in batches:
            items = batch.items.filter(status__in=_PENDING_ITEM_STATES).order_by("id")
            for item in items:
                if limit and done_items >= limit:
                    self.stdout.write(f"limit {limit} reached; {batch.id} left partial")
                    return
                self._process_item(item, batch)
                done_items += 1
            self._finalise(batch)
        self.stdout.write(f"processed {done_items} item(s)")

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

        if cr is not None and cr.confident:
            doc_type = cr.doc_type
            review_state = "filed"
            verification = "unverified"
        else:
            doc_type = "other"
            review_state = "unsorted"
            verification = "needs_review"
        method = (cr.method if cr is not None else "ocr_keyword")
        confidence = (cr.confidence if cr is not None else None)
        doc_date = (cr.doc_date if cr is not None else None)

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
            content_hash=content_hash, classification_method=method,
            classification_confidence=confidence, verification_status=verification,
            review_state=review_state, document_date=doc_date, batch=batch,
        )
        item.status = "filed" if review_state == "filed" else "unsorted"
        item.classified_as = doc_type if review_state == "filed" else "not_medical" if doc_type == "other" else doc_type
        item.content_hash = content_hash
        item.result_document = doc
        item.processed_at = timezone.now()
        item.save(using="default", update_fields=["status", "classified_as", "content_hash",
                                                  "result_document", "processed_at"])

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
        # 'ignored' was counted at manifest time (non-document extensions);
        # duplicates fold into 'ignored' for the patient-facing summary.
        batch.ignored = batch.ignored + sum(1 for s in items if s == "duplicate")
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
