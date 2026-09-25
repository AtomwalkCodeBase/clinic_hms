"""
apps/patients/portal_extraction_views.py
-----------------------------------------
Mobile document upload — extraction-only phase.

Deliberately separate from PortalDocumentListCreateView (portal_views.py,
still used unchanged by web + will keep being used by web) and from
PortalDocumentBatchView (the unrelated, zero-traffic web folder-upload
feature). This flow reads the text (OCR/pypdf) and saves it on an ExtractionItem. Once a
file has been read, extraction.file_into_reports() hands the text to a
shared_document row, where the same keyword rules and AI check as any other
My Reports upload take over. That is the second status the phone shows after
"Read": each item in the list/detail answers below carries `ai`
(queued | running | done | failed | skipped | none) taken from that row.

Two paths, split by file count — the same instant/bulk split the My Reports
pipeline uses (core/pipeline/routing.py). The threshold is the "Sort instantly up
to" setting on platform admin -> Background Jobs (instant_max_files, default 3);
the app reads it from the config endpoint and this module re-validates it:

  GET  /api/v1/portal/documents/extract/config/
      the limits the app needs before it chooses a path.

  POST /api/v1/portal/documents/extract/sync/
      up to instant_max_files files, processed inline, response has the text directly.

  POST /api/v1/portal/documents/extract/bulk/
  POST /api/v1/portal/documents/extract/bulk/<batch_id>/start/
  GET  /api/v1/portal/documents/extract/bulk/<batch_id>/status/
      bigger uploads: presigned-S3 upload, then the batch waits "queued" in the database
      until the scheduled job "Process mobile bulk uploads" reads it (apps/registry/tasks.py),
      or — if Celery isn't running — the web server reads it (bulk_fallback). Polled for progress.
"""

import base64
import io
import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction

from rest_framework.views import APIView

from core.permissions import IsPatient
from core.response import success, error
from core.file_validation import validate_data_uri, validate_bytes, FileValidationError
from core import storage as blob_storage
from apps.registry.models import PatientAccount
from apps.patients.portal_views import _resolve_target_awpid_and_dob

logger = logging.getLogger(__name__)

# ── caps (distinct from the unrelated batch feature's _ITEM_MAX_BYTES etc.) ──
# Per-file size / page caps and the S3 key layout live in apps/registry/extraction.py,
# shared with the Celery task so both paths enforce exactly the same rules.
from apps.registry.extraction import (
    TYPE_MAX_BYTES as _TYPE_MAX_BYTES, EXT_BY_MIME as _EXT_BY_MIME, UPLOAD_URL_TTL,
    file_key_for, validate_size_and_pages, fail_item, run_extraction, size_problem, ai_map, AI_NONE,
)

_BULK_MAX_FILES = 50


def _instant_max() -> int:
    """Largest upload that is read inside the request. One setting for the whole pipeline (Background Jobs -> Settings)."""
    from core import celery_runtime as rt
    return int(rt.config().instant_max_files or 3)


def _target_identity(request):
    """(target_awpid, target_full_name, error_response_or_None). See _target_identity_full for the acct's own awpid too."""
    target_awpid, full_name, acct_awpid, err = _target_identity_full(request)
    return target_awpid, full_name, err


def _target_identity_full(request):
    """(target_awpid, target_full_name, logged_in_account_awpid, error_response_or_None)."""
    acct = PatientAccount.objects.using("default").get(pk=request.user.id)
    target_awpid, _dob, err = _resolve_target_awpid_and_dob(request)
    if err:
        return None, None, None, err
    if target_awpid == acct.awpid:
        return target_awpid, acct.full_name, acct.awpid, None
    from apps.registry.models import PatientIdentity
    identity = PatientIdentity.objects.using("default").filter(awpid=target_awpid).first()
    return target_awpid, (identity.full_name if identity else acct.full_name), acct.awpid, None


