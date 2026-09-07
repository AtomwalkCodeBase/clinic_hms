"""
apps/patients/consult_pad_recognition.py
-----------------------------------------
Turn the photographed handwritten SOAP pad into structured text.

A vision model transcribes the handwriting verbatim and splits it into the
four SOAP sections. The encounter page then fills those fields (on the
doctor pressing "Load handwritten note") for review and editing — the
model's output is never treated as final, it's a first draft the clinician
signs off.

Provider-agnostic: any OpenAI-compatible `/chat/completions` endpoint works
(OpenAI, Groq, OpenRouter, Together, a local vLLM/Ollama). Configure via
settings.CONSULT_PAD_LLM_BASE / _MODEL / _KEY. Called with `requests`
(already a dependency) — no vendor SDK.

Design choices:
  - VERBATIM transcription only. The prompt forbids summarising, correcting,
    expanding, or inventing clinical content — a mis-read drug dose that gets
    "helpfully" normalised is far more dangerous than an obvious typo the
    doctor catches on review.
  - Graceful no-op. With no key set, recognise() returns status="skipped";
    the handwritten PDF is still stored and the doctor types the note in.
"""

import base64
import io
import json
import logging
import re
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# Vision tokens are expensive and Groq's per-model TPM budget is small — a
# full-res phone photo of an A4 page can be ~4k+ tokens on its own. Downscale
# hard and re-encode as JPEG before sending; handwriting stays legible well
# below this and each page then costs ~1k tokens.
_MAX_EDGE = 800
_JPEG_Q = 80


def _prep_image(png_bytes: bytes) -> str:
    """Raw PNG bytes -> a compact 'data:image/jpeg;base64,...' URL."""
    from PIL import Image
    im = Image.open(io.BytesIO(png_bytes))
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    im.thumbnail((_MAX_EDGE, _MAX_EDGE * 3))  # cap width; allow tall pages
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=_JPEG_Q)
    return "data:image/jpeg;base64," + base64.standard_b64encode(buf.getvalue()).decode("ascii")

_SYSTEM = """You read a photographed HANDWRITTEN medical consultation note and turn it into a structured draft the doctor will review before signing.

TRANSCRIPTION RULES
- Read the handwriting VERBATIM. Do NOT summarise, rephrase, expand, translate, or invent any clinical content. Keep abbreviations, doses, units and numbers exactly as written.
- If a word or number is genuinely illegible, write [illegible]. Never guess a dose, and never guess which drug an illegible scrawl is.
- If there are multiple pages, read them in order as one continuous note.

Then produce this JSON (ONLY the JSON, no prose, no code fences):
{
  "is_clinical_note": true, // false if the image is blank, unreadable, or clearly not a medical consultation note
  "confidence": 0.0,      // 0.0-1.0 — your overall confidence that this is a legible handwritten clinical note you transcribed correctly. Use 0.0-0.2 for a blank / unreadable / not-a-note image.
  "subjective": "",       // symptoms/history in the patient's words, chief complaint, duration, relevant negatives
  "objective": "",        // examination findings, vital signs, measurable observations
  "assessment": "",       // the diagnosis / clinical impression text as written
  "plan": "",             // the plan text as written (medications, orders, advice, follow-up) — keep it verbatim
  "investigations": "",   // ONLY lab/imaging tests ordered (e.g. "CBC, NS1 antigen, chest X-ray"), else ""
  "advice": "",           // ONLY non-drug advice to the patient (rest, fluids, diet, warning signs), else ""
  "follow_up_days": null, // integer number of days until review if stated ("review in 2 days" -> 2, "R/v after 1 week" -> 7), else null
  "diagnoses": [          // one entry per distinct diagnosis / impression found in the note
    {"code": "", "description": ""}   // description = the diagnosis text; code = your best ICD-10 code or "" if unsure
  ],
  "prescription": [       // one entry per medication written (look for "Rx", "Tab", "Cap", "Syp", "Inj", drug lines anywhere in the note)
    {
      "drug_name": "",        // the medicine name, without the "Tab/Cap/Syp" prefix. If the handwriting is an OBVIOUS misspelling of a real drug, give its STANDARD spelling (e.g. "paracimtamol" -> "Paracetamol", "azithro" -> "Azithromycin"). If you cannot tell which drug is meant, keep it exactly as written. NEVER swap in a different drug.
      "dosage": "",           // strength/amount as written, e.g. "500 mg", "1 tab", "10 ml"; "" if none written
      "frequency": "",        // MUST be one of: od (once daily / OD / QD / 1-0-0), bd (twice daily / BD / BID / 1-0-1), td (three times / TID / TDS / 1-1-1), qid (four times / QID / QDS), sos (SOS / PRN / as needed), stat (STAT / immediately), nocte (at night / HS / bedtime), mane (in the morning / OM). If unclear, use "od".
      "route": "",            // one of: oral, iv, im, sc, topical, inhaled, rectal, sublingual. Default "oral".
      "duration_days": null,  // integer days if written ("x 5 days" -> 5), else null
      "instructions": "",     // e.g. "after food", "before sleep"; "" if none
      "confidence": 0.0       // 0.0-1.0 — confidence that this whole line (drug + dose + frequency + duration) was read correctly
    }
  ]
}

STRUCTURED-EXTRACTION RULES
- If the image is blank, unreadable, or clearly not a medical consultation note, set "is_clinical_note" to false and "confidence" to 0.0, leave every text field "", and return "diagnoses": [] and "prescription": []. Do NOT invent content to fill the shape.
- Extract every medication and every diagnosis you can read, even though they also appear inside the "plan"/"assessment" text. Do NOT invent a drug, dose, or diagnosis that is not written.
- The `drug_name` field (and ONLY that field) may be corrected to a medicine's standard spelling when the handwriting is an obvious misspelling of a real drug. NEVER change a dose, strength, number, unit, frequency, route or duration — those stay exactly as written. NEVER replace a drug with a different one, and never invent one.
- If the note contains no medications, "prescription" is []. If no separate diagnosis, "diagnoses" is [].
- raw_text (add this key too) holds the FULL verbatim transcription of everything written, in reading order — UNALTERED, including any misspellings."""

