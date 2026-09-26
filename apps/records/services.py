"""
The records pipeline, two independently-queued Celery stages so a slow classification/LLM call for
one document never blocks extraction starting on the next:

    save_upload()          one UploadBatch + one SharedDocument per file, files to S3
    extract_document()     S3 → RapidOCR → save text, hand off to classify_document_task
    classify_document()    rule classification → Ollama if score < 75 → save

The keyword rules come from the ClassificationRule table on every call, so a
change in Platform Admin applies to the next document with no restart. The
same rules drive both the rule score and the Ollama prompt.
"""
import io
import logging
import time
import uuid
from contextlib import contextmanager
from datetime import timedelta

import requests
from django.conf import settings
from django.db import connections, transaction
from django.db.models import Q
from django.utils import timezone

from core import ocr, storage
from .models import ClassificationRule, SharedDocument, UploadBatch

logger = logging.getLogger(__name__)

THRESHOLD = 75
STUCK_MINUTES = 5     # shared with stuck_document_ids() — how long "in progress" means "worker died"
OBJECT_PREFIX = "patient-documents/"
_EXT = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png"}


# ── upload ───────────────────────────────────────────────────────────────
def _is_ours(key: str) -> bool:
    return bool(key) and key.startswith(OBJECT_PREFIX)


def _safe_delete(key: str) -> None:
    """Never deletes an S3 object outside this app's own prefix — a bug or a wrong key passed in
    later can't cost a document (or anything else in the bucket) that isn't this app's to delete."""
    if not _is_ours(key):
        if key:
            logger.warning("records: refusing to delete %r — not a records/ object", key)
        return
    storage.delete(key)


def save_upload(awpid, files):
    """`files` = [(uploaded_file, raw_bytes, verified_mime)], already validated.
    If S3 fails part-way, the files already sent are deleted and nothing is saved."""
    keys = []
    try:
        for f, raw, mime in files:
            keys.append(storage.put_bytes(f"{OBJECT_PREFIX}{awpid}/{uuid.uuid4().hex}.{_EXT[mime]}", raw, mime_type=mime))
        with transaction.atomic(using="default"):
            batch = UploadBatch.objects.create(awpid=awpid, total_files=len(files))
            docs = [SharedDocument.objects.create(
                awpid=awpid, batch=batch, title=f.name.rsplit(".", 1)[0][:200], file_name=f.name[:255],
                mime_type=mime, s3_key=key, uploaded_by="patient", processing_status="queued",
            ) for (f, _, mime), key in zip(files, keys)]
    except Exception:
        for key in keys:
            _safe_delete(key)
        raise
    return batch, docs


# ── processing ───────────────────────────────────────────────────────────
@contextmanager
def _locked(document_id):
    """True if this call got document_id's lock; released on exit. A Postgres advisory lock, not a
    status check, so a live worker and a stale-recovery redispatch can never both act on the same
    document at once — the second caller just sees `got=False` and returns immediately."""
    conn = connections["default"]
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", [document_id])
        got = cur.fetchone()[0]
    try:
        yield got
    finally:
        if got:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", [document_id])


def extract_document(document_id):
    """Stage 1: S3 → text. On success, dispatches classify_document_task and returns immediately —
    this worker is free for the next document without waiting on classification or the LLM."""
    with _locked(document_id) as got:
        if not got:
            return
        doc = SharedDocument.objects.filter(pk=document_id, processing_status__in=("queued", "ocr")).first()
        if not doc:
            return
        _set(doc, processing_status="ocr", error="")
        try:
            text = extract_text(storage.get_bytes(doc.s3_key), doc.mime_type)
        except Exception as exc:
            logger.exception("records: extraction failed for %s", document_id)
            _set(doc, processing_status="failed", error=str(exc)[:2000])
            return
        _set(doc, processing_status="classifying", extracted_text=text)
    from .tasks import classify_document_task
    classify_document_task.delay(document_id)


