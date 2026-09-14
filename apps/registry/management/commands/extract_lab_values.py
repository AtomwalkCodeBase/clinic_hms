"""
extract_lab_values
-------------------
Reads test values out of every already-filed lab_report SharedDocument that
hasn't been attempted yet — the async companion to core.doc_classifier
(which deliberately never does this; see its docstring) and a separate
concern from `process_document_batches` (that command drains newly-uploaded
files through classification; this one runs later, on documents already
confidently filed, regardless of which upload path produced them or when).

Run it on a cron tick (no --forever/daemon mode — unlike
process_document_batches, there's no local model to keep warm here, every
call is a remote HTTP request regardless of how long the process has been
resident):

    */10 * * * *  cd /srv/hms && python manage.py extract_lab_values

A Postgres advisory lock serialises drains, same pattern as
process_document_batches (distinct key — see _DRAIN_LOCK_KEY below) — an
overlapping cron tick no-ops instead of racing on the same document.

For each candidate document this:
  1. reads its stored bytes (S3 key or legacy base64 data URI)
  2. gets page text (PDF text layer, or OCR — reusing core.doc_classifier's
     own private but stable _pdf_text/_ocr_text helpers, and core.ocr's
     public pdf_page_images for the vision fallback)
  3. calls core.lab_value_extractor: text layer first, vision layer only if
     the text layer found nothing and the source text was thin
  4. stores every sanitised value found (even sub-threshold ones — the data
     stays honest/debuggable and feeds core/extractor_eval_corpus.py), and
     sets SharedDocument.extraction_status:
       done          — every stored value's confidence >= 0.7
       needs_review  — ran, but 0 values found, or at least one sub-threshold
       failed        — both extraction layers unavailable or errored

Deliberately excludes review_state="unsorted" documents — those are the
classification review tray's population (wrong type/panel/date, unresolved
by core.doc_classifier), a non-overlapping concern from value extraction,
which only ever runs on documents already confidently filed.

Idempotent: only extraction_status="not_attempted" rows are queried, so a
crashed mid-pass run is safe to re-run — it just picks up where it left off.

Known gap: if a patient later corrects a document's classification via the
existing review-tray PATCH flow (PortalDocumentDetailView.patch()),
extraction_status is never reset, so that document is never re-attempted.
Not fixed here — a future --retry flag is the natural fast-follow.
"""

import base64 as _b64
import logging

from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

logger = logging.getLogger(__name__)

# Arbitrary but stable 64-bit key for pg_advisory_lock — only this command
# uses it. "rdlv" = registry document lab-values (distinct from
# process_document_batches' 0x7264_6274, "rdbt").
_DRAIN_LOCK_KEY = 0x7264_6C76

_CONFIDENCE_GATE = 0.7


class Command(BaseCommand):
    help = "Extract structured lab test values from every filed lab_report not yet attempted."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50,
                            help="Max documents to process per drain pass.")

    def handle(self, *args, **opts):
        n = self._drain(opts["limit"])
        self.stdout.write(f"processed {n} document(s)")

    # --------------------------------------------------------------- drain
    def _drain(self, limit):
        from apps.registry.models import SharedDocument

        with connection.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", [_DRAIN_LOCK_KEY])
            got = cur.fetchone()[0]
        if not got:
            self.stdout.write("another drain holds the lock; skipping this pass")
            return 0

        done = 0
        try:
            docs = (SharedDocument.objects.using("default")
                    .filter(doc_type="lab_report", review_state="filed",
                            hidden_at__isnull=True, deleted_at__isnull=True,
                            extraction_status="not_attempted")
                    .order_by("created_at")[:limit])
            for doc in docs:
                try:
                    self._process_document(doc)
                except Exception:
                    logger.exception("extract_lab_values: doc %s crashed; marking failed", doc.id)
                    doc.extraction_status = "failed"
                    doc.extracted_at = timezone.now()
                    doc.save(using="default", update_fields=["extraction_status", "extracted_at"])
                done += 1
        finally:
            with connection.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", [_DRAIN_LOCK_KEY])
        return done

    # ---------------------------------------------------------------- item
    def _process_document(self, doc):
        from apps.registry.models import ExtractedLabValue
        from core import doc_classifier, lab_value_extractor, lab_variation, ocr, storage as blob_storage

        raw = doc.file_data or ""
        try:
            content = (_b64.b64decode(raw.split(",", 1)[1]) if raw.startswith("data:")
                       else blob_storage.get_bytes(raw))
        except Exception:
            logger.warning("extract_lab_values: doc %s — cannot read stored bytes", doc.id, exc_info=True)
            self._mark(doc, status="failed")
            return

        text = ""
        try:
            if doc.mime_type == "application/pdf":
                text = doc_classifier._pdf_text(content)
            if len(text.strip()) < 40:   # thin/absent — OCR it (handles image-only PDFs too)
                ocr_text, _conf = doc_classifier._ocr_text(content, doc.mime_type)
                text = ocr_text or text
        except Exception:
            logger.warning("extract_lab_values: doc %s — text extraction failed", doc.id, exc_info=True)

        # "values" present in the returned dict (even as []) means the layer
        # actually ran and answered — absent means it was disabled or the
        # call errored (lab_value_extractor never raises, see its docstring).
        # This distinguishes "ran fine, found nothing" (needs_review) from
        # "never got a real answer from either layer" (failed).
        text_result = lab_value_extractor.extract_text(text, doc.report_categories)
        text_ok = "values" in text_result
        values = text_result.get("values") or []
        method = "text_llm" if text_ok else ""

        vision_ok = False
        if not values and (not text_ok or len(text.strip()) < 40):
            try:
                images = ocr.pdf_page_images(content, max_pages=2) if doc.mime_type == "application/pdf" else [content]
            except Exception:
                images = []
            if images:
                vision_result = lab_value_extractor.extract_images(images, doc.report_categories)
                vision_ok = "values" in vision_result
                if vision_ok:
                    values = vision_result.get("values") or []
                    method = "vision_llm"

        if not values:
            status = "needs_review" if (text_ok or vision_ok) else "failed"
            self._mark(doc, status=status, method=method)
            return

        eff_date = doc.document_date or (doc.created_at.date() if doc.created_at else None)
        rows = [
            ExtractedLabValue(
                document=doc, awpid=doc.awpid, document_date=eff_date,
                parameter_slug=lab_variation.parameter_slug(v["parameter"]), parameter_label=v["parameter"],
                value_numeric=v["value"], unit=v["unit"],
                reference_range_text=v["reference_range_text"],
                confidence=v["confidence"], extraction_method=method,
            )
            for v in values
        ]
        ExtractedLabValue.objects.using("default").bulk_create(rows)

        confident = sum(1 for v in values if v["confidence"] >= _CONFIDENCE_GATE)
        status = "done" if confident == len(values) else "needs_review"
        doc.extraction_status = status
        doc.extraction_method = method
        doc.extraction_values_total = len(values)
        doc.extraction_values_confident = confident
        doc.extracted_at = timezone.now()
        doc.save(using="default", update_fields=[
            "extraction_status", "extraction_method", "extraction_values_total",
            "extraction_values_confident", "extracted_at",
        ])

    def _mark(self, doc, *, status, method=""):
        doc.extraction_status = status
        doc.extraction_method = method
        doc.extracted_at = timezone.now()
        doc.save(using="default", update_fields=["extraction_status", "extraction_method", "extracted_at"])