_USER_TEXT = "Read this handwritten consultation note and return the JSON described in your instructions."

# Per-tab steer. The consult session has a Prescription tab and an Internal
# Note tab; telling the model which one it's looking at improves accuracy and
# stops it hallucinating drugs into a plain note (or vice versa).
_FOCUS_HINT = {
    "rx": " This page is PRIMARILY THE PRESCRIPTION: fill the `prescription` array with every medication written. Doctors often also jot a little clinical context on the same page — if any is present, still capture it: symptoms/history -> `subjective`, measured vitals or exam findings -> `objective`, non-drug advice (rest, fluids, diet, warning signs) -> `advice`, lab/imaging ordered -> `investigations`, review interval -> `follow_up_days`. Leave `assessment`, `plan` and `diagnoses` empty unless a diagnosis is clearly written.",
    "note": " This is a CLINICAL NOTE page with NO prescription: fill the SOAP fields, `diagnoses`, `investigations`, `advice` and `follow_up_days`, and leave `prescription` empty.",
    "all": "",
}

# For the multi-page path: one image per request (so each request fits the
# provider's per-minute token budget), then a final text-only structuring
# call over the joined transcription.
_TRANSCRIBE_SYS = """You transcribe ONE photographed page of a HANDWRITTEN medical consultation note.
- Transcribe VERBATIM, line by line, top to bottom. Do NOT summarise, correct, rephrase, expand, translate or invent anything. Keep abbreviations, drug names, doses, units and numbers exactly as written.
- If a word or number is genuinely illegible, write [illegible]. Never guess a dose or a drug name.
- Output ONLY the transcribed text of this page. No commentary, no headings, no JSON."""

_STRUCTURE_SYS = _SYSTEM.replace(
    "You read a photographed HANDWRITTEN medical consultation note and turn it into",
    "You are given the plain-text transcription of a handwritten medical consultation note. Turn it into",
).replace(
    "TRANSCRIPTION RULES\n- Read the handwriting VERBATIM. Do NOT summarise, rephrase, expand, translate, or invent any clinical content. Keep abbreviations, doses, units and numbers exactly as written.\n- If a word or number is genuinely illegible, write [illegible]. Never guess a dose, and never guess which drug an illegible scrawl is.\n- If there are multiple pages, read them in order as one continuous note.\n\n",
    "Do NOT change wording, EXCEPT the drug_name field may be corrected to a medicine's standard spelling when the transcription is an obvious misspelling of a real drug. Never change a dose, number, unit, frequency, route or duration; never substitute a different drug. Otherwise only reorganise what is given.\n\n",
)

