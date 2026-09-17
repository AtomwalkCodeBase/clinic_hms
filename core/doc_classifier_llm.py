"""
core/doc_classifier_llm.py
--------------------------
Optional LLM fallback for the *uncertain tail* of document classification.

`core.doc_classifier` runs its deterministic keyword pass first; only when
that isn't confident (`ClassResult.needs` non-empty) and the page is readable
does it call `classify(text)` here. So this never touches the ~85 % of
uploads the keyword pass already nails — it resolves the rest.

Contract (see `_llm_refine` in doc_classifier.py): return a dict with any of

    {
      "kind":        prescription | lab_report | scan | discharge_summary |
                     other | not_medical,
      "categories":  [<panel slug>, ...]   # lab_report only, from report_types.SLUGS
      "report_date": "YYYY-MM-DD" | null,
      "date_source": collection | report | received | issue | consult | bare,
      "confidence":  0..1
    }

It is a *labeller*, never an interpreter: the prompt forbids test values,
findings, diagnoses or any clinical content. Anything malformed, off-schema,
rate-limited past the retry budget, or key-less → returns ``{}`` and the
deterministic result stands.

Config (settings / .env):
    DOC_CLASSIFIER_LLM        dotted path that enables it — default already
                              points here; a blank KEY below disables it.
    DOC_CLASSIFIER_LLM_BASE   OpenAI-compatible base URL (default: Groq)
    DOC_CLASSIFIER_LLM_MODEL  text model id (default: llama-3.3-70b-versatile)
    DOC_CLASSIFIER_LLM_KEY    api key; falls back to GROQ_API_KEY
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


def _cache():
    """The persistent, worker-shared classifier cache; falls back to the
    default (local-memory) cache if 'doc_classify' isn't configured."""
    try:
        return caches["doc_classify"]
    except Exception:
        return caches["default"]

logger = logging.getLogger(__name__)

_KINDS = {"prescription", "lab_report", "scan", "discharge_summary", "other", "not_medical"}
_DATE_SRC = {"collection", "report", "received", "issue", "consult", "bare"}
_MAX_CHARS = 6000        # the identifying part of any report is near the top
_CACHE_TTL = 60 * 60 * 24 * 30   # a given OCR text always classifies the same
_MAX_TRIES = 4
# Reasoning-tier models (openai/gpt-oss-20b included) spend output tokens on
# an internal scratchpad before the answer; 300 was too tight and Groq was
# returning 400 json_validate_failed ("max completion tokens reached before
# generating a valid document") on some inputs — silently caught and treated
# as "LLM unavailable", not surfaced. Matches doc_classifier_vision.py's
# _MAX_TOKENS, which hit the same failure mode for the same reason.
_MAX_TOKENS = 1024

_SYSTEM = (
    "You sort scanned MEDICAL PAPERWORK into filing categories. You are given "
    "the raw OCR text of ONE document. Decide what KIND of document it is and, "
    "if it is a lab report, which standard test PANEL(S) it contains, plus the "
    "report's own date.\n"
    "STRICT RULES:\n"
    "- Output ONLY a JSON object. No prose.\n"
    "- NEVER output test values, results, findings, diagnoses, drug names, or "
    "any clinical content. Categories and a date only.\n"
    "- kind is one of: prescription, lab_report, scan, discharge_summary, "
    "other, not_medical.\n"
    "  * prescription = a doctor's medication order (drug lines, dosing, Rx).\n"
    "  * lab_report = a diagnostic/pathology report with a results table.\n"
    "  * scan = radiology/imaging report (x-ray, USG, CT, MRI, ECG, echo).\n"
    "  * discharge_summary = hospital discharge / admission summary.\n"
    "  * not_medical = invoice, receipt, ID card, boarding pass, bank "
    "statement, payslip, or anything not a health record.\n"
    "  * other = medical-adjacent but none of the above.\n"
    "- categories: ONLY for kind=lab_report. Use slugs from this fixed list, "
    "primary panel first; [] if unsure. Allowed slugs: {slugs}.\n"
    "- report_date: the clinically meaningful date (prefer sample-collection, "
    "then report/result date; ignore print/next-visit dates). ISO YYYY-MM-DD "
    "or null. date_source: collection|report|received|issue|consult|bare.\n"
    "- confidence: your certainty 0..1 for kind + categories.\n"
    'Respond exactly: {{"kind": "...", "categories": [...], "report_date": '
    '"YYYY-MM-DD" or null, "date_source": "...", "confidence": 0.0}}'
)


