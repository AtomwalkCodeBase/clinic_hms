"""
core/health_insight.py
------------------------
Writes the short "AI trends" narrative paragraph shown in the patient
app when someone explicitly taps to see what their previous records say
about one lab value — a THIRD LLM-backed stage, distinct from both
core.doc_classifier_llm (kind/panel/date) and core.lab_value_extractor
(reads the numbers off a report). This module never touches a document or
extracts a number itself; it only writes prose OVER numbers
core.lab_variation / PortalLabTrendsView already computed from
already-extracted, already confidence-gated ExtractedLabValue rows.

Same conventions as the other two LLM call sites on purpose:
  - No SDK: a raw OpenAI-compatible /chat/completions POST.
  - Never raises. Any failure/disabled-config -> None, and the caller shows
    a plain "couldn't generate an insight right now" rather than surfacing
    an exception — this is a nice-to-have narrative, not a pipeline stage
    anything downstream depends on.
  - The same 429/413/5xx retry with Retry-After honored, the same "drop
    response_format and retry once on a 400 that mentions it" tolerance —
    though this call doesn't request response_format at all (plain prose
    out, not JSON), so that branch is dead here but kept for symmetry with
    the other two modules in case a future prompt ever adds one.
  - A persistent, worker-shared cache (reuses caches["lab_extract"] rather
    than provisioning a fourth cache table for one more LLM call site)
    keyed by a hash of the exact points fed in — the narrative only
    changes when a new reading actually arrives, so re-opening "AI trends"
    against the same data doesn't re-bill the provider.

UNLIKE lab_value_extractor, this call is never triggered by a cron/
management command — only PortalHealthInsightNarrativeView, itself only
reachable by an explicit POST from the patient tapping "Yes, show me" in
the app. Nothing here runs on a GET or a page load.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time

import requests
from django.conf import settings
from django.core.cache import caches

logger = logging.getLogger(__name__)

_MAX_TRIES = 4
# Reasoning-tier models (openai/gpt-oss-20b included) spend output tokens on
# an internal scratchpad before the answer — a 2-3 sentence paragraph still
# needs the same 1024 floor core.doc_classifier_llm and core.lab_value_
# extractor already learned the hard way (see doc_classifier_llm.py's
# _MAX_TOKENS comment); anything tighter truncates the visible answer
# mid-sentence rather than the reasoning trace.
_MAX_TRIES = 4
_MAX_TOKENS = 1024
_CACHE_TTL = 60 * 60 * 24 * 7  # 7 days — shorter than extraction's 30/60; the underlying points change often
_MIN_CHARS = 20              # anything shorter than this is almost certainly a broken/empty response, not a real paragraph
_MAX_CHARS = 700

_SYSTEM = (
    "You are a calm, plain-language health assistant writing ONE short "
    "paragraph (2-3 sentences, no headings, no bullet points, no markdown) "
    "directly to a patient, in second person ('your hemoglobin', 'your "
    "doctor' — never 'their'/'the patient's'), about how a single lab "
    "value has changed across their own past reports. You are given the "
    "exact dated readings already extracted from their reports — never "
    "invent, round, or assume any reading not listed. "
    "Reference specific numbers and dates from the list you're given. "
    "Do not diagnose, name a disease, or recommend a treatment. If the "
    "trend moved in the direction noted as a concern below, end with a "
    "brief, gentle note that it's worth mentioning to their doctor — "
    "otherwise end on a neutral, informational note. Never say \"consult "
    "your doctor for medical advice\" as a generic disclaimer; the app "
    "already shows that separately — just write the paragraph itself."
)


def _enabled() -> bool:
    return bool(getattr(settings, "HEALTH_INSIGHT_LLM_KEY", "")
               and getattr(settings, "HEALTH_INSIGHT_LLM_BASE", "")
               and getattr(settings, "HEALTH_INSIGHT_LLM_MODEL", ""))


def _cache():
    try:
        return caches["lab_extract"]
    except Exception:
        return caches["default"]


def _post_text(payload: dict) -> str:
    key = settings.HEALTH_INSIGHT_LLM_KEY
    url = settings.HEALTH_INSIGHT_LLM_BASE.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    resp = None
    for attempt in range(_MAX_TRIES):
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        if resp.status_code == 400 and "response_format" in resp.text:
            payload.pop("response_format", None)
            continue
        if resp.status_code in (429, 413, 500, 502, 503) and attempt < _MAX_TRIES - 1:
            wait = min(20, int(resp.headers.get("retry-after") or 0) or 4 * (attempt + 1))
            logger.warning("health_insight: %s from provider — retry %d in %ss",
                           resp.status_code, attempt + 1, wait)
            time.sleep(wait)
            continue
        break
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _friendly_date(iso: str) -> str:
    """"2026-09-10" -> "10 Sep 2026" — the ISO form the endpoint passes in
    reads awkwardly inline in a sentence ("on 2026-09-10"); this is purely
    for the LLM's input phrasing, never re-parsed."""
    try:
        from datetime import datetime
        dt = datetime.strptime(iso, "%Y-%m-%d")
        return f"{dt.day} {dt.strftime('%b %Y')}"  # portable day-of-month — %-d/%#d aren't cross-platform
    except (ValueError, TypeError):
        return iso