_EMPTY = {
    "subjective": "", "objective": "", "assessment": "", "plan": "", "raw_text": "",
    "investigations": "", "advice": "", "follow_up_days": None,
    "diagnoses": [], "prescription": [], "investigations_resolved": [],
    "is_clinical_note": True, "confidence": None,
    "low_ink": False, "page_warnings": "",
}

_FREQ_OK = {"od", "bd", "td", "qid", "sos", "stat", "nocte", "mane"}
_ROUTE_OK = {"oral", "iv", "im", "sc", "topical", "inhaled", "rectal", "sublingual"}

# ── Frequency / sig shorthand ──────────────────────────────────────────────
# Doctors write the dosing frequency a dozen different ways, and a small
# vision model often drops it into `instructions` instead of `frequency`
# ("3 days 2donly" -> instructions="2donly", frequency=""). This maps the
# common written forms to the canonical enum. Checked in order — specific
# words first, then the "N-N-N" grid, then "N daily"/"N times", then plain OD.
_N_TO_FREQ = {1: "od", 2: "bd", 3: "td", 4: "qid"}
_FREQ_PATTERNS = [
    ("stat",  re.compile(r"\b(stat|immediately|at once|right now)\b", re.I)),
    ("sos",   re.compile(r"\b(sos|p\.?r\.?n|as needed|if needed|when required|as required)\b", re.I)),
    ("nocte", re.compile(r"\b(nocte|noct|h\.?s|at night|at bed\s?time|bed\s?time|before sleep|every night)\b", re.I)),
    ("mane",  re.compile(r"\b(mane|o\.?m|in the morning|every morning|morning dose)\b", re.I)),
    ("qid",   re.compile(r"\b(qid|qds|q\.?i\.?d|q6h|1\s*-\s*1\s*-\s*1\s*-\s*1|four times)\b", re.I)),
    ("td",    re.compile(r"\b(tds|tid|t\.?i\.?d|q8h|thrice|1\s*-\s*1\s*-\s*1|three times)\b", re.I)),
    ("bd",    re.compile(r"\b(bd|bid|b\.?i\.?d|bpd|q12h|twice|1\s*-\s*0\s*-\s*1)\b", re.I)),
    ("od",    re.compile(r"\b(od|qd|o\.?d|q\.?d|q24h|1\s*-\s*0\s*-\s*0|once daily|once a day|every day|daily)\b", re.I)),
]
# "N daily / N times / N x" — tolerant of the model's misreads of "daily"
# (2donly, 2dly, 3daly …) and of a missing space.
_FREQ_NUM_RE = re.compile(r"\b([1-4])\s*(?:x|times?|d[a-z]{0,3}ly|/\s*day|per\s*day|a\s*day)\b", re.I)


def _freq_from_text(s: str):
    """(canonical enum, matched-substring) for the first frequency form found
    in `s`, or (None, None). Pure."""
    s = (s or "").strip()
    if not s:
        return None, None
    m = _FREQ_NUM_RE.search(s)
    if m:
        f = _N_TO_FREQ.get(int(m.group(1)))
        if f:
            return f, m.group(0)
    for enum, rx in _FREQ_PATTERNS:
        m = rx.search(s)
        if m:
            return enum, m.group(0)
    return None, None


def _strip_span(s: str, frag: str) -> str:
    """Remove the first occurrence of `frag` from `s` and tidy leftover
    punctuation / double spaces."""
    if not frag:
        return s
    i = s.lower().find(frag.lower())
    if i < 0:
        return s
    out = (s[:i] + s[i + len(frag):])
    return re.sub(r"\s{2,}", " ", out).strip(" ,;-·").strip()

# ── Local pixel pre-check ────────────────────────────────────────────────────
# Runs before any API call. A pen/finger stroke on the white pad is near-black;
# this lets us answer "is the page blank / barely-written?" ourselves instead
# of paying for a vision call and then trusting the model's self-report.
_INK_LUMA_MAX = 200          # greyscale value at/below which a pixel counts as ink
_BLANK_INK_FRACTION = 0.0025  # below this on every page → treat as blank, skip the model
_SPARSE_INK_FRACTION = 0.010  # mean below this (but not blank) → cap confidence