def _enabled() -> bool:
    return bool(getattr(settings, "DOC_CLASSIFIER_LLM_KEY", "")
               and getattr(settings, "DOC_CLASSIFIER_LLM_BASE", "")
               and getattr(settings, "DOC_CLASSIFIER_LLM_MODEL", ""))


def _post(payload: dict) -> str:
    key = settings.DOC_CLASSIFIER_LLM_KEY
    url = settings.DOC_CLASSIFIER_LLM_BASE.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    resp = None
    for attempt in range(_MAX_TRIES):
        resp = requests.post(url, json=payload, headers=headers, timeout=45)
        if resp.status_code == 400 and "response_format" in resp.text:
            payload.pop("response_format", None)
            continue
        if resp.status_code in (429, 413, 500, 502, 503) and attempt < _MAX_TRIES - 1:
            wait = min(20, int(resp.headers.get("retry-after") or 0) or 4 * (attempt + 1))
            logger.warning("doc_classifier_llm: %s from provider — retry %d in %ss",
                           resp.status_code, attempt + 1, wait)
            time.sleep(wait)
            continue
        break
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _sanitise(raw) -> dict:
    """Keep only well-formed, in-schema fields."""
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    kind = str(raw.get("kind") or "").strip().lower()
    if kind in _KINDS:
        out["kind"] = kind
    cats = raw.get("categories") or []
    if isinstance(cats, list):
        cats = [c for c in (str(x).strip().lower() for x in cats) if c in report_types.PANELS_BY_SLUG]
        if cats:
            out["categories"] = cats[:6]
    rd = raw.get("report_date")
    if isinstance(rd, str) and len(rd) >= 10:
        try:
            y, m, d = (int(x) for x in rd[:10].split("-"))
            from datetime import date
            date(y, m, d)                      # validate
            out["report_date"] = f"{y:04d}-{m:02d}-{d:02d}"
        except Exception:
            pass
    ds = str(raw.get("date_source") or "").strip().lower()
    if ds in _DATE_SRC:
        out["date_source"] = ds
    try:
        c = float(raw.get("confidence"))
        out["confidence"] = max(0.0, min(1.0, c))
    except (TypeError, ValueError):
        pass
    return out


def classify(text: str) -> dict:
    """Text (OCR / PDF layer) -> label dict. Best-effort; never raises."""
    text = (text or "").strip()
    if not text or not _enabled():
        return {}
    text = text[:_MAX_CHARS]

    ck = "docllm:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:40]
    _c = _cache()
    hit = _c.get(ck)
    if hit is not None:
        return hit

    sys_prompt = _SYSTEM.format(slugs=", ".join(report_types.SLUGS))
    payload = {
        "model": settings.DOC_CLASSIFIER_LLM_MODEL,
        "temperature": 0,
        "max_tokens": _MAX_TOKENS,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": "OCR TEXT:\n" + text},
        ],
    }
    try:
        content = _post(payload)
        data = json.loads(content)
    except Exception:
        logger.warning("doc_classifier_llm: call failed; keeping deterministic result",
                       exc_info=True)
        return {}

    result = _sanitise(data)
    _c.set(ck, result, _CACHE_TTL)
    logger.info("doc_classifier_llm: kind=%s cats=%s date=%s conf=%s",
                result.get("kind"), result.get("categories"),
                result.get("report_date"), result.get("confidence"))
    return result