def _points_text(points: list[dict], unit: str) -> str:
    lines = []
    for p in points:
        bit = f"- {_friendly_date(p['date'])}: {p['value']}{unit}"
        if p.get("status") and p["status"] != "normal":
            bit += f" ({p['status']})"
        lines.append(bit)
    return "\n".join(lines)


def generate_trend_narrative(parameter_label: str, unit: str, points: list[dict], concern: str) -> str | None:
    """
    points: chronological [{"date": "YYYY-MM-DD", "value": float,
    "status": "high"|"low"|"normal"|None}, ...] — exactly what
    PortalLabTrendsView already computes, never re-derived here.
    concern: "higher_is_concern" | "lower_is_concern" | "neutral", from
    core.lab_variation.PARAMETER_DIRECTION — steers only the closing tone,
    never which facts get stated.

    Returns a short paragraph, or None if disabled, misconfigured, the
    provider call failed, or the response came back empty/malformed —
    never raises, so a flaky provider degrades to "no narrative today"
    rather than a 500 on an otherwise-working screen.
    """
    if not points or len(points) < 2 or not _enabled():
        return None

    points_text = _points_text(points, unit)
    ck = "healthnarr:" + hashlib.sha256(
        f"{parameter_label}|{unit}|{concern}|{points_text}".encode("utf-8")
    ).hexdigest()[:40]
    _c = _cache()
    hit = _c.get(ck)
    if hit is not None:
        return hit or None  # a cached None-as-failure stays None, never re-tried within the TTL

    concern_hint = {
        "higher_is_concern": "a HIGHER value is the one worth flagging for this test",
        "lower_is_concern": "a LOWER value is the one worth flagging for this test",
        "neutral": "neither direction is inherently more concerning than the other for this test",
    }.get(concern, "neither direction is inherently more concerning than the other for this test")

    payload = {
        "model": settings.HEALTH_INSIGHT_LLM_MODEL,
        "temperature": 0.4,
        "max_tokens": _MAX_TOKENS,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": (
                f"Test: {parameter_label}\n"
                f"Readings, oldest first:\n{points_text}\n\n"
                f"Private context for your closing note only — do not restate this "
                f"as a sentence, just let it steer whether you end on a flagging "
                f"note or a neutral one: for {parameter_label}, {concern_hint}."
            )},
        ],
    }
    try:
        content = (_post_text(payload) or "").strip()
    except Exception:
        logger.warning("health_insight: narrative call failed", exc_info=True)
        _c.set(ck, "", _CACHE_TTL)
        return None

    # Strip stray markdown fencing/quotes a model sometimes wraps prose in —
    # this is meant to render as plain text in the app, not markdown.
    content = content.strip("`\"' \n")
    if not (_MIN_CHARS <= len(content) <= _MAX_CHARS):
        logger.warning("health_insight: narrative out of size bounds (%d chars) — discarding", len(content))
        _c.set(ck, "", _CACHE_TTL)
        return None

    _c.set(ck, content, _CACHE_TTL)
    return content