def classify_document(document_id):
    """Stage 2: rules, then the LLM if needed — its own task so a slow LLM call never occupies a
    worker slot that could otherwise be extracting the next document."""
    with _locked(document_id) as got:
        if not got:
            return
        doc = SharedDocument.objects.filter(pk=document_id, processing_status="classifying").first()
        if not doc:
            return
        try:
            doc_type, score, method = classify(doc.extracted_text)
            _set(doc, doc_type=doc_type, score=score, method=method, processing_status="completed")
        except Exception as exc:
            logger.exception("records: classification failed for %s", document_id)
            _set(doc, processing_status="failed", error=str(exc)[:2000])


def _set(doc, **fields):
    for k, v in fields.items():
        setattr(doc, k, v)
    doc.save(update_fields=[*fields, "updated_at"])


def extract_text(raw, mime):
    """PDF text layer if it has one, otherwise RapidOCR on the image / first PDF pages."""
    if mime == "application/pdf":
        from pypdf import PdfReader
        text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(raw)).pages[:5]).strip()
        if len(text) >= 40:
            return text
        return "\n".join(ocr.run(png).text for png in ocr.pdf_page_images(raw)).strip()
    return ocr.run(raw).text.strip()


# ── classification ───────────────────────────────────────────────────────
def load_rules():
    """{doc_type: [keyword, ...]} from the active rules — read fresh every time."""
    return {r.doc_type: r.keyword_list for r in ClassificationRule.objects.filter(is_active=True) if r.keyword_list}


def classify(text):
    """Returns (doc_type, score 0–100, "rule" | "llm")."""
    rules = load_rules()
    if not text.strip() or not rules:
        return "other", 0.0, "rule"
    doc_type, score = rule_classify(text, rules)
    if score >= THRESHOLD:
        return doc_type, score, "rule"
    doc_type, score = llm_classify(text, rules)
    return doc_type, score, "llm"


def rule_classify(text, rules):
    """Score = share of a type's keywords found in the text; the best type wins."""
    text = text.lower()
    best = ("other", 0.0)
    for doc_type, keywords in rules.items():
        score = round(100 * sum(k in text for k in keywords) / len(keywords), 2)
        if score > best[1]:
            best = (doc_type, score)
    return best


def llm_classify(text, rules):
    """Ask the configured LLM (LLM_MODE — local Ollama or the production GPU server) the same rules
    the rule-based pass used."""
    catalogue = "\n".join(f"- {t}: {'|'.join(k)}" for t, k in rules.items())
    prompt = (f"Classify this medical document. Types and their keywords:\n{catalogue}\n- other: none of these\n\n"
              f"Reply with ONLY one line: <type>|<score 0-100>\n\nDocument text:\n{text[:4000]}")
    answer = llm_complete("", prompt, temperature=0)["content"].strip().splitlines()[0]
    doc_type, _, score = answer.partition("|")
    doc_type = doc_type.strip().lower()
    score = float(score.strip().rstrip("%") or 0)
    return (doc_type if doc_type in rules else "other"), max(0.0, min(100.0, score))


# ── LLM (local Ollama or the production GPU server — same Ollama contract for both, only the
#    base URL/key/model/timeout differ by LLM_MODE. No fallback between them, ever.) ────────
class LLMUnavailable(Exception):
    """The LLM_MODE-selected server is unreachable, unset, or returned something unusable."""


def llm_mode() -> str:
    """"local" or "production" — raises if LLM_MODE is anything else, rather than silently
    defaulting to local (a typo here must never mean "quietly use the wrong server")."""
    mode = (settings.LLM_MODE or "").strip().lower()
    if mode not in ("local", "production"):
        raise ValueError(f"LLM_MODE must be 'local' or 'production', got {settings.LLM_MODE!r}")
    return mode


