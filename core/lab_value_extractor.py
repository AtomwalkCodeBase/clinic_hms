"""
core/lab_value_extractor.py
----------------------------
Reads the actual test VALUES out of an already-classified lab_report — a
second, separate pipeline stage from core.doc_classifier, which deliberately
never does this (its own docstring forbids test values; it only decides
kind/panel/date). This module is the "read the number" step, run later and
asynchronously via `manage.py extract_lab_values`, never inline with a
document upload.

Same conventions as core/doc_classifier_llm.py and core/doc_classifier_vision.py
on purpose — this is the same kind of call, just a different question:
  - No SDK: a raw OpenAI-compatible /chat/completions POST.
  - A labeller, never a calculator: the prompt forbids inferring, rounding,
    converting, or computing anything not printed. Copy, don't interpret.
  - Never raises. Any failure/disabled-layer -> {}, and the caller (the
    extract_lab_values command) marks the document accordingly — this module
    never decides what "failed" means for a SharedDocument row.
  - response_format json_object, temperature 0, the same 429/413/5xx retry
    with Retry-After honored, the same "drop response_format and retry once
    on a 400 that mentions it" tolerance.
  - A persistent, worker-shared cache (caches["lab_extract"], migration 0038)
    keyed by a hash of the input — a document's printed values never change.

Contract: {"values": [{"parameter": str, "value": <number>, "unit": str,
"reference_range_text": str, "confidence": 0..1}, ...]}. Every entry is
sanitised before being trusted (`_sanitise_values`) — non-numeric `value`
silently drops that entry (qualitative results like "Negative" or "1+" are
out of v1's scope, never coerced into a number). Confidence is per VALUE,
not per document — the caller stores every sanitised entry (even low-
confidence ones) so extract_lab_values.py / a review UI can see exactly which
result, not just which document, needs a human's eyes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time

import requests
from django.conf import settings
from django.core.cache import caches

from core import report_types
from core.doc_classifier_vision import _loads, _prep  # reuse the same tolerant-JSON parse + image downscale/encode

logger = logging.getLogger(__name__)

_MAX_CHARS = 8000          # a results table can run longer than the header text doc_classifier_llm needs
_MAX_VALUES = 40           # bounds payload size and guards against a hallucinated runaway list
_CACHE_TTL_TEXT = 60 * 60 * 24 * 30    # 30 days — matches doc_classifier_llm's text TTL
_CACHE_TTL_VISION = 60 * 60 * 24 * 60  # 60 days — matches doc_classifier_vision's TTL
_MAX_TRIES = 4
_MAX_IMAGES = 2
# An array of up to _MAX_VALUES analyte objects needs materially more output
# budget than classification's single flat object (doc_classifier_llm.py's
# _MAX_TOKENS=1024 / doc_classifier_vision.py's =1024) — start higher, tune
# against core/extractor_eval_corpus.py if outputs truncate.
_MAX_TOKENS = 2048

_SYSTEM = (
    "You read the RESULTS TABLE of a medical lab report and extract every "
    "numeric test result exactly as printed. You are given the raw OCR/page "
    "text of ONE document already known to contain these panels: {labels}. "
    "Analytes commonly found in those panels include: {hints} — this list is "
    "GUIDANCE, not a whitelist; extract every row with a plain numeric "
    "result, not only these names.\n"
    "STRICT RULES:\n"
    "- Output ONLY a JSON object: {{\"values\": [...]}}. No prose.\n"
    "- NEVER infer, calculate, round, estimate, or convert a value, unit, or "
    "reference range that isn't printed. If you can't read a value "
    "confidently, omit it rather than guess.\n"
    "- Copy reference_range_text EXACTLY as printed for that row (e.g. "
    "\"13.0 - 17.0\", \"<5\", \"Male: 13-17, Female: 12-15\") — do not "
    "compute, normalize, split, or convert it. Empty string if none printed.\n"
    "- Skip qualitative / descriptive results (colour, appearance, "
    "Negative/Positive/Trace, 1+/2+, organism names, \"Nil seen\") — only "
    "extract results that are a plain number.\n"
    "- Skip anything that is not a clinical test result, even if it has a "
    "number next to a label-like word: lab technician / pathologist / "
    "doctor names and signature blocks, accreditation or registration "
    "numbers, sample IDs, barcodes, report/page numbers, dates, phone "
    "numbers, and other administrative header/footer fields. Only extract "
    "a row if it is genuinely a measured analyte inside the results table.\n"
    "- confidence (0..1): your certainty that THIS parameter+value+unit trio, "
    "specifically, was read correctly — not your certainty about the "
    "document as a whole. A smudged or ambiguous digit should score low, not "
    "be silently rounded to something confident-looking.\n"
    "- unit: exactly as printed (e.g. \"g/dL\", \"10^3/uL\", \"mg/dL\"); "
    "empty string if none printed.\n"
    'Respond exactly: {{"values": [{{"parameter": "...", "value": 0.0, '
    '"unit": "...", "reference_range_text": "...", "confidence": 0.0}}, ...]}}'
)


def _cache():
    try:
        return caches["lab_extract"]
    except Exception:
        return caches["default"]


def _enabled_text() -> bool:
    return bool(getattr(settings, "LAB_EXTRACTOR_LLM_KEY", "")
               and getattr(settings, "LAB_EXTRACTOR_LLM_BASE", "")
               and getattr(settings, "LAB_EXTRACTOR_LLM_MODEL", ""))


def _enabled_vision() -> bool:
    return bool(getattr(settings, "LAB_EXTRACTOR_VISION_KEY", "")
               and getattr(settings, "LAB_EXTRACTOR_VISION_BASE", "")
               and getattr(settings, "LAB_EXTRACTOR_VISION_MODEL", ""))


def _hints_for(panel_slugs: list) -> tuple:
    """(labels_str, hints_str) for the prompt — panel labels + a deduped
    sample of their marker vocabulary. Guidance only, see module docstring."""
    slugs = [s for s in (panel_slugs or []) if s in report_types.PANELS_BY_SLUG]
    if not slugs:
        slugs = list(report_types.SLUGS)  # unknown panel — no vocabulary to scope to, extract anything numeric
    labels, hints = [], []
    seen = set()
    for slug in slugs:
        panel = report_types.PANELS_BY_SLUG[slug]
        labels.append(panel.label)
        for h in (*panel.strong, *panel.markers):
            if h not in seen:
                seen.add(h)
                hints.append(h)
    return ", ".join(labels), ", ".join(hints[:60])


def _parse_number(raw) -> float | None:
    """Lenient numeric coercion — a printed "10,500" or " 13.9 " should still
    parse; anything that isn't recognisably a plain number returns None so
    the caller drops that entry rather than guessing."""
    if isinstance(raw, (int, float)):
        return float(raw)
    if not isinstance(raw, str):
        return None
    s = raw.strip().replace(",", "")
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _sanitise_values(raw) -> list:
    """Keep only well-formed entries; cap the list. Never raises."""
    if not isinstance(raw, dict):
        return []
    values = raw.get("values")
    if not isinstance(values, list):
        return []
    out = []
    for entry in values[: _MAX_VALUES * 2]:   # look at a bit more than the cap in case some entries get dropped
        if not isinstance(entry, dict):
            continue
        parameter = str(entry.get("parameter") or "").strip()[:120]
        if not parameter:
            continue
        value = _parse_number(entry.get("value"))
        if value is None:
            continue
        try:
            confidence = max(0.0, min(1.0, float(entry.get("confidence"))))
        except (TypeError, ValueError):
            continue  # no usable confidence — never trust a value with an unknown confidence
        out.append({
            "parameter": parameter,
            "value": value,
            "unit": str(entry.get("unit") or "").strip()[:30],
            "reference_range_text": str(entry.get("reference_range_text") or "").strip()[:80],
            "confidence": confidence,
        })
        if len(out) >= _MAX_VALUES:
            break
    return out


def _post_text(payload: dict) -> str:
    key = settings.LAB_EXTRACTOR_LLM_KEY
    url = settings.LAB_EXTRACTOR_LLM_BASE.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    resp = None
    for attempt in range(_MAX_TRIES):
        resp = requests.post(url, json=payload, headers=headers, timeout=45)
        if resp.status_code == 400 and "response_format" in resp.text:
            payload.pop("response_format", None)
            continue
        if resp.status_code in (429, 413, 500, 502, 503) and attempt < _MAX_TRIES - 1:
            wait = min(20, int(resp.headers.get("retry-after") or 0) or 4 * (attempt + 1))
            logger.warning("lab_value_extractor: %s from provider — retry %d in %ss",
                           resp.status_code, attempt + 1, wait)
            time.sleep(wait)
            continue
        break
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _post_vision(payload: dict) -> str:
    key = settings.LAB_EXTRACTOR_VISION_KEY
    url = settings.LAB_EXTRACTOR_VISION_BASE.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    resp = None
    for attempt in range(_MAX_TRIES):
        resp = requests.post(url, json=payload, headers=headers, timeout=90)
        if resp.status_code == 400 and "response_format" in resp.text:
            payload.pop("response_format", None)
            continue
        if resp.status_code in (429, 413, 500, 502, 503) and attempt < _MAX_TRIES - 1:
            wait = min(30, int(resp.headers.get("retry-after") or 0) or 5 * (attempt + 1))
            logger.warning("lab_value_extractor: %s from provider (vision) — retry %d in %ss",
                           resp.status_code, attempt + 1, wait)
            time.sleep(wait)
            continue
        break
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def extract_text(text: str, panel_slugs: list) -> dict:
    """OCR/PDF text -> {"values": [...]}. Best-effort; never raises."""
    text = (text or "").strip()
    if not text or not _enabled_text():
        return {}
    text = text[:_MAX_CHARS]
    labels, hints = _hints_for(panel_slugs)

    ck = "labtxt:" + hashlib.sha256((text + "|" + labels).encode("utf-8")).hexdigest()[:40]
    _c = _cache()
    hit = _c.get(ck)
    if hit is not None:
        return hit

    payload = {
        "model": settings.LAB_EXTRACTOR_LLM_MODEL,
        "temperature": 0,
        "max_tokens": _MAX_TOKENS,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _SYSTEM.format(labels=labels, hints=hints)},
            {"role": "user", "content": "REPORT TEXT:\n" + text},
        ],
    }
    try:
        content = _post_text(payload)
        data = json.loads(content)
    except Exception:
        logger.warning("lab_value_extractor: text call failed", exc_info=True)
        return {}

    result = {"values": _sanitise_values(data)}
    _c.set(ck, result, _CACHE_TTL_TEXT)
    logger.info("lab_value_extractor: text layer found %d value(s)", len(result["values"]))
    return result


def extract_images(images: list, panel_slugs: list) -> dict:
    """List of page-image bytes -> {"values": [...]}. Best-effort; never raises."""
    images = [b for b in (images or []) if b][:_MAX_IMAGES]
    if not images or not _enabled_vision():
        return {}
    labels, hints = _hints_for(panel_slugs)

    digest = hashlib.sha256(b"".join(images) + labels.encode("utf-8")).hexdigest()[:40]
    ck = "labvis:" + digest
    _c = _cache()
    hit = _c.get(ck)
    if hit is not None:
        return hit

    urls = [u for u in (_prep(b) for b in images) if u]
    if not urls:
        return {}

    content = [{"type": "text", "text": "Extract every numeric test result from this report."}]
    content += [{"type": "image_url", "image_url": {"url": u}} for u in urls]
    payload = {
        "model": settings.LAB_EXTRACTOR_VISION_MODEL,
        "temperature": 0,
        "max_tokens": _MAX_TOKENS,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _SYSTEM.format(labels=labels, hints=hints)},
            {"role": "user", "content": content},
        ],
    }
    try:
        data = _loads(_post_vision(payload))
    except Exception:
        logger.warning("lab_value_extractor: vision call failed", exc_info=True)
        return {}
    if not data:
        logger.warning("lab_value_extractor: empty/unparseable vision reply")
        return {}

    result = {"values": _sanitise_values(data)}
    _c.set(ck, result, _CACHE_TTL_VISION)
    logger.info("lab_value_extractor: vision layer found %d value(s)", len(result["values"]))
    return result
