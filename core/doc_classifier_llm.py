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
    DOC_CLASSIFIER_LLM_KEY    api key; falls back to GROQ_API_KEY. Not needed
                              for a local server (Ollama: BASE=http://localhost:11434/v1).
    DOC_CLASSIFIER_LLM_TIMEOUT seconds per call (a local 7B model is slower)
    LLM_MODE                  local (the settings above) | production (the GPU
                              server's gateway, LLM_GATEWAY_URL) — see core.llm_client

In the background pipeline this runs as its own task on the "llm" Celery
queue (core/pipeline/llm_queue.py, task core.llm_drain): one document at a time, and while
the server is unreachable the task waits and retries instead of failing.
"""

from __future__ import annotations

import hashlib
import json
import logging

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
    "- The text comes from OCR and WILL contain scanning errors: garbled "
    "characters, merged/split words, misread digits, a misread 'Date' as "
    "'Dale', and similar noise. Read past it — do not lower your confidence "
    "just because the text looks imperfect; only lower it if the meaning "
    "itself is genuinely unclear.\n"
    "- kind is one of: prescription, lab_report, scan, discharge_summary, "
    "other, not_medical.\n"
    "  * prescription = a DOCTOR instructing a PATIENT what to take: dosing "
    "lines (e.g. '1-0-1', 'Tab.', 'Sig:'), a diagnosis, advice. This is an "
    "ORDER, not a charge.\n"
    "  * lab_report = a diagnostic/pathology report with a results table.\n"
    "  * scan = radiology/imaging report (x-ray, USG, CT, MRI, ECG, echo).\n"
    "  * discharge_summary = hospital discharge / admission summary.\n"
    "  * not_medical = invoice, receipt, ID card, boarding pass, bank "
    "statement, payslip, or anything not a health record.\n"
    "    IMPORTANT: a PHARMACY OR HOSPITAL BILL/RECEIPT is not_medical even "
    "when it lists medicine names, a doctor's name, or a hospital letterhead "
    "— a bill is a SHOP charging money for items already sold, not a doctor's "
    "order. Look for the commerce signal: GST/CGST/SGST, a unit price or MRP "
    "column, a bill/receipt/DL number, 'Net Payable', 'Amount Paid', a "
    "payment mode (UPI/cash/card). Two or more of these on a page that lists "
    "drug names means it is the pharmacy's bill for those drugs, not the "
    "prescription that ordered them — classify it not_medical, not "
    "prescription, however many medicine names appear.\n"
    "  * other = medical-adjacent but none of the above.\n"
    "- categories: ONLY for kind=lab_report. Use slugs from this fixed list, "
    "primary panel first; [] if unsure. Allowed slugs: {slugs}.\n"
    "- report_date: the clinically meaningful date (prefer sample-collection, "
    "then report/result date; ignore print/next-visit dates). ISO YYYY-MM-DD "
    "or null. date_source: collection|report|received|issue|consult|bare.\n"
    "- confidence: your genuine certainty 0..1 for kind + categories — do not "
    "default to a round number like 0.95 out of habit; a truly clear-cut "
    "document (e.g. an OP bill with three billing markers, or a textbook lab "
    "report) can be 0.95-1.0, but a page you are inferring from thin or "
    "conflicting evidence should score well below that.\n"
    "- scores: your probability 0..1 for EVERY kind (prescription, lab_report, "
    "scan, discharge_summary, other, not_medical); they should sum to about 1.\n"
    'Respond exactly: {{"kind": "...", "categories": [...], "report_date": '
    '"YYYY-MM-DD" or null, "date_source": "...", "confidence": 0.0, '
    '"scores": {{"prescription": 0.0, "lab_report": 0.0, "scan": 0.0, '
    '"discharge_summary": 0.0, "other": 0.0, "not_medical": 0.0}}}}'
)


def _is_local(base: str) -> bool:
    return any(h in (base or "") for h in ("://localhost", "://127.0.0.1", "://host.docker.internal"))


def _enabled() -> bool:
    from core import llm_client
    if llm_client.mode() == "production":
        return bool(getattr(settings, "LLM_GATEWAY_URL", ""))
    base = getattr(settings, "DOC_CLASSIFIER_LLM_BASE", "")
    return bool((getattr(settings, "DOC_CLASSIFIER_LLM_KEY", "") or _is_local(base))
               and base
               and getattr(settings, "DOC_CLASSIFIER_LLM_MODEL", ""))


def model_name() -> str:
    from core import llm_client
    if not _enabled():
        return ""
    if llm_client.mode() == "production":
        return (getattr(settings, "LLM_GATEWAY_MODEL", "") or "gpu-server")[:80]
    return getattr(settings, "DOC_CLASSIFIER_LLM_MODEL", "")


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
    sc = raw.get("scores")
    if isinstance(sc, dict):
        scores = {}
        for k, v in sc.items():
            k = str(k).strip().lower()
            try:
                if k in _KINDS:
                    scores[k] = round(max(0.0, min(1.0, float(v))), 3)
            except (TypeError, ValueError):
                continue
        if scores:
            out["scores"] = scores
            if "kind" not in out:
                out["kind"] = max(scores, key=scores.get)
    return out


def _parse_json(content: str) -> dict:
    """The GPU gateway has no JSON mode — take the first {...} object in the reply."""
    content = (content or "").strip()
    try:
        return json.loads(content)
    except ValueError:
        start, end = content.find("{"), content.rfind("}")
        if start != -1 and end > start:
            return json.loads(content[start:end + 1])
        raise


def classify(text: str, *, raise_unavailable: bool = False) -> dict:
    """
    Text (OCR / PDF layer) -> label dict, via core.llm_client (local Ollama or
    the production GPU server — LLM_MODE). Best-effort: returns {} on any
    problem, except that with raise_unavailable=True an unreachable/busy
    server raises llm_client.LLMUnavailable so a queued task can retry later.
    """
    from core import llm_client
    text = (text or "").strip()
    if not text or not _enabled():
        return {}
    # What identifies a document is near the top; the budget depends on the
    # server (a local 7B on CPU slows steeply with length — 4.3k chars 77 s vs
    # 2.5k 16 s, same verdict; the GPU server has a 32k context).
    text = text[:llm_client.max_chars()]

    ck = f"docllm3:{llm_client.mode()}:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:40]
    _c = _cache()
    hit = _c.get(ck)
    if hit is not None:
        return hit

    sys_prompt = _SYSTEM.format(slugs=", ".join(report_types.SLUGS))
    try:
        out = llm_client.complete(sys_prompt, "OCR TEXT:\n" + text, temperature=0,
                                  max_tokens=_MAX_TOKENS, json_mode=True)
        data = _parse_json(out["content"])
    except llm_client.LLMUnavailable:
        if raise_unavailable:
            raise
        logger.warning("doc_classifier_llm: LLM unavailable; keeping deterministic result")
        return {}
    except Exception:
        logger.warning("doc_classifier_llm: call failed; keeping deterministic result", exc_info=True)
        return {}

    result = _sanitise(data)
    _c.set(ck, result, _CACHE_TTL)
    logger.info("doc_classifier_llm: kind=%s cats=%s date=%s conf=%s (%s, %ss)",
                result.get("kind"), result.get("categories"), result.get("report_date"),
                result.get("confidence"), llm_client.mode(), out.get("generation_time"))
    return result