class PortalExtractSyncView(APIView):
    """
    POST body: { files: [{file_name, mime_type, file_data}, ...], patient_awpid? }
    Up to instant_max_files files, processed inline. Every file is tracked as
    an ExtractionItem; a file that passes validation is kept in S3
    (file_key) and then extracted, one that fails validation is recorded
    with the reason and NOT kept. Extraction only — no classification, no
    SharedDocument row, not visible in My Reports.
    """
    permission_classes = [IsPatient]

    def post(self, request):
        from django.utils import timezone
        from apps.registry.models import ExtractionItem

        target_awpid, target_full_name, err = _target_identity(request)
        if err:
            return err

        files = request.data.get("files") or []
        if not isinstance(files, list) or not files:
            return error("files list is required.")
        instant_max = _instant_max()
        if len(files) > instant_max:
            return error(f"Instant upload accepts at most {instant_max} files — use bulk upload for more.")

        slug = blob_storage.identity_slug(name=target_full_name, identifier=target_awpid)
        results = []
        for f in files:
            file_name = str((f or {}).get("file_name") or "").strip()[:255]
            file_data = (f or {}).get("file_data") or ""
            row = {"item_id": None, "file_name": file_name, "status": "failed",
                   "text": "", "confidence": None, "reason": ""}

            def reject(reason, mime="", size=0):
                """Record the attempt, keep nothing."""
                it = ExtractionItem.objects.using("default").create(
                    batch=None, awpid=target_awpid, original_filename=file_name, mime_type=mime,
                    declared_size=size, file_size=size, status="failed", reason=reason[:160],
                    processed_at=timezone.now(),
                )
                row.update(item_id=str(it.id), reason=reason)
                results.append(row)

            # ── 1. validate (type by magic bytes, size, pages) ──
            try:
                mime_type = validate_data_uri(file_data)
                raw = base64.b64decode(file_data.split(",", 1)[1])
            except FileValidationError as exc:
                reject(str(exc))
                continue
            except Exception:
                reject("Couldn't read this file.")
                continue
            problem = validate_size_and_pages(raw, mime_type)
            if problem:
                reject(problem, mime_type, len(raw))
                continue

            # ── 2. keep the validated file in S3 ──
            # Created already claimed (processing, attempt 1) — same ownership rule the
            # worker follows, so run_extraction/fail_item work identically on both paths.
            item = ExtractionItem.objects.using("default").create(
                batch=None, awpid=target_awpid, original_filename=file_name, mime_type=mime_type,
                declared_size=len(raw), file_size=len(raw), status="processing",
                attempts=1, started_at=timezone.now(),
            )
            key = file_key_for(slug, item.id, mime_type)
            try:
                blob_storage.put_bytes(key, raw, mime_type=mime_type)
            except Exception:
                logger.exception("could not store extraction file for item %s", item.id)
                fail_item(item, "Couldn't save the file. Please try again.")
                row.update(item_id=str(item.id), reason=item.reason)
                results.append(row)
                continue
            item.file_key = key
            item.save(using="default", update_fields=["file_key"])

            # ── 3. extract (JSON + text saved on the item) ──
            ok = run_extraction(item, raw, mime_type)
            row.update(item_id=str(item.id), status=item.status, reason=item.reason)
            if ok:
                row.update(text=item.extracted_text, confidence=item.extraction_confidence)
            results.append(row)

        return success(data={"results": results}, status=200)