def _ink_fraction(png_bytes: bytes) -> float:
    """Fraction of pixels dark enough to be pen strokes. Fails OPEN (1.0) so a
    decode error never suppresses a real note."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(png_bytes)).convert("L")
        im.thumbnail((400, 1200))
        px = list(im.getdata())
        if not px:
            return 0.0
        return sum(1 for p in px if p <= _INK_LUMA_MAX) / len(px)
    except Exception:
        logger.debug("consult-pad ink-fraction check failed", exc_info=True)
        return 1.0


def _blankness(page_images: list) -> tuple:
    """(_all_blank, _sparse) from local pixel inspection only."""
    fracs = [_ink_fraction(p) for p in page_images]
    if not fracs:
        return True, True
    all_blank = all(f < _BLANK_INK_FRACTION for f in fracs)
    sparse = (sum(fracs) / len(fracs)) < _SPARSE_INK_FRACTION
    return all_blank, sparse


# ── Dose sanity ─────────────────────────────────────────────────────────────
_DOSE_UNIT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(mcg|microgram|ug|mg|gm|g|ml|iu|units?|%)", re.I)
_DOSE_AMOUNT_RE = re.compile(
    r"(?:\d+(?:\.\d+)?|½|¼|\bhalf\b|\bone\b|\btwo\b)\s*"
    r"(?:tab|tablet|cap|capsule|tsp|tbsp|puff|drop|spray|sachet|amp|scoop|ml|application)s?", re.I)
# Loose per-administration ceilings — above these is almost always a mis-read
# and worth a second look, not a hard block.
_DOSE_MAX = {"mcg": 5000.0, "ug": 5000.0, "mg": 4000.0, "g": 5.0, "gm": 5.0, "ml": 60.0, "iu": 100000.0}


def _check_dose(dosage: str) -> list:
    """Conservative heuristic flags for an obviously-off or unusable dose
    string — only the clear cases, so it doesn't cry wolf on normal orders."""
    s = (dosage or "").strip()
    if not s:
        return []  # 'dose missing' is flagged separately upstream
    flags = []
    m = _DOSE_UNIT_RE.search(s)
    if m:
        val = float(m.group(1))
        unit = m.group(2).lower()
        unit = {"microgram": "mcg", "gm": "g", "unit": "iu", "units": "iu"}.get(unit, unit)
        cap = _DOSE_MAX.get(unit)
        if val == 0:
            flags.append("dose reads as zero — verify")
        elif cap and val > cap:
            flags.append(f"unusually high dose ({m.group(0).strip()}) — verify")
    elif not _DOSE_AMOUNT_RE.search(s) and not re.search(r"\d", s):
        flags.append("dose is not a clear amount — verify")
    return flags


def _as_int(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str) and v.strip().lstrip("-").isdigit():
        return int(v.strip())
    return None


