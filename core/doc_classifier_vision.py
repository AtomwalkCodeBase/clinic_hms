"""
core/doc_classifier_vision.py
-----------------------------
The VISION layer of document classification — the last automated fallback.

`core.doc_classifier` reaches here only when the text layers couldn't settle
the document: OCR produced garbage / too little text, or the deterministic
pass and the text LLM disagree on the kind, or a lab report's panel is still
unknown. It hands the page image(s) straight to a vision-language model and
asks the SAME labelling question — kind / panel / date, never values.

It is OFF unless ``settings.DOC_CLASSIFIER_VISION_MODEL`` is set. Groq now
serves an image-capable model — ``qwen/qwen3.8-27b`` accepts ``image_url``
content and reuses the existing Groq key — or point BASE / MODEL / KEY at a
local vLLM/Ollama VLM (Qwen2.5-VL, Llama-3.2-Vision, MiniCPM-V) or OpenRouter
(google/gemini-2.0-flash-001, openai/gpt-4o-mini). Any OpenAI-compatible
``/chat/completions`` that accepts ``image_url`` content works.

Output contract, cache semantics, retry/backoff and the "never raises,
returns {} on any trouble" guarantee are all identical to
core.doc_classifier_llm — this module reuses its `_sanitise` and constants.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import re
import time

import requests
from django.conf import settings

from core import report_types
from core.doc_classifier_llm import _DATE_SRC, _KINDS, _sanitise, _cache  # noqa: F401  (shared contract)

logger = logging.getLogger(__name__)

_CACHE_TTL = 60 * 60 * 24 * 60
_MAX_TRIES = 4
_MAX_IMAGES = 2
_MAX_EDGE = 1600          # px, long side — plenty for printed text, keeps the payload small
# Reasoning-tier models (Gemini 3.x flash, o-series) spend output tokens on an
# internal scratchpad before the answer — a tight cap truncates the JSON.
_MAX_TOKENS = 1024


def _loads(text: str) -> dict:
    """Parse a model's reply into a dict, tolerating ```json fences and any
    prose the model wrapped around the object."""
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.IGNORECASE).strip()
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        pass
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else {}
        except Exception:
            pass
    return {}

_SYSTEM = (
    "You sort scanned MEDICAL PAPERWORK into filing categories from its "
    "image(s). Decide the KIND of document and, if it is a lab report, which "
    "standard test PANEL(S) it shows, plus the report's own date.\n"
    "STRICT RULES:\n"
    "- Output ONLY a JSON object. No prose.\n"
    "- NEVER output test values, results, findings, diagnoses, drug names or "
    "any clinical content — categories and a date only.\n"
    "- kind is one of: prescription, lab_report, scan, discharge_summary, "
    "other, not_medical.\n"
    "  prescription = a doctor's medication order (drug lines / dosing / Rx). "
    "lab_report = a pathology report with a results table. scan = radiology / "
    "imaging report. discharge_summary = hospital discharge or admission "
    "summary. not_medical = invoice, receipt, ID card, boarding pass, bank "
    "statement, payslip or anything that is not a health record. other = "
    "medical-adjacent but none of the above.\n"
    "- categories: ONLY for kind=lab_report, slugs from this fixed list, "
    "primary panel first, [] if unsure. Allowed slugs: {slugs}.\n"
    "- report_date: the clinically meaningful date (prefer sample collection, "
    "then report/result date; ignore print / next-visit dates). ISO "
    "YYYY-MM-DD or null. date_source: collection|report|received|issue|"
    "consult|bare.\n"
    "- confidence: your certainty 0..1 for kind + categories.\n"
    'Respond exactly: {{"kind": "...", "categories": [...], "report_date": '
    '"YYYY-MM-DD" or null, "date_source": "...", "confidence": 0.0}}'
)


def enabled() -> bool:
    return bool(getattr(settings, "DOC_CLASSIFIER_VISION_MODEL", "")
               and getattr(settings, "DOC_CLASSIFIER_VISION_BASE", "")
               and getattr(settings, "DOC_CLASSIFIER_VISION_KEY", ""))


def _prep(image_bytes: bytes) -> str | None:
    """PNG/JPEG bytes -> a downscaled 'data:image/jpeg;base64,...' URL."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(image_bytes))
        im = im.convert("RGB")
        w, h = im.size
        if max(w, h) > _MAX_EDGE:
            f = _MAX_EDGE / max(w, h)
            im = im.resize((max(1, int(w * f)), max(1, int(h * f))))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82)
        return "data:image/jpeg;base64," + base64.standard_b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        logger.warning("doc_classifier_vision: image prep failed", exc_info=True)
        return None


def _post(payload: dict) -> str:
    key = settings.DOC_CLASSIFIER_VISION_KEY
    url = settings.DOC_CLASSIFIER_VISION_BASE.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    resp = None
    for attempt in range(_MAX_TRIES):
        resp = requests.post(url, json=payload, headers=headers, timeout=90)
        if resp.status_code == 400 and "response_format" in resp.text:
            payload.pop("response_format", None)
            continue
        if resp.status_code in (429, 413, 500, 502, 503) and attempt < _MAX_TRIES - 1:
            wait = min(30, int(resp.headers.get("retry-after") or 0) or 5 * (attempt + 1))
            logger.warning("doc_classifier_vision: %s from provider — retry %d in %ss",
                           resp.status_code, attempt + 1, wait)
            time.sleep(wait)
            continue
        break
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def classify_images(images: list) -> dict:
    """List of page-image bytes -> label dict. Best-effort; never raises."""
    images = [b for b in (images or []) if b][:_MAX_IMAGES]
    if not images or not enabled():
        return {}

    digest = hashlib.sha256(b"".join(images)).hexdigest()[:40]
    ck = "docvis:" + digest
    _c = _cache()
    hit = _c.get(ck)
    if hit is not None:
        return hit

    urls = [u for u in (_prep(b) for b in images) if u]
    if not urls:
        return {}

    sys_prompt = _SYSTEM.format(slugs=", ".join(report_types.SLUGS))
    content = [{"type": "text", "text": "Classify this document."}]
    content += [{"type": "image_url", "image_url": {"url": u}} for u in urls]
    payload = {
        "model": settings.DOC_CLASSIFIER_VISION_MODEL,
        "temperature": 0,
        "max_tokens": _MAX_TOKENS,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": content},
        ],
    }
    try:
        data = _loads(_post(payload))
    except Exception:
        logger.warning("doc_classifier_vision: call failed; keeping earlier result", exc_info=True)
        return {}
    if not data:
        logger.warning("doc_classifier_vision: empty/unparseable reply; keeping earlier result")
        return {}

    result = _sanitise(data)
    _c.set(ck, result, _CACHE_TTL)
    logger.info("doc_classifier_vision: kind=%s cats=%s date=%s conf=%s",
                result.get("kind"), result.get("categories"),
                result.get("report_date"), result.get("confidence"))
    return result