class PortalExtractBulkCreateView(APIView):
    """
    POST body: { files: [{name, size, mime_type}, ...], patient_awpid? }
    3-50 files. Creates an ExtractionBatch + one ExtractionItem per file and
    returns a presigned S3 PUT url for each. The phone uploads straight to
    that permanent key (extraction-files/…, same layout as the instant path);
    the worker validates it afterwards and deletes it again if it's invalid.
    """
    permission_classes = [IsPatient]

    def post(self, request):
        from django.conf import settings
        from apps.registry.models import ExtractionBatch, ExtractionItem
        from apps.registry.tasks import reconcile_stale_batches

        target_awpid, target_full_name, acct_awpid, err = _target_identity_full(request)
        if err:
            return err

        files = request.data.get("files") or []
        if not isinstance(files, list) or not files:
            return error("files list is required.")
        # No minimum: the app chooses the path from the live instant_max_files setting, which an admin can
        # change between that choice and this call — a small batch is harmless, so don't turn it away.
        if len(files) > _BULK_MAX_FILES:
            return error(f"Too many files. Upload at most {_BULK_MAX_FILES} at a time.")

        # Close out anything that can't make progress (abandoned upload, stalled worker) —
        # never a healthy batch — so it doesn't block this patient forever.
        reconcile_stale_batches(target_awpid)
        if (ExtractionBatch.objects.using("default")
                .filter(awpid=target_awpid, status__in=ExtractionBatch.ACTIVE_STATUSES).exists()):
            return error("You already have an upload in progress. Please wait for it to finish.")

        # One bad file must not sink the rest: files that can't be accepted are left out and reported
        # back in `skipped`; everything else goes ahead. Only when NOTHING is acceptable is the whole
        # request refused. `index` is the file's position in the request, so the phone can match each
        # upload link to the right file even though some files were skipped.
        accepted, skipped, total_bytes = [], [], 0
        for index, f in enumerate(files):
            name = str((f or {}).get("name") or "").strip()
            try:
                size = int((f or {}).get("size") or 0)
            except (TypeError, ValueError):
                size = 0
            mime_type = str((f or {}).get("mime_type") or "").strip()
            if mime_type not in _EXT_BY_MIME:
                skipped.append({"index": index, "name": name, "reason": "Only PDF, JPG and PNG files are accepted."})
                continue
            cap = _TYPE_MAX_BYTES.get(mime_type)
            if cap and size > cap:
                skipped.append({"index": index, "name": name, "reason": f"Over the {cap // (1024 * 1024)} MB limit for this file type."})
                continue
            total_bytes += size
            accepted.append({"index": index, "name": name, "size": size, "mime_type": mime_type})

        if not accepted:
            first = skipped[0]
            return error(f'None of these files can be uploaded. "{first["name"]}": {first["reason"]}')

        batch_cap = getattr(settings, "EXTRACTION_BATCH_MAX_BYTES", 175 * 1024 * 1024)
        if total_bytes > batch_cap:
            return error(f"This selection is over the {batch_cap // (1024 * 1024)}MB per-batch limit. Split it into two.")

        slug = blob_storage.identity_slug(name=target_full_name, identifier=target_awpid)
        out = []
        # All-or-nothing: a failure part-way must not leave an empty batch behind (it would block the
        # patient's next bulk upload until cleanup closes it).
        with transaction.atomic(using="default"):
            batch = ExtractionBatch.objects.using("default").create(
                awpid=target_awpid, initiated_by_awpid=acct_awpid, total_files=len(accepted), status="pending",
            )
            for a in accepted:
                item = ExtractionItem.objects.using("default").create(
                    batch=batch, awpid=target_awpid, original_filename=a["name"],
                    mime_type=a["mime_type"], declared_size=a["size"], status="uploading",
                )
                key = file_key_for(slug, item.id, a["mime_type"])
                item.file_key = key
                item.save(using="default", update_fields=["file_key"])
                out.append({
                    "index": a["index"],
                    "item_id": str(item.id),
                    "filename": a["name"],
                    "put_url": blob_storage.presigned_put_url(key, mime_type=a["mime_type"], expires_in=UPLOAD_URL_TTL),
                    "content_type": a["mime_type"],
                })
        return success(data={"batch_id": str(batch.id), "items": out, "skipped": skipped}, status=201)