def _as_float(v):
    """Best-effort float clamped to [0, 1]; None if not parseable."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return max(0.0, min(1.0, f))


# A recognised result is "empty" (blank page / nothing usable written) when the
# model returned no structured content and only a trivial amount of raw text.
# The encounter page treats this as its own state ("pages look blank") rather
# than a normal load that happens to fill nothing.
_MIN_MEANINGFUL_CHARS = 6


def _has_content(recognized: dict) -> bool:
    if recognized.get("prescription") or recognized.get("diagnoses"):
        return True
    for k in ("subjective", "objective", "assessment", "plan", "investigations", "advice"):
        if (recognized.get(k) or "").strip():
            return True
    return len((recognized.get("raw_text") or "").strip()) >= _MIN_MEANINGFUL_CHARS


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    try:
        obj = json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise ValueError("model did not return JSON")
        obj = json.loads(m.group(0))
    if not isinstance(obj, dict):
        raise ValueError("model did not return a JSON object")

    out = dict(_EMPTY)
    for k in ("subjective", "objective", "assessment", "plan", "raw_text", "investigations", "advice"):
        v = obj.get(k, "")
        out[k] = v.strip() if isinstance(v, str) else ("" if v is None else str(v))

    out["is_clinical_note"] = obj.get("is_clinical_note") is not False
    out["confidence"] = _as_float(obj.get("confidence"))

    fd = _as_int(obj.get("follow_up_days"))
    out["follow_up_days"] = fd if (fd is not None and fd > 0) else None

    dx = obj.get("diagnoses") or []
    out["diagnoses"] = [
        {"code": str(d.get("code", "")).strip(), "description": str(d.get("description", "")).strip()}
        for d in dx if isinstance(d, dict) and str(d.get("description", "")).strip()
    ]

    rx = obj.get("prescription") or []
    clean = []
    for it in rx:
        if not isinstance(it, dict):
            continue
        name = str(it.get("drug_name", "")).strip()
        if not name:
            continue
        route = str(it.get("route", "")).strip().lower()
        dur = _as_int(it.get("duration_days"))
        dur_val = dur if (dur is not None and dur > 0) else None
        dosage = str(it.get("dosage", "")).strip()
        instr = str(it.get("instructions", "")).strip()

        # Frequency: normalise the model's value (handles "1-0-1", "twice",
        # "BD", …), and if it's still missing, try to recover one the model
        # dropped into `instructions` / `dosage` ("3 days 2donly" -> bd) and
        # strip that token back out of the instructions.
        raw_freq = str(it.get("frequency", "")).strip().lower()
        mapped = raw_freq if raw_freq in _FREQ_OK else (_freq_from_text(raw_freq)[0] if raw_freq else None)
        freq_from = ""
        if not mapped:
            for label, src in (("instructions", instr), ("dose", dosage)):
                m_enum, m_frag = _freq_from_text(src)
                if m_enum:
                    mapped = m_enum
                    if label == "instructions":
                        instr = _strip_span(instr, m_frag)
                    freq_from = label
                    break
        freq_ok = mapped in _FREQ_OK

        # Surfaced to the doctor on the review panel — a line missing a dose or
        # duration, or one where we had to assume a frequency, needs a look
        # before it goes into the record.
        flags = []
        if not dosage:
            flags.append("dose missing")
        else:
            flags.extend(_check_dose(dosage))
        if dur_val is None:
            flags.append("duration missing")
        if not freq_ok:
            flags.append("frequency assumed OD")
        elif freq_from:
            flags.append(f"frequency read from {freq_from} text")

        clean.append({
            "drug_name": name,
            "dosage": dosage,
            "frequency": mapped if freq_ok else "od",
            "frequency_defaulted": not freq_ok,
            "route": route if route in _ROUTE_OK else "oral",
            "duration_days": dur_val,
            "instructions": instr,
            "confidence": _as_float(it.get("confidence")),
            "flags": flags,
        })
    out["prescription"] = clean
    return out


def _post_chat(payload: dict) -> str:
    """
    POST an OpenAI-compatible chat request with retry-on-rate-limit, and
    return the assistant message content. Groq reports a per-minute
    token-budget overrun as 413 (not 429) on the vision path, so both are
    treated as retryable; it also honours a `retry-after` header.
    """
    key = settings.CONSULT_PAD_LLM_KEY
    url = settings.CONSULT_PAD_LLM_BASE.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    _MAX_TRIES = 6
    resp = None
    for attempt in range(_MAX_TRIES):
        resp = requests.post(url, json=payload, headers=headers, timeout=120)
        if resp.status_code == 400 and "response_format" in resp.text:
            payload.pop("response_format", None)
            continue
        if resp.status_code in (429, 413) and attempt < _MAX_TRIES - 1:
            wait = int(resp.headers.get("retry-after") or 0) or (12 * (attempt + 1))
            logger.warning("consult-pad LLM rate-limited (%s) — retry %d/%d in %ss",
                           resp.status_code, attempt + 1, _MAX_TRIES - 1, wait)
            time.sleep(wait)
            continue
        break
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _transcribe_page(png_bytes: bytes) -> str:
    """One page image -> plain verbatim text (one request, fits a small TPM)."""
    return _post_chat({
        "model": settings.CONSULT_PAD_LLM_MODEL,
        "max_tokens": 2000,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": _TRANSCRIBE_SYS},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": _prep_image(png_bytes)}},
                {"type": "text", "text": "Transcribe this page verbatim."},
            ]},
        ],
    }).strip()


def _structure_text(full_text: str, focus: str = "all") -> dict:
    """Joined transcription -> the structured SOAP/Dx/Rx JSON (text-only call)."""
    content = _post_chat({
        "model": settings.CONSULT_PAD_LLM_MODEL,
        "max_tokens": 4000,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _STRUCTURE_SYS},
            {"role": "user", "content": f"Transcribed handwritten note:\n\n{full_text}\n\nReturn the JSON described in your instructions.{_FOCUS_HINT.get(focus, '')}"},
        ],
    })
    out = _parse_json(content)
    out["raw_text"] = full_text
    return out


def recognise(page_images: list, *, focus: str = "all") -> dict:
    """
    page_images: list of raw PNG byte strings, in page order.
    focus: "all" | "rx" | "note" — which consult-session tab these pages are.

    Returns {"status": "done" | "empty" | "skipped" | "failed",
             "recognized": {subjective, objective, assessment, plan, raw_text,
                            diagnoses, prescription, investigations, advice,
                            follow_up_days, is_clinical_note, confidence},
             "error": ""}.
    "empty" means the pages were blank / unreadable / not a clinical note —
    nothing to load, and the encounter page says so instead of silently
    filling nothing.
    Never raises — a recognition failure must not lose the handwritten note.

    One page  -> a single image->JSON call (fast).
    Many pages -> transcribe each page on its own (so no single request blows
    the provider's per-minute token budget), then one text-only structuring
    call over the joined transcription.
    """
    key = settings.CONSULT_PAD_LLM_KEY
    if not key:
        return {"status": "skipped", "recognized": dict(_EMPTY), "error": ""}
    if not page_images:
        return {"status": "failed", "recognized": dict(_EMPTY), "error": "no pages"}

    # Local pixel pre-check — a blank pad never reaches the model.
    all_blank, sparse_ink = _blankness(page_images)
    if all_blank:
        logger.info("consult-pad recognition: pages blank on pixel check (pages=%d) — skipped model",
                    len(page_images))
        return {"status": "empty", "recognized": dict(_EMPTY), "error": ""}

    try:
        page_warnings = ""
        if len(page_images) == 1:
            content = _post_chat({
                "model": settings.CONSULT_PAD_LLM_MODEL,
                "max_tokens": 4000,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": _prep_image(page_images[0])}},
                        {"type": "text", "text": _USER_TEXT + _FOCUS_HINT.get(focus, "")},
                    ]},
                ],
            })
            recognized = _parse_json(content)
            if not recognized["raw_text"]:
                recognized["raw_text"] = "\n".join(
                    recognized[k] for k in ("subjective", "objective", "assessment", "plan") if recognized[k]
                )
        else:
            # Per-page transcription is resilient: one page failing must not
            # discard the pages that read fine.
            page_texts, failed_pages = [], []
            for idx, png in enumerate(page_images):
                try:
                    page_texts.append(_transcribe_page(png))
                except Exception:
                    logger.warning("consult-pad: page %d/%d transcription failed",
                                   idx + 1, len(page_images), exc_info=True)
                    failed_pages.append(idx + 1)
                    page_texts.append("")
                if idx < len(page_images) - 1:
                    time.sleep(4)  # space requests so rate-limit retries stay rare
            full = "\n\n".join(t for t in page_texts if t).strip()
            if not full:
                if failed_pages:
                    return {"status": "failed", "recognized": dict(_EMPTY),
                            "error": "all pages unreadable"}
                return {"status": "empty", "recognized": dict(_EMPTY), "error": ""}
            recognized = _structure_text(full, focus=focus)
            if failed_pages:
                page_warnings = (
                    f"{len(failed_pages)} of {len(page_images)} page(s) could not be read "
                    f"(page {', '.join(map(str, failed_pages))}) — load again or add them by hand."
                )

        recognized["page_warnings"] = page_warnings
        if sparse_ink:
            # Barely anything on the page — don't let a confident-sounding model
            # push it past the encounter page's low-confidence gate.
            recognized["low_ink"] = True
            c = recognized.get("confidence")
            recognized["confidence"] = 0.3 if c is None else min(c, 0.3)

        if recognized.get("is_clinical_note") is False or not _has_content(recognized):
            logger.info("consult-pad recognition: blank / not-a-note (model=%s pages=%d)",
                        settings.CONSULT_PAD_LLM_MODEL, len(page_images))
            return {"status": "empty", "recognized": recognized, "error": ""}

        logger.info("consult-pad recognition ok: model=%s pages=%d chars=%d conf=%s low_ink=%s",
                    settings.CONSULT_PAD_LLM_MODEL, len(page_images), len(recognized["raw_text"]),
                    recognized.get("confidence"), recognized.get("low_ink"))
        return {"status": "done", "recognized": recognized, "error": ""}
    except Exception as exc:  # noqa: BLE001 — must never propagate
        logger.exception("consult-pad recognition failed")
        return {"status": "failed", "recognized": dict(_EMPTY), "error": str(exc)[:500]}