def _server_config():
    """(base_url, key, model, timeout) for whichever server LLM_MODE selects."""
    if llm_mode() == "production":
        return (settings.LLM_PRODUCTION_URL, settings.LLM_PRODUCTION_TOKEN,
                settings.LLM_PRODUCTION_MODEL, settings.LLM_PRODUCTION_TIMEOUT)
    return (settings.DOC_CLASSIFIER_LLM_BASE, settings.DOC_CLASSIFIER_LLM_KEY,
            settings.DOC_CLASSIFIER_LLM_MODEL, settings.DOC_CLASSIFIER_LLM_TIMEOUT)


def llm_complete(system_prompt, user_prompt, *, temperature=0.0, max_tokens=None) -> dict:
    """Ask whichever server LLM_MODE selects — the one HTTP implementation both modes share, since
    both are Ollama (OpenAI-compatible /chat/completions); only _server_config() differs by mode.
    Returns {"content", "prompt_tokens", "completion_tokens", "generation_time"}."""
    base_url, key, model, timeout = _server_config()
    if not base_url:
        raise LLMUnavailable(f"no URL configured for LLM_MODE={llm_mode()}")
    messages = ([{"role": "system", "content": system_prompt}] if system_prompt else []) \
        + [{"role": "user", "content": user_prompt}]
    payload = {"model": model, "temperature": temperature, "messages": messages,
               "options": {"num_ctx": settings.LLM_NUM_CTX}}
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    t0 = time.monotonic()
    try:
        resp = requests.post(f"{base_url.rstrip('/')}/chat/completions",
                              headers={"Authorization": f"Bearer {key or 'ollama'}"},
                              json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise LLMUnavailable(f"{llm_mode()} LLM unreachable: {exc}") from exc
    if not resp.ok:
        raise LLMUnavailable(f"{llm_mode()} LLM returned HTTP {resp.status_code}")
    try:
        d = resp.json()
        usage = d.get("usage") or {}
        return {"content": d["choices"][0]["message"]["content"], "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"), "generation_time": round(time.monotonic() - t0, 2)}
    except (ValueError, KeyError, IndexError) as exc:
        raise LLMUnavailable(f"{llm_mode()} LLM returned an unexpected response: {exc}") from exc


def llm_status() -> dict:
    """Never raises for network reasons. {"mode", "reachable"} — or {"mode": "invalid", "reachable":
    False, "error"} if LLM_MODE itself is misconfigured (surfaced, not swallowed)."""
    try:
        mode = llm_mode()
    except ValueError as exc:
        return {"mode": "invalid", "reachable": False, "error": str(exc)}
    base_url, key, _model, _timeout = _server_config()
    if not base_url:
        return {"mode": mode, "reachable": False}
    try:
        resp = requests.get(f"{base_url.rstrip('/')}/models",
                             headers={"Authorization": f"Bearer {key or 'ollama'}"}, timeout=5)
        return {"mode": mode, "reachable": resp.ok}
    except requests.RequestException:
        return {"mode": mode, "reachable": False}


# ── periodic sweep ───────────────────────────────────────────────────────
def documents_ready_for_pickup(limit):
    """
    (id, processing_status) pairs the periodic sweep may (re)send now, oldest first, up to `limit` —
    status tells the caller which stage's task to dispatch:
      - "queued": always eligible — either a bulk batch deliberately left undispatched at intake
        (see SweepConfig.instant_max_files), or one whose initial dispatch failed (broker was down).
        Nothing can be actively working on a "queued" document, so there's no staleness wait.
      - "ocr" / "classifying": only once stale (STUCK_MINUTES) — something claimed the document and
        never finished, so the worker most likely died.
    Their updated_at is bumped so the same run isn't sent again next cycle.
    """
    cutoff = timezone.now() - timedelta(minutes=STUCK_MINUTES)
    qs = (SharedDocument.objects
          .filter(Q(processing_status="queued")
                  | Q(processing_status__in=("ocr", "classifying"), updated_at__lt=cutoff))
          .order_by("created_at"))
    rows = list(qs.values_list("id", "processing_status")[:limit])
    SharedDocument.objects.filter(id__in=[r[0] for r in rows]).update(updated_at=timezone.now())
    return rows