class PortalExtractBulkStartView(APIView):
    """
    POST .../bulk/<batch_id>/start/ — the phone says "I've uploaded what I could".

    The server does NOT take that on trust: it checks each expected object in S3
    (present? within the size cap?), fails the ones that never arrived, queues
    only the ones that did, and rejects the request if nothing arrived.

    Nothing is sent to a queue: the batch simply waits "queued" in the database and
    the scheduled job "Process mobile bulk uploads" reads it (the same way My Reports
    bulk uploads wait for their job). If Celery isn't running, bulk_fallback reads it
    inside the web server instead. So Start no longer depends on Redis being up.

    Idempotent: only the request that wins the pending -> queued update
    continues; a repeat (double tap, retry after a timeout) just reports the
    batch's current state. If S3 can't be checked the batch goes back to
    "pending" with its files kept, so the phone can simply call Start again —
    nothing is re-uploaded.
    """
    permission_classes = [IsPatient]

    def post(self, request, batch_id):
        from django.utils import timezone
        from apps.registry.models import ExtractionBatch, ExtractionItem
        from apps.registry.tasks import abort_batch, bulk_fallback, _finalise_if_done

        target_awpid, _name, err = _target_identity(request)
        if err:
            return err

        batches = ExtractionBatch.objects.using("default")
        batch = batches.filter(pk=batch_id, awpid=target_awpid).first()
        if not batch:
            return error("Batch not found.", status=404)

        def current():
            return success(data={"batch_id": str(batch.id), "status": batches.get(pk=batch.pk).status})

        if batch.status != "pending":
            return current()
        now = timezone.now()
        won = batches.filter(pk=batch.pk, status="pending").update(
            status="queued", queued_at=now, last_progress_at=now, start_failed_at=None)
        if not won:                      # another request claimed it a moment ago
            return current()

        def back_to_pending():
            batches.filter(pk=batch.pk).update(status="pending", queued_at=None, start_failed_at=timezone.now())
            return error("Processing is temporarily unavailable. Please try again in a moment.", status=503)

        # ── check what actually reached S3 ──
        items = ExtractionItem.objects.using("default")
        try:
            # HEAD every object concurrently — one round-trip each, so doing 50 in a row
            # would keep this request (and a gunicorn worker) busy for many seconds.
            from concurrent.futures import ThreadPoolExecutor
            waiting = list(batch.items.filter(status="uploading"))
            with ThreadPoolExecutor(max_workers=8) as pool:
                sizes = list(pool.map(lambda w: blob_storage.head_size(w.file_key), waiting))
            for it, size in zip(waiting, sizes):
                problem = None if size is not None else "Upload didn't finish. Please upload this file again."
                if size is not None:
                    problem = size_problem(size, it.mime_type)
                if problem:
                    if size is not None:              # oversize object: not kept
                        try:
                            blob_storage.delete(it.file_key)
                        except Exception:
                            logger.warning("could not delete oversize upload %s", it.file_key, exc_info=True)
                    items.filter(pk=it.pk, status="uploading").update(
                        status="failed", reason=problem[:160], file_key="", processed_at=timezone.now())
                else:
                    items.filter(pk=it.pk, status="uploading").update(status="queued", file_size=size)
        except Exception:
            logger.exception("could not verify uploads for batch %s", batch.id)
            return back_to_pending()

        if not batch.items.filter(status="queued").exists():
            abort_batch(batch, "None of the files finished uploading. Please upload again.")
            return error("None of your files finished uploading. Please try again.", status=400)
        _finalise_if_done(batch.pk)        # counters now reflect files that never arrived

        # The batch is now "queued" in the database. With Celery running, the scheduled job picks it
        # up; without it, read it here (web-server fallback) so it never waits with nobody to read it.
        bulk_fallback(batch.id)
        return current()


class PortalExtractConfigView(APIView):
    """
    GET .../extract/config/ — the limits the app needs BEFORE it chooses instant or bulk. One source of
    truth with the My Reports pipeline: instant_max_files is the "Sort instantly up to" setting on
    platform admin -> Background Jobs.
    """
    permission_classes = [IsPatient]

    def get(self, request):
        return success(data={
            "instant_max_files": _instant_max(),
            "bulk_max_files": _BULK_MAX_FILES,
            "batch_max_bytes": getattr(settings, "EXTRACTION_BATCH_MAX_BYTES", 175 * 1024 * 1024),
        })


class PortalExtractBulkStatusView(APIView):
    """GET .../bulk/<batch_id>/status/ — polled by the mobile app while a batch is queued/processing."""
    permission_classes = [IsPatient]

    def get(self, request, batch_id):
        from apps.registry.models import ExtractionBatch
        from apps.registry.tasks import reconcile_stale_batches

        target_awpid, _name, err = _target_identity(request)
        if err:
            return err

        batch = ExtractionBatch.objects.using("default").filter(pk=batch_id, awpid=target_awpid).first()
        if not batch:
            return error("Batch not found.", status=404)
        if batch.status in ExtractionBatch.ACTIVE_STATUSES:
            # Polling doubles as recovery: a file stuck past the worker's hard limit is failed
            # here, and a batch that genuinely can't progress is closed (healthy ones are not).
            reconcile_stale_batches(target_awpid)
            batch.refresh_from_db()
        items = list(batch.items.values("id", "original_filename", "status", "reason", "started_at", "processed_at"))
        counts = {s: 0 for s in ("uploading", "queued", "processing", "done", "failed")}
        for it in items:
            counts[it["status"]] = counts.get(it["status"], 0) + 1
        return success(data={
            "batch": {
                "id": str(batch.id), "status": batch.status,
                "total_files": batch.total_files, "completed": batch.completed, "failed": batch.failed,
                "processed": batch.processed, "progress_percent": batch.progress_percent,
                "counts": counts,
                "created_at": batch.created_at, "queued_at": batch.queued_at,
                "started_at": batch.started_at, "finished_at": batch.finished_at,
            },
            "items": [{**it, "id": str(it["id"])} for it in items],
        })


class PortalPushTokenRegisterView(APIView):
    """
    POST /api/v1/portal/push-token/  body: { token, platform? }
    Registers this device's Expo push token against the LOGGED-IN account
    (not a family-member target — a push token belongs to the device/app
    install, not to whichever patient is currently being viewed). Used so
    far only to notify when a background bulk extraction batch finishes
    (see apps/registry/tasks.py) — no other notification type reads this yet.
    """
    permission_classes = [IsPatient]

    def post(self, request):
        from apps.registry.models import PushDeviceToken

        acct = PatientAccount.objects.using("default").get(pk=request.user.id)
        token = str(request.data.get("token") or "").strip()
        platform = str(request.data.get("platform") or "").strip()[:10]
        if not token:
            return error("token is required.")

        PushDeviceToken.objects.using("default").update_or_create(
            token=token, defaults={"awpid": acct.awpid, "platform": platform},
        )
        return success(data={"registered": True})


# ── Extracted reports list (finished items the patient hasn't dismissed) ───────

_LIST_CAP = 300
_INSTANT_GROUP_GAP = timedelta(seconds=90)   # sync uploads have no batch: uploads this close together count as one group


def _snippet(text, n=90):
    flat = " ".join((text or "").split())
    return flat[:n] + ("…" if len(flat) > n else "")


class PortalExtractedItemsView(APIView):
    """
    GET .../extract/items/[?patient_awpid=] — finished (done/failed), undismissed
    extractions, newest upload first, grouped per upload. Each item carries `ai`, the AI-check
    status (see the module docstring); counts.ai_pending is how many are still queued/running. Items of a batch that
    was cancelled outright (nothing arrived) are left out: the progress card
    already told the patient, and there is nothing to open.
    """
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.registry.models import ExtractionItem

        target_awpid, _name, err = _target_identity(request)
        if err:
            return err

        rows = list(
            ExtractionItem.objects.using("default")
            .filter(awpid=target_awpid, status__in=("done", "failed"), dismissed_at__isnull=True)
            .exclude(batch__status="cancelled")
            .order_by("-created_at")[:_LIST_CAP]
            .values("id", "batch_id", "original_filename", "mime_type", "file_key", "status", "reason",
                    "extracted_text", "created_at", "document_id")
        )
        ai = ai_map(r["document_id"] for r in rows)        # the AI-check status of each file, one query

        groups, by_batch, oldest = [], {}, {}
        for r in rows:
            item = {
                "id": str(r["id"]), "name": r["original_filename"] or "Upload", "status": r["status"],
                "mime_type": r["mime_type"],
                "has_file": bool(r["file_key"]),
                "reason": r["reason"] if r["status"] == "failed" else "",
                "snippet": _snippet(r["extracted_text"]) if r["status"] == "done" else "",
                "created_at": r["created_at"],
                "ai": ai.get(r["document_id"], AI_NONE) if r["status"] == "done" else AI_NONE,
            }
            if r["batch_id"]:
                key = f"batch-{r['batch_id']}"
                g = by_batch.get(key)
                if not g:
                    g = by_batch[key] = {"id": key, "kind": "batch", "created_at": r["created_at"], "items": []}
                    groups.append(g)
            else:
                # newest-first: a sync item joins the previous sync group when it is close enough in time
                g = groups[-1] if groups and groups[-1]["kind"] == "instant" else None
                if not g or oldest[g["id"]] - r["created_at"] > _INSTANT_GROUP_GAP:
                    g = {"id": f"instant-{r['id']}", "kind": "instant", "created_at": r["created_at"], "items": []}
                    groups.append(g)
                oldest[g["id"]] = r["created_at"]
            g["items"].append(item)

        # A stable file total per upload for the group title. Without it the title would count only the
        # files finished so far ("5 files", "9 files", ...) and grow while a batch is still being read.
        from apps.registry.models import ExtractionBatch
        totals = {
            str(pk): n for pk, n in
            ExtractionBatch.objects.using("default")
            .filter(pk__in=[g["id"][len("batch-"):] for g in groups if g["kind"] == "batch"])
            .values_list("id", "total_files")
        }
        for g in groups:
            g["total"] = totals.get(g["id"][len("batch-"):], len(g["items"])) if g["kind"] == "batch" else len(g["items"])

        ready = sum(1 for r in rows if r["status"] == "done")
        ai_pending = sum(1 for g in groups for i in g["items"] if i["ai"]["status"] in ("queued", "running"))
        return success(data={"counts": {"ready": ready, "failed": len(rows) - ready, "ai_pending": ai_pending}, "groups": groups})


class PortalExtractedItemDetailView(APIView):
    """GET .../extract/items/<item_id>/ — a short-lived link to the kept original file (opened like any other report), plus the text."""
    permission_classes = [IsPatient]

    def get(self, request, item_id):
        from apps.registry.models import ExtractionItem

        target_awpid, _name, err = _target_identity(request)
        if err:
            return err
        it = ExtractionItem.objects.using("default").filter(pk=item_id, awpid=target_awpid).first()
        if not it or it.status not in ("done", "failed"):
            return error("Not found.", status=404)

        file_url = blob_storage.signed_url(it.file_key) if it.file_key else ""   # "" if storage is unset/unavailable
        ai = ai_map([it.document_id]).get(it.document_id, AI_NONE) if it.status == "done" else AI_NONE
        return success(data={
            "id": str(it.id), "name": it.original_filename or "Upload", "status": it.status,
            "reason": it.reason if it.status == "failed" else "",
            "text": it.extracted_text if it.status == "done" else "",
            "page_count": it.page_count, "mime_type": it.mime_type,
            "file_url": file_url, "created_at": it.created_at, "ai": ai,
        })


class PortalExtractedItemsDismissView(APIView):
    """
    POST .../extract/items/dismiss/  body: { item_ids: [...] } or { all: true }, plus optional patient_awpid.
    Hides finished items from the list. Nothing is deleted: the file, text and row stay for the later
    classification stage. Only the target patient's own finished items can be touched.
    """
    permission_classes = [IsPatient]

    def post(self, request):
        import uuid
        from django.utils import timezone
        from apps.registry.models import ExtractionItem

        target_awpid, _name, err = _target_identity(request)
        if err:
            return err

        qs = ExtractionItem.objects.using("default").filter(
            awpid=target_awpid, status__in=("done", "failed"), dismissed_at__isnull=True,
        ).exclude(batch__status="cancelled")      # same set the list shows
        if request.data.get("all") is not True:
            ids = request.data.get("item_ids")
            if not isinstance(ids, list) or not ids:
                return error("item_ids (or all: true) is required.")
            if len(ids) > 500:
                return error("Too many items at once.")
            clean = []
            for i in ids:
                try:
                    clean.append(uuid.UUID(str(i)))
                except ValueError:
                    return error("Invalid item id.")
            qs = qs.filter(pk__in=clean)
        return success(data={"dismissed": qs.update(dismissed_at=timezone.now())})
