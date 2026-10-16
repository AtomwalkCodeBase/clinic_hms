"""Patient-side helpers: portal access, booking sync, and the consult pad's handwriting recognition and aliases."""
import logging
import base64
import hashlib
import io
import json
import re
import time
import requests
from apps.patients.models import Patient
from core.response import error
from django.conf import settings


def resolve_target_awpid_and_dob(request):
    """
    Shared helper — resolves which patient (self or a linked family member)
    a portal request is about, and returns (awpid, date_of_birth, error_response).
    Mirrors the ownership check already used by PortalMyRecordsView /
    PortalHealthSummaryView: a family member's AWPID is only valid here if
    PatientRelationship actually links it to this account.
    """
    acct = accounts().get(pk=request.user.id)
    target_awpid = (request.query_params.get("patient_awpid") or request.data.get("patient_awpid") or "").strip() or acct.awpid

    if target_awpid == acct.awpid:
        return target_awpid, acct.date_of_birth, None

    from apps.patients.models import PatientRelationship
    is_family = PatientRelationship.objects.using("default").filter(
        guardian__awpid=acct.awpid, dependent__awpid=target_awpid,
    ).exists()
    if not is_family:
        return None, None, error("That patient isn't linked to your account.", status=403)

    identity = Patient.objects.using("default").filter(awpid=target_awpid).first()
    return target_awpid, (identity.date_of_birth if identity else None), None


logger = logging.getLogger(__name__)
def sync_patient_booking(appointment, db_name):
    """
    Best-effort — booking must never fail because this couldn't run. If
    neither the booked patient nor (for a dependent) their guardian has ever
    created a patient portal account, there's genuinely nothing to sync to;
    that's the normal case for most front-desk walk-ins, not an error.
    """
    try:
        from apps.patients.models import Patient, PatientRelationship
        from apps.patients.models import PatientBooking
        from apps.hospital_master.models import Hospital

        patient_awpid = (appointment.patient_awpid or "").strip()
        if not patient_awpid:
            return

        # Already synced? (e.g. this Appointment was actually created via the
        # portal's own booking view, which writes its PatientBooking inline —
        # avoid a duplicate row if this ever gets called from both places.)
        if PatientBooking.objects.using("default").filter(appointment_id=appointment.id).exists():
            return

        acct = accounts().filter(awpid=patient_awpid).first()
        if not acct:
            # Not the account owner themself — maybe a dependent, in which
            # case the booking should show up on the GUARDIAN's dashboard
            # (same as when a patient books a family member through the
            # portal directly — see PortalBookView.post).
            rel = PatientRelationship.objects.using("default").filter(
                dependent__awpid=patient_awpid
            ).first()
            if rel:
                acct = accounts().filter(awpid=rel.guardian.awpid).first()

        if not acct:
            return  # no portal account anywhere in this chain — nothing to sync

        hospital = Hospital.objects.using("default").filter(db_name=db_name).first()
        if not hospital:
            return

        PatientBooking.objects.using("default").create(
            booked_by=acct,
            hospital=hospital,
            appointment_id=appointment.id,
            doctor_name=appointment.doctor_name or "",
            scheduled_date=appointment.scheduled_date,
            chief_complaint=appointment.chief_complaint or "",
            status=appointment.status,
            patient=Patient.objects.using("default").filter(awpid=patient_awpid).first(),
        )
    except Exception:
        # Same graceful-degradation pattern as core.audit.log_action — a
        # booking that already succeeded in the hospital DB must not fail (or
        # roll back) just because this best-effort portal-visibility sync hit
        # an unexpected error.
        logger.warning("sync_patient_booking failed for appointment_id=%s db=%s", appointment.id, db_name, exc_info=True)


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
    "rx": " This page is PRIMARILY THE PRESCRIPTION: fill the `prescription` array with every medication written. Doctors also write clinical context on the same page — capture everything that IS written: symptoms/history -> `subjective`, measured vitals or exam findings -> `objective`, the diagnosis / clinical impression if one is written -> `assessment` (and `diagnoses`), the non-drug plan — advice, rest, fluids, follow-up, tests ordered -> `plan` / `advice` / `investigations` / `follow_up_days`. Do NOT repeat the medication lines inside `plan`; those go ONLY in `prescription`. Do not invent an assessment or plan that is not written.",
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
# this lets us answer "is this page blank?" ourselves instead of paying for a
# vision call and then trusting the model's self-report.
_INK_LUMA_MAX = 200          # greyscale value at/below which a pixel counts as ink
# Only a canvas essentially untouched by pen falls below this. A page with even
# a few scrawled words sits well clear of it, so a real (if sparse) note is
# never mistaken for blank and dropped. Kept deliberately low: a genuine note
# in a light hand should still reach the model (and get its confidence capped
# by _SPARSE_INK_FRACTION), not be discarded here.
_BLANK_INK_FRACTION = 0.0006
_SPARSE_INK_FRACTION = 0.010  # mean over the written pages below this → cap confidence
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
def _partition_pages(page_images: list) -> tuple:
    """(written_pages, blank_page_numbers) from local pixel inspection.

    A sheet the patient never wrote on — an extra page added by accident, a
    trailing empty page — is dropped here so it can't sink a note that WAS
    written on the other pages. Only when every page is blank does the caller
    treat the whole load as empty.
    """
    written, blank_nums = [], []
    for idx, png in enumerate(page_images):
        if _ink_fraction(png) >= _BLANK_INK_FRACTION:
            written.append(png)
        else:
            blank_nums.append(idx + 1)
    return written, blank_nums
def _is_sparse(page_images: list) -> bool:
    """True when the written pages carry, on average, very little ink — a real
    note in a light hand: cap the model's confidence rather than trust it."""
    if not page_images:
        return False
    fracs = [_ink_fraction(p) for p in page_images]
    return (sum(fracs) / len(fracs)) < _SPARSE_INK_FRACTION
# A per-page transcription that is really just the model saying "nothing here".
# Dropped from the joined text so one such page can't drag a multi-page note
# into a false "not a clinical note".
_BLANKISH_TRANSCRIPTION_RE = re.compile(
    r"^[\s\W]*(?:\[?\s*(?:blank(?:\s+page)?|empty|illegible|"
    r"no(?:thing)?(?:\s+(?:text|writing|content|written|here|visible))*|"
    r"this\s+page\s+(?:is|appears\s+(?:to\s+be\s+)?)\s*blank)\s*\]?[.\s]*)+$",
    re.I,
)
def _looks_blank_transcription(text: str) -> bool:
    t = (text or "").strip()
    if len(re.sub(r"[^0-9A-Za-z]+", "", t)) < 3:
        return True
    return bool(_BLANKISH_TRANSCRIPTION_RE.match(t))
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
    # Recognition is serialised per session (one call at a time), so a single
    # request can afford a few honest retries against the provider's small
    # per-minute budget. Kept bounded so a hard quota wall still surfaces as
    # `failed` (→ "type it in") rather than hanging; the doctor's Load button
    # auto-polls, so a slow success is fine.
    _MAX_TRIES = 5
    resp = None
    for attempt in range(_MAX_TRIES):
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        if resp.status_code == 400 and "response_format" in resp.text:
            payload.pop("response_format", None)
            continue
        if resp.status_code in (429, 413) and attempt < _MAX_TRIES - 1:
            wait = min(20, int(resp.headers.get("retry-after") or 0) or (5 * (attempt + 1)))
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
        "max_tokens": 1200,
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
        "max_tokens": 2500,
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
def _page_key(png_bytes: bytes) -> str:
    return hashlib.sha1(png_bytes).hexdigest()
def recognise(page_images: list, *, focus: str = "all", page_text_cache: dict | None = None) -> dict:
    """
    page_images: list of raw PNG byte strings, in page order.
    focus: "all" | "rx" | "note" — which consult-session tab these pages are.
    page_text_cache: {sha1(png): verbatim_text} from a PRIOR compile of this
        tab. Pages whose bytes are unchanged are reused from here and cost no
        model call — so a re-load after the doctor "adds something" only
        transcribes the NEW pages, then re-structures the whole note. The
        result carries an updated cache back under recognized["_page_texts"].

    Returns {"status": "done" | "empty" | "skipped" | "failed",
             "recognized": {subjective, objective, assessment, plan, raw_text,
                            diagnoses, prescription, investigations, advice,
                            follow_up_days, is_clinical_note, confidence,
                            _page_texts},
             "error": ""}.
    "empty" means the pages were blank / unreadable / not a clinical note.
    Never raises — a recognition failure must not lose the handwritten note.
    """
    key = settings.CONSULT_PAD_LLM_KEY
    cache_in = dict(page_text_cache or {})
    if not key:
        return {"status": "skipped", "recognized": dict(_EMPTY), "error": ""}
    if not page_images:
        return {"status": "failed", "recognized": dict(_EMPTY), "error": "no pages"}

    # Local pixel pre-check. Drop any sheet with essentially no pen on it, so
    # one stray blank page can't sink a note written on the others. Only when
    # every page is blank is the whole load "empty".
    written_pages, blank_page_nums = _partition_pages(page_images)
    if not written_pages:
        logger.info("consult-pad recognition: all %d page(s) blank on pixel check — skipped model",
                    len(page_images))
        return {"status": "empty", "recognized": dict(_EMPTY, _page_texts={}), "error": ""}

    sparse_ink = _is_sparse(written_pages)
    blank_note = ""
    if blank_page_nums:
        nums = ", ".join(map(str, blank_page_nums))
        blank_note = (
            f"Page{'' if len(blank_page_nums) == 1 else 's'} {nums} "
            f"{'was' if len(blank_page_nums) == 1 else 'were'} blank and skipped."
        )
        logger.info("consult-pad recognition: skipped %d blank page(s) of %d (pages %s)",
                    len(blank_page_nums), len(page_images), nums)
    page_images = written_pages

    try:
        page_warnings = ""
        # Per-page transcription, cache-aware. An unchanged page is free; only
        # new/edited pages hit the model. One failing page never discards the
        # rest. `cache_out` keeps only the pages present now, so it can't grow
        # without bound across reloads.
        page_texts, failed_pages, cache_out, calls_made = [], [], {}, 0
        for idx, png in enumerate(page_images):
            h = _page_key(png)
            cached = cache_in.get(h)
            if cached is not None:
                page_texts.append("" if _looks_blank_transcription(cached) else cached)
                cache_out[h] = cached
                continue
            if calls_made and idx < len(page_images):
                time.sleep(4)  # space real requests so rate-limit retries stay rare
            try:
                txt = _transcribe_page(png)
                calls_made += 1
                cache_out[h] = txt
                page_texts.append("" if _looks_blank_transcription(txt) else txt)
            except Exception:
                logger.warning("consult-pad: page %d/%d transcription failed",
                               idx + 1, len(page_images), exc_info=True)
                failed_pages.append(idx + 1)
                page_texts.append("")

        full = "\n\n".join(t for t in page_texts if t).strip()
        if not full:
            if failed_pages:
                return {"status": "failed", "recognized": dict(_EMPTY, _page_texts=cache_out),
                        "error": "all pages unreadable"}
            return {"status": "empty", "recognized": dict(_EMPTY, _page_texts=cache_out), "error": ""}
        recognized = _structure_text(full, focus=focus)
        # We transcribed real text off the page ourselves. A text-only
        # structuring pass that then reports "not a clinical note" is overruled
        # — worst case the doctor gets the raw transcription to read, which
        # beats a false "pages look blank".
        if len(full) >= _MIN_MEANINGFUL_CHARS:
            recognized["is_clinical_note"] = True
        if failed_pages:
            page_warnings = (
                f"{len(failed_pages)} of {len(page_images)} page(s) could not be read "
                f"(page {', '.join(map(str, failed_pages))}) — load again or add them by hand."
            )

        recognized["_page_texts"] = cache_out
        recognized["page_warnings"] = " ".join(p for p in (blank_note, page_warnings) if p)
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
        try:
            keep = cache_out  # type: ignore[name-defined]
        except NameError:
            keep = {}
        return {"status": "failed", "recognized": dict(_EMPTY, _page_texts=keep), "error": str(exc)[:500]}


# brand + generic + doctor-shorthand aliases. Strengths / forms deliberately
# omitted — this table is for name resolution only.
SEED_DRUGS = [
    {"brand": "Dolo", "generic": "Paracetamol", "aliases": ["pcm", "para", "paracetamol", "acetaminophen", "calpol", "crocin", "dolo 650", "p 650", "pcm 650", "febrinil"]},
    {"brand": "Combiflam", "generic": "Ibuprofen + Paracetamol", "aliases": ["ibuprofen+paracetamol", "brufen+pcm", "flexon", "ibugesic plus"]},
    {"brand": "Brufen", "generic": "Ibuprofen", "aliases": ["ibuprofen", "ibugesic", "brufen 400"]},
    {"brand": "Naprosyn", "generic": "Naproxen", "aliases": ["naproxen", "naxdom", "naprosyn 500"]},
    {"brand": "Zerodol", "generic": "Aceclofenac", "aliases": ["aceclofenac", "hifenac", "acenac", "zerodol sp", "zerodol p"]},
    {"brand": "Zerodol-P", "generic": "Aceclofenac + Paracetamol", "aliases": ["aceclofenac+paracetamol", "hifenac p", "acenac p"]},
    {"brand": "Voveran", "generic": "Diclofenac", "aliases": ["diclofenac", "dynapar", "voveran sr", "diclo"]},
    {"brand": "Etova", "generic": "Etoricoxib", "aliases": ["etoricoxib", "nucoxia", "etoshine"]},
    {"brand": "Ultracet", "generic": "Tramadol + Paracetamol", "aliases": ["tramadol+paracetamol", "dolotram", "tramazac"]},
    {"brand": "Augmentin", "generic": "Amoxicillin + Clavulanic acid", "aliases": ["amoxicillin+clavulanic acid", "amox-clav", "clavam", "moxikind cv", "advent", "amoxyclav", "augmentin 625", "co-amoxiclav"]},
    {"brand": "Mox", "generic": "Amoxicillin", "aliases": ["amoxicillin", "amoxil", "novamox", "mox 500", "amox"]},
    {"brand": "Azithral", "generic": "Azithromycin", "aliases": ["azithromycin", "azee", "azithral 500", "azithro", "zithromax", "azicip", "athm"]},
    {"brand": "Taxim-O", "generic": "Cefixime", "aliases": ["cefixime", "zifi", "cefix", "mahacef", "taxim o 200", "omnix"]},
    {"brand": "Cefpodox", "generic": "Cefpodoxime", "aliases": ["cefpodoxime", "cepodem", "doxcef", "podocef"]},
    {"brand": "Ciplox", "generic": "Ciprofloxacin", "aliases": ["ciprofloxacin", "cifran", "ciprobid", "ciplox 500"]},
    {"brand": "Levoflox", "generic": "Levofloxacin", "aliases": ["levofloxacin", "levoflox 500", "glevo", "l-cin", "levaquin"]},
    {"brand": "Oflox", "generic": "Ofloxacin", "aliases": ["ofloxacin", "zanocin", "oflox 200"]},
    {"brand": "Norflox", "generic": "Norfloxacin", "aliases": ["norfloxacin", "norflox tz", "noroxin"]},
    {"brand": "Metrogyl", "generic": "Metronidazole", "aliases": ["metronidazole", "flagyl", "metrogyl 400", "metron"]},
    {"brand": "Ornof", "generic": "Ofloxacin + Ornidazole", "aliases": ["ofloxacin+ornidazole", "oflomac oz", "normet", "zenflox oz", "o2"]},
    {"brand": "Doxy", "generic": "Doxycycline", "aliases": ["doxycycline", "doxt", "dox", "minocin", "doxy 1"]},
    {"brand": "Cef", "generic": "Cephalexin", "aliases": ["cephalexin", "sporidex", "phexin", "cephalexin 500"]},
    {"brand": "Cefadur", "generic": "Cefuroxime", "aliases": ["cefuroxime", "ceftum", "zocef", "supacef"]},
    {"brand": "Monocef", "generic": "Ceftriaxone", "aliases": ["ceftriaxone", "oframax", "mahacef inj", "rocephin"]},
    {"brand": "Pan", "generic": "Pantoprazole", "aliases": ["pantoprazole", "pantop", "pan 40", "pantocid", "pantodac"]},
    {"brand": "Pan-D", "generic": "Pantoprazole + Domperidone", "aliases": ["pantoprazole+domperidone", "pantop d", "pantocid d", "pan d"]},
    {"brand": "Omez", "generic": "Omeprazole", "aliases": ["omeprazole", "ocid", "omez 20", "omecip", "prilosec"]},
    {"brand": "Nexpro", "generic": "Esomeprazole", "aliases": ["esomeprazole", "esoz", "nexium", "nexpro 40", "esofag"]},
    {"brand": "Rantac", "generic": "Ranitidine", "aliases": ["ranitidine", "zinetac", "aciloc", "rantac 150"]},
    {"brand": "Razo", "generic": "Rabeprazole", "aliases": ["rabeprazole", "rabekind", "veloz"]},
    {"brand": "Digene", "generic": "Antacid gel", "aliases": ["antacid", "gelusil", "mucaine gel", "magaldrate", "digene gel"]},
    {"brand": "Cyclopam", "generic": "Dicyclomine + Paracetamol", "aliases": ["dicyclomine+paracetamol", "cyclopam", "spasmonil", "scompaz"]},
    {"brand": "Buscopan", "generic": "Hyoscine butylbromide", "aliases": ["hyoscine", "buscopan", "hyoscine butylbromide", "spasmo"]},
    {"brand": "Meftal-Spas", "generic": "Mefenamic acid + Dicyclomine", "aliases": ["mefenamic+dicyclomine", "meftal spas", "spasmindon"]},
    {"brand": "Drotin", "generic": "Drotaverine", "aliases": ["drotaverine", "drotin ds", "doverin"]},
    {"brand": "Cetzine", "generic": "Cetirizine", "aliases": ["cetirizine", "cet", "cetrizine", "alerid", "okacet", "zyrtec", "cetzine 10"]},
    {"brand": "Levocet", "generic": "Levocetirizine", "aliases": ["levocetirizine", "xyzal", "1 al", "levocet", "teczine", "vozet"]},
    {"brand": "Allegra", "generic": "Fexofenadine", "aliases": ["fexofenadine", "allegra 120", "fexova", "histafree"]},
    {"brand": "Avil", "generic": "Pheniramine", "aliases": ["pheniramine", "avil 25", "avil"]},
    {"brand": "Montek-LC", "generic": "Montelukast + Levocetirizine", "aliases": ["montelukast+levocetirizine", "montair lc", "monti lc", "montek lc", "romilast l"]},
    {"brand": "Montair", "generic": "Montelukast", "aliases": ["montelukast", "montek", "montair 10", "romilast"]},
    {"brand": "Deriphyllin", "generic": "Etophylline + Theophylline", "aliases": ["etophylline+theophylline", "deriphyllin retard", "deriphyllin"]},
    {"brand": "Asthalin", "generic": "Salbutamol", "aliases": ["salbutamol", "albuterol", "asthalin", "ventorlin", "levolin", "asthalin inhaler"]},
    {"brand": "Foracort", "generic": "Formoterol + Budesonide", "aliases": ["formoterol+budesonide", "symbicort", "foracort 200", "budamate"]},
    {"brand": "Budecort", "generic": "Budesonide", "aliases": ["budesonide", "budecort", "pulmicort"]},
    {"brand": "Ascoril", "generic": "Bromhexine + Terbutaline + Guaifenesin", "aliases": ["ascoril ls", "ascoril d", "bromhexine", "chericof"]},
    {"brand": "Wikoryl", "generic": "Paracetamol + Phenylephrine + CPM", "aliases": ["cold tablet", "sinarest", "coldarin", "d cold", "okacold", "wikoryl", "cold tab"]},
    {"brand": "Otrivin", "generic": "Xylometazoline", "aliases": ["xylometazoline", "otrivin", "nasivion", "nasal drops"]},
    {"brand": "Ondem", "generic": "Ondansetron", "aliases": ["ondansetron", "emeset", "vomikind", "ondem md", "zofran"]},
    {"brand": "Domstal", "generic": "Domperidone", "aliases": ["domperidone", "domstal", "vomistop", "motilium"]},
    {"brand": "Perinorm", "generic": "Metoclopramide", "aliases": ["metoclopramide", "perinorm", "reglan", "maxeron"]},
    {"brand": "Glycomet", "generic": "Metformin", "aliases": ["metformin", "glycomet", "gluconorm", "metformin sr", "obimet", "carbophage"]},
    {"brand": "Amaryl", "generic": "Glimepiride", "aliases": ["glimepiride", "amaryl", "glimestar", "zoryl", "glimy"]},
    {"brand": "Amaryl-M", "generic": "Glimepiride + Metformin", "aliases": ["glimepiride+metformin", "amaryl m", "glycomet gp", "zoryl m", "glimy m"]},
    {"brand": "Januvia", "generic": "Sitagliptin", "aliases": ["sitagliptin", "istavel", "januvia", "sitatab"]},
    {"brand": "Jardiance", "generic": "Empagliflozin", "aliases": ["empagliflozin", "jardiance", "gibtulio"]},
    {"brand": "Amlong", "generic": "Amlodipine", "aliases": ["amlodipine", "amlopres", "amlodac", "stamlo", "amlong 5", "norvasc"]},
    {"brand": "Telma", "generic": "Telmisartan", "aliases": ["telmisartan", "telma 40", "telsartan", "telvas", "arbitel"]},
    {"brand": "Telma-H", "generic": "Telmisartan + Hydrochlorothiazide", "aliases": ["telmisartan+hctz", "telma h", "telsartan h"]},
    {"brand": "Losar", "generic": "Losartan", "aliases": ["losartan", "losar 50", "repace", "covance"]},
    {"brand": "Envas", "generic": "Enalapril", "aliases": ["enalapril", "envas", "enam", "nuril"]},
    {"brand": "Metolar", "generic": "Metoprolol", "aliases": ["metoprolol", "metolar xr", "met xl", "starpress", "betaloc"]},
    {"brand": "Concor", "generic": "Bisoprolol", "aliases": ["bisoprolol", "concor", "corbis"]},
    {"brand": "Dytor", "generic": "Torsemide", "aliases": ["torsemide", "dytor", "tide"]},
    {"brand": "Lasix", "generic": "Furosemide", "aliases": ["furosemide", "lasix", "frusemide", "frusenex"]},
    {"brand": "Nebicard", "generic": "Nebivolol", "aliases": ["nebivolol", "nebicard", "nodon", "nebilong"]},
    {"brand": "Ecosprin", "generic": "Aspirin", "aliases": ["aspirin", "ecosprin 75", "aspirin 75", "disprin", "loprin"]},
    {"brand": "Clopilet", "generic": "Clopidogrel", "aliases": ["clopidogrel", "clopilet a", "deplatt", "plavix", "clavix"]},
    {"brand": "Atorva", "generic": "Atorvastatin", "aliases": ["atorvastatin", "atorlip", "storvas", "lipitor", "atorva 20", "tonact"]},
    {"brand": "Rosuvas", "generic": "Rosuvastatin", "aliases": ["rosuvastatin", "rozavel", "crestor", "rosuvas 10", "novastat"]},
    {"brand": "Thyronorm", "generic": "Levothyroxine", "aliases": ["levothyroxine", "eltroxin", "thyrox", "thyronorm 50", "thyup"]},
    {"brand": "Shelcal", "generic": "Calcium + Vitamin D3", "aliases": ["calcium", "shelcal 500", "gemcal", "calcimax", "ccm", "calcium carbonate"]},
    {"brand": "Uprise-D3", "generic": "Cholecalciferol", "aliases": ["vitamin d3", "calcirol", "d rise", "uprise d3", "cholecalciferol", "d3 60k"]},
    {"brand": "Neurobion", "generic": "Vitamin B complex", "aliases": ["b complex", "neurobion forte", "becosules"]},
    {"brand": "Nurokind", "generic": "Mecobalamin", "aliases": ["mecobalamin", "methylcobalamin", "nurokind", "methycobal", "cobadex"]},
    {"brand": "Zincovit", "generic": "Multivitamin", "aliases": ["multivitamin", "zincovit", "supradyn", "a to z", "polybion"]},
    {"brand": "Limcee", "generic": "Vitamin C", "aliases": ["vitamin c", "limcee", "celin", "ascorbic acid", "celwin"]},
    {"brand": "Livogen", "generic": "Ferrous ascorbate + Folic acid", "aliases": ["iron", "livogen", "dexorange", "orofer xt", "autrin", "fefol", "ferrous ascorbate", "iron folic"]},
    {"brand": "Folvite", "generic": "Folic acid", "aliases": ["folic acid", "folvite", "folinext"]},
    {"brand": "Electral", "generic": "Oral rehydration salts", "aliases": ["ors", "electral", "walyte", "prolyte", "rehydration"]},
    {"brand": "Sporlac", "generic": "Lactobacillus probiotic", "aliases": ["probiotic", "sporlac ds", "vizylac", "prowel", "econorm", "bifilac"]},
    {"brand": "Cremaffin", "generic": "Liquid paraffin + Milk of magnesia", "aliases": ["laxative", "cremaffin plus", "cremadu"]},
    {"brand": "Duphalac", "generic": "Lactulose", "aliases": ["lactulose", "duphalac", "looz", "livoluk"]},
    {"brand": "Dulcolax", "generic": "Bisacodyl", "aliases": ["bisacodyl", "dulcolax", "laxopeg"]},
    {"brand": "Isabgol", "generic": "Psyllium husk", "aliases": ["isabgol", "fibofit", "naturolax", "sat isabgol", "psyllium"]},
    {"brand": "Wysolone", "generic": "Prednisolone", "aliases": ["prednisolone", "wysolone", "omnacortil", "predmet", "deltacortril"]},
    {"brand": "Medrol", "generic": "Methylprednisolone", "aliases": ["methylprednisolone", "medrol", "solu medrol"]},
    {"brand": "Defcort", "generic": "Deflazacort", "aliases": ["deflazacort", "defcort", "zenflam", "moraceff"]},
    {"brand": "Betnesol", "generic": "Betamethasone", "aliases": ["betamethasone", "betnesol", "walacort"]},
    {"brand": "Ivermectol", "generic": "Ivermectin", "aliases": ["ivermectin", "ivermectol", "iverjohn", "scabishield"]},
    {"brand": "Zentel", "generic": "Albendazole", "aliases": ["albendazole", "zentel", "bandy", "albezole", "almex"]},
    {"brand": "Fluconazole", "generic": "Fluconazole", "aliases": ["fluconazole", "forcan", "zocon", "flucos", "fcn 150"]},
    {"brand": "Itraconazole", "generic": "Itraconazole", "aliases": ["itraconazole", "itraspor", "canditral", "sporanox", "itaspor"]},
    {"brand": "Terbinafine", "generic": "Terbinafine", "aliases": ["terbinafine", "terbicip", "zimig", "lamisil", "sebifin"]},
    {"brand": "Candid", "generic": "Clotrimazole", "aliases": ["clotrimazole", "candid cream", "canesten", "surfaz"]},
    {"brand": "Acivir", "generic": "Acyclovir", "aliases": ["acyclovir", "acivir 400", "zovirax", "ocuvir"]},
    {"brand": "Tamiflu", "generic": "Oseltamivir", "aliases": ["oseltamivir", "tamiflu", "fluvir", "antiflu"]},
    {"brand": "Betadine", "generic": "Povidone iodine", "aliases": ["povidone iodine", "betadine", "wokadine", "cipladine"]},
    {"brand": "Soframycin", "generic": "Framycetin", "aliases": ["framycetin", "soframycin", "framypen"]},
    {"brand": "T-Bact", "generic": "Mupirocin", "aliases": ["mupirocin", "t-bact", "supirocin", "bactroban"]},
    {"brand": "Silverex", "generic": "Silver sulfadiazine", "aliases": ["silver sulfadiazine", "silverex", "burnol", "argispread"]},
    {"brand": "Volini", "generic": "Diclofenac topical", "aliases": ["pain gel", "volini", "moov", "diclofenac gel", "dynapar gel"]},
    {"brand": "Liv-52", "generic": "Herbal hepatoprotective", "aliases": ["liv 52", "liv52 ds"]},
    {"brand": "Udiliv", "generic": "Ursodeoxycholic acid", "aliases": ["ursodeoxycholic acid", "udiliv", "udihep", "ursocol"]},
    {"brand": "Gabapin", "generic": "Gabapentin", "aliases": ["gabapentin", "gabapin", "gabantin", "neurontin"]},
    {"brand": "Pregabalin", "generic": "Pregabalin", "aliases": ["pregabalin", "pregeb", "nervup", "lyrica", "pregabid"]},
    {"brand": "Amitone", "generic": "Amitriptyline", "aliases": ["amitriptyline", "amitone", "tryptomer", "eliwel"]},
    {"brand": "Nexito", "generic": "Escitalopram", "aliases": ["escitalopram", "nexito", "cipralex", "szetalo", "feliz s"]},
    {"brand": "Levipil", "generic": "Levetiracetam", "aliases": ["levetiracetam", "levipil", "keppra", "torleva"]},
    {"brand": "Tegrital", "generic": "Carbamazepine", "aliases": ["carbamazepine", "tegrital", "zeptol", "mazetol"]},
]
# Common handwriting / OCR misreads of frequent OPD drugs -> the standard
# generic. These give the consult-pad recogniser an EXACT hit (no fuzzy
# threshold to clear) for the mistakes that actually recur on the pad.
# surface is lower-case; value must match a `generic` in SEED_DRUGS above.
MISREADS = {
    "panacetamol": "Paracetamol", "paracetmol": "Paracetamol",
    "paracetamal": "Paracetamol", "paracetemol": "Paracetamol",
    "paracitamol": "Paracetamol", "parcetamol": "Paracetamol",
    "pcm": "Paracetamol",
    "azithromicin": "Azithromycin", "azithromyacin": "Azithromycin",
    "azithromycine": "Azithromycin", "azithral": "Azithromycin",
    "amoxycillin": "Amoxicillin", "amoxicilin": "Amoxicillin",
    "amoxycillin trihydrate": "Amoxicillin",
    "pantoprazol": "Pantoprazole", "pantaprazole": "Pantoprazole",
    "pantoprozole": "Pantoprazole",
    "omeprazol": "Omeprazole", "omeprazol e": "Omeprazole",
    "rabeprazol": "Rabeprazole",
    "cetrizine": "Cetirizine", "cetirizin": "Cetirizine",
    "levocetrizine": "Levocetirizine", "levocitirizine": "Levocetirizine",
    "montelukas": "Montelukast", "montelukaste": "Montelukast",
    "metronidazol": "Metronidazole", "metronidazole 400": "Metronidazole",
    "ciprofloxacin hcl": "Ciprofloxacin", "ciprofloxacine": "Ciprofloxacin",
    "levofloxacine": "Levofloxacin", "ofloxacine": "Ofloxacin",
    "diclofenac sodium": "Diclofenac", "diclophenac": "Diclofenac",
    "aceclofinac": "Aceclofenac", "aceclofenak": "Aceclofenac",
    "ibuprufen": "Ibuprofen", "ibuprofin": "Ibuprofen",
    "metformin hcl": "Metformin", "metformine": "Metformin",
    "amlodipin": "Amlodipine", "amlodypine": "Amlodipine",
    "telmisartan h": "Telmisartan", "telmisarton": "Telmisartan",
    "atorvastatin calcium": "Atorvastatin", "atorvastatine": "Atorvastatin",
    "rosuvastatine": "Rosuvastatin",
    "azithromycin 500": "Azithromycin", "cefixime 200": "Cefixime",
    "cefixim": "Cefixime", "cefpodoxim": "Cefpodoxime",
    "domperidon": "Domperidone", "ondansetrone": "Ondansetron",
    "prednisolon": "Prednisolone", "methylprednisolon": "Methylprednisolone",
}
def alias_pairs():
    """
    Yield (surface_lower, generic_lower) for every brand and alias in the
    seed table. `surface` is the abbreviated/branded string a doctor might
    write; `generic` is what it maps to.
    """
    for d in SEED_DRUGS:
        gen = (d.get("generic") or "").strip().lower()
        if not gen:
            continue
        brand = (d.get("brand") or "").strip().lower()
        if brand:
            yield brand, gen
        for a in d.get("aliases") or []:
            a = (a or "").strip().lower()
            if a:
                yield a, gen
def seed_name_pairs():
    """
    Yield (surface_lower, canonical) where `canonical` is the standard,
    properly-cased generic name — for use as a STANDALONE drug-name resolver
    when the hospital has no (or a sparse) Drug catalog. Covers every generic,
    brand and alias in SEED_DRUGS plus the MISREADS table. The generic also
    maps to itself so an already-standard string snaps to the right casing.
    """
    for d in SEED_DRUGS:
        gen = (d.get("generic") or "").strip()
        if not gen:
            continue
        yield gen.lower(), gen
        brand = (d.get("brand") or "").strip().lower()
        if brand:
            yield brand, gen
        for a in d.get("aliases") or []:
            a = (a or "").strip().lower()
            if a:
                yield a, gen
    for surface, canon in MISREADS.items():
        yield surface, canon


# canonical standard name + the shorthand a doctor might scrawl.
SEED_TESTS = [
    # ── Haematology ──────────────────────────────────────────────────────────
    {"canonical": "Complete Blood Count", "aliases": ["cbc", "cp", "complete blood picture", "hemogram", "haemogram", "cbc with esr", "full blood count", "fbc", "blood count"]},
    {"canonical": "Haemoglobin", "aliases": ["hb", "hgb", "haemoglobin", "hemoglobin"]},
    {"canonical": "Total Leucocyte Count", "aliases": ["tlc", "tc", "wbc count", "total count", "leucocyte count"]},
    {"canonical": "Differential Leucocyte Count", "aliases": ["dlc", "dc", "differential count"]},
    {"canonical": "Platelet Count", "aliases": ["platelet", "plt", "platelets", "platelet count"]},
    {"canonical": "Peripheral Smear", "aliases": ["ps", "psmear", "peripheral blood smear", "pbs", "smear"]},
    {"canonical": "Erythrocyte Sedimentation Rate", "aliases": ["esr", "sed rate"]},
    {"canonical": "Reticulocyte Count", "aliases": ["retic", "retic count", "reticulocyte"]},
    {"canonical": "Prothrombin Time / INR", "aliases": ["pt", "pt inr", "pt/inr", "inr", "prothrombin time"]},
    {"canonical": "Activated Partial Thromboplastin Time", "aliases": ["aptt", "ptt"]},
    {"canonical": "D-Dimer", "aliases": ["d dimer", "ddimer", "d-dimer"]},
    {"canonical": "Blood Group & Rh Typing", "aliases": ["blood group", "bl grp", "abo rh", "grouping", "blood grouping", "abo typing"]},

    # ── Diabetes / glycaemic ────────────────────────────────────────────────
    {"canonical": "Fasting Blood Sugar", "aliases": ["fbs", "fbg", "fasting sugar", "fasting glucose", "gf"]},
    {"canonical": "Post Prandial Blood Sugar", "aliases": ["ppbs", "pp sugar", "post prandial sugar", "pp glucose", "gpp", "2hr ppbs"]},
    {"canonical": "Random Blood Sugar", "aliases": ["rbs", "random sugar", "random glucose", "grbs", "cbg"]},
    {"canonical": "HbA1c (Glycated Haemoglobin)", "aliases": ["hba1c", "hb a1c", "a1c", "glycated hb", "glycosylated hb"]},
    {"canonical": "Oral Glucose Tolerance Test", "aliases": ["ogtt", "gtt", "glucose tolerance test"]},
    {"canonical": "Fasting Insulin", "aliases": ["fasting insulin", "s insulin", "serum insulin"]},

    # ── Renal / electrolytes ────────────────────────────────────────────────
    {"canonical": "Renal Function Test", "aliases": ["rft", "kft", "renal function", "kidney function test", "kidney function"]},
    {"canonical": "Blood Urea", "aliases": ["urea", "blood urea", "b urea"]},
    {"canonical": "Blood Urea Nitrogen", "aliases": ["bun"]},
    {"canonical": "Serum Creatinine", "aliases": ["creatinine", "s creatinine", "s.creat", "creat", "sr creatinine"]},
    {"canonical": "Serum Uric Acid", "aliases": ["uric acid", "s uric acid", "sua"]},
    {"canonical": "Serum Electrolytes", "aliases": ["electrolytes", "s electrolytes", "serum electrolyte", "na k cl", "na/k", "na k", "rft with electrolytes"]},
    {"canonical": "Serum Sodium", "aliases": ["sodium", "s sodium", "na+", "s na"]},
    {"canonical": "Serum Potassium", "aliases": ["potassium", "s potassium", "k+", "s k"]},
    {"canonical": "Serum Calcium", "aliases": ["calcium", "s calcium", "s ca", "ca++"]},
    {"canonical": "Serum Phosphorus", "aliases": ["phosphorus", "phosphate", "s phosphorus", "po4"]},
    {"canonical": "Serum Magnesium", "aliases": ["magnesium", "s magnesium", "s mg", "mg++"]},

    # ── Liver ───────────────────────────────────────────────────────────────
    {"canonical": "Liver Function Test", "aliases": ["lft", "liver function", "liver panel", "lfts"]},
    {"canonical": "Serum Bilirubin (Total & Direct)", "aliases": ["bilirubin", "s bilirubin", "t bili", "total bilirubin", "sbr"]},
    {"canonical": "SGPT (ALT)", "aliases": ["sgpt", "alt", "alat"]},
    {"canonical": "SGOT (AST)", "aliases": ["sgot", "ast", "asat"]},
    {"canonical": "Alkaline Phosphatase", "aliases": ["alp", "alk phos", "s alp"]},
    {"canonical": "Gamma GT", "aliases": ["ggt", "gamma gt", "g gt", "ggtp"]},
    {"canonical": "Serum Total Protein & Albumin", "aliases": ["total protein", "protein albumin", "tp alb", "s protein", "a/g ratio", "albumin globulin"]},
    {"canonical": "Serum Albumin", "aliases": ["albumin", "s albumin", "s alb"]},
    {"canonical": "Serum Amylase", "aliases": ["amylase", "s amylase"]},
    {"canonical": "Serum Lipase", "aliases": ["lipase", "s lipase"]},

    # ── Lipids ──────────────────────────────────────────────────────────────
    {"canonical": "Lipid Profile", "aliases": ["lipid profile", "lipids", "lp", "fasting lipid profile", "flp", "lipid panel"]},
    {"canonical": "Total Cholesterol", "aliases": ["cholesterol", "t chol", "total cholesterol", "s cholesterol"]},
    {"canonical": "Serum Triglycerides", "aliases": ["triglycerides", "tg", "tgl", "s triglycerides"]},
    {"canonical": "HDL Cholesterol", "aliases": ["hdl", "hdl cholesterol"]},
    {"canonical": "LDL Cholesterol", "aliases": ["ldl", "ldl cholesterol"]},

    # ── Thyroid / endocrine ────────────────────────────────────────────────
    {"canonical": "Thyroid Profile (T3 T4 TSH)", "aliases": ["thyroid profile", "tft", "t3 t4 tsh", "thyroid function test", "thyroid panel"]},
    {"canonical": "TSH", "aliases": ["tsh", "s tsh", "thyroid stimulating hormone"]},
    {"canonical": "Free T3", "aliases": ["ft3", "free t3"]},
    {"canonical": "Free T4", "aliases": ["ft4", "free t4"]},
    {"canonical": "Serum Cortisol", "aliases": ["cortisol", "s cortisol", "am cortisol"]},
    {"canonical": "Serum Prolactin", "aliases": ["prolactin", "prl", "s prolactin"]},
    {"canonical": "Vitamin D (25-OH)", "aliases": ["vitamin d", "vit d", "25 oh vit d", "vitamin d3 level", "25-hydroxy vitamin d", "vit d level"]},
    {"canonical": "Vitamin B12", "aliases": ["vitamin b12", "vit b12", "b12", "cobalamin level", "s b12"]},
    {"canonical": "Serum Ferritin", "aliases": ["ferritin", "s ferritin"]},
    {"canonical": "Iron Studies", "aliases": ["iron studies", "iron profile", "serum iron", "tibc", "iron tibc"]},
    {"canonical": "Serum Folate", "aliases": ["folate", "folic acid level", "s folate", "rbc folate"]},

    # ── Cardiac ─────────────────────────────────────────────────────────────
    {"canonical": "Troponin I", "aliases": ["trop", "trop i", "troponin", "trop-i", "hs trop"]},
    {"canonical": "Troponin T", "aliases": ["trop t", "troponin t"]},
    {"canonical": "CPK-MB", "aliases": ["cpk mb", "ck mb", "ckmb", "cpk-mb"]},
    {"canonical": "CPK Total", "aliases": ["cpk", "ck total", "cpk total", "creatine kinase"]},
    {"canonical": "NT-proBNP", "aliases": ["bnp", "nt probnp", "pro bnp", "nt-pro bnp"]},

    # ── Inflammatory / infectious markers ──────────────────────────────────
    {"canonical": "C-Reactive Protein", "aliases": ["crp", "c reactive protein", "hs crp", "quantitative crp"]},
    {"canonical": "Procalcitonin", "aliases": ["pct", "procalcitonin"]},
    {"canonical": "Widal Test", "aliases": ["widal", "widal test", "typhoid widal"]},
    {"canonical": "Dengue NS1 Antigen", "aliases": ["ns1", "dengue ns1", "ns1 antigen", "dengue antigen"]},
    {"canonical": "Dengue Serology (IgG / IgM)", "aliases": ["dengue serology", "dengue igg igm", "dengue igm", "dengue elisa"]},
    {"canonical": "Malaria Parasite / Antigen", "aliases": ["mp", "malaria parasite", "mp smear", "malaria antigen", "qbc malaria", "mpqbc"]},
    {"canonical": "Peripheral Smear for Malarial Parasite", "aliases": ["psmp", "ps for mp", "smear for mp"]},
    {"canonical": "Scrub Typhus IgM", "aliases": ["scrub typhus", "scrub igm", "scrub typhus serology"]},
    {"canonical": "Leptospira IgM", "aliases": ["lepto", "leptospira", "lepto igm"]},
    {"canonical": "Blood Culture & Sensitivity", "aliases": ["blood culture", "bl c/s", "blood c/s", "bactec"]},
    {"canonical": "Urine Culture & Sensitivity", "aliases": ["urine culture", "urine c/s", "ur c/s"]},
    {"canonical": "COVID-19 RT-PCR", "aliases": ["covid rtpcr", "covid pcr", "rtpcr covid", "sars cov 2 pcr"]},
    {"canonical": "COVID-19 Rapid Antigen", "aliases": ["covid rat", "rapid antigen covid", "covid antigen"]},

    # ── Viral serology ─────────────────────────────────────────────────────
    {"canonical": "HBsAg", "aliases": ["hbsag", "hbs ag", "hepatitis b surface antigen", "australia antigen"]},
    {"canonical": "Anti-HCV", "aliases": ["hcv", "anti hcv", "hcv antibody", "hepatitis c antibody"]},
    {"canonical": "HIV I & II (ELISA)", "aliases": ["hiv", "hiv 1 2", "hiv elisa", "hiv i ii", "retroviral screen"]},
    {"canonical": "Viral Marker Screen (HBsAg, HCV, HIV)", "aliases": ["viral markers", "viral marker", "vm screen", "hbsag hcv hiv", "hiv hbsag hcv"]},

    # ── Urine / stool ─────────────────────────────────────────────────────
    {"canonical": "Urine Routine & Microscopy", "aliases": ["urine r/m", "urine re", "urine routine", "ur r/m", "urine r/e", "cue", "complete urine examination", "urine analysis", "urinalysis"]},
    {"canonical": "Urine Pregnancy Test", "aliases": ["upt", "urine pregnancy", "pregnancy test"]},
    {"canonical": "Urine Microalbumin", "aliases": ["microalbumin", "urine microalbumin", "spot microalbumin", "acr", "albumin creatinine ratio"]},
    {"canonical": "24-hour Urine Protein", "aliases": ["24 hr urine protein", "24 hour protein", "24h urine protein"]},
    {"canonical": "Stool Routine & Microscopy", "aliases": ["stool r/m", "stool re", "stool routine", "stool r/e", "stool examination"]},
    {"canonical": "Stool Occult Blood", "aliases": ["stool occult blood", "occult blood", "fobt", "stool for ob"]},

    # ── Imaging / cardiology procedures ───────────────────────────────────
    {"canonical": "Chest X-Ray PA View", "aliases": ["cxr", "chest x ray", "x ray chest", "chest xray", "cxr pa", "x-ray chest pa"]},
    {"canonical": "X-Ray", "aliases": ["x ray", "xray", "x-ray", "plain radiograph"]},
    {"canonical": "Ultrasound Abdomen & Pelvis", "aliases": ["usg abdomen", "usg abd pelvis", "usg w/a", "usg whole abdomen", "us abdomen", "sonography abdomen", "usg kub"]},
    {"canonical": "Ultrasound", "aliases": ["usg", "ultrasound", "sonography", "us scan"]},
    {"canonical": "Electrocardiogram", "aliases": ["ecg", "ekg", "12 lead ecg"]},
    {"canonical": "2D Echocardiography", "aliases": ["2d echo", "echo", "echocardiography", "2decho", "2d-echo"]},
    {"canonical": "Treadmill Test", "aliases": ["tmt", "treadmill test", "stress test", "ett"]},
    {"canonical": "CT Scan", "aliases": ["ct", "ct scan", "cect", "ncct"]},
    {"canonical": "MRI", "aliases": ["mri", "mr scan", "mri scan"]},
    {"canonical": "Mammography", "aliases": ["mammography", "mammogram"]},
    {"canonical": "Bone Mineral Density (DEXA)", "aliases": ["bmd", "dexa", "dexa scan", "bone density"]},

    # ── Misc common ──────────────────────────────────────────────────────
    {"canonical": "Serum Vitamin B-complex Panel", "aliases": ["b complex panel", "vitamin b panel"]},
    {"canonical": "Rheumatoid Factor", "aliases": ["ra factor", "rf", "rheumatoid factor", "ra test"]},
    {"canonical": "Anti-CCP", "aliases": ["anti ccp", "ccp", "acpa"]},
    {"canonical": "ANA (Antinuclear Antibody)", "aliases": ["ana", "antinuclear antibody", "ana by if"]},
    {"canonical": "Anti-Streptolysin O", "aliases": ["aso", "aslo", "aso titre"]},
    {"canonical": "Serum PSA", "aliases": ["psa", "prostate specific antigen", "s psa", "total psa"]},
    {"canonical": "Serum Beta-hCG", "aliases": ["beta hcg", "b hcg", "bhcg", "serum hcg", "quantitative hcg"]},
    {"canonical": "Sputum for AFB", "aliases": ["sputum afb", "afb", "sputum for afb", "zn stain sputum", "afb smear"]},
    {"canonical": "Sputum CBNAAT / GeneXpert", "aliases": ["cbnaat", "genexpert", "sputum genexpert", "gene xpert", "tb pcr"]},
    {"canonical": "Mantoux Test", "aliases": ["mantoux", "tst", "ppd", "tuberculin test"]},
    {"canonical": "Arterial Blood Gas", "aliases": ["abg", "blood gas", "arterial blood gas analysis"]},
    {"canonical": "Serum Procalcitonin", "aliases": ["s pct"]},
    {"canonical": "G6PD", "aliases": ["g6pd", "g 6 pd", "glucose 6 phosphate dehydrogenase"]},
    {"canonical": "Serum LDH", "aliases": ["ldh", "s ldh", "lactate dehydrogenase"]},
]
def consult_pad_lab_aliases_alias_pairs():
    """
    Yield (surface_lower, canonical) for every canonical name and alias in the
    seed table. `surface` is the lower-cased string a doctor might scrawl;
    `canonical` is the standard, properly-cased test name it maps to. The
    canonical name also yields a pair against its own lower-case form so an
    already-standard string snaps to the canonical casing.
    """
    for t in SEED_TESTS:
        canon = (t.get("canonical") or "").strip()
        if not canon:
            continue
        yield canon.lower(), canon
        for a in t.get("aliases") or []:
            a = (a or "").strip().lower()
            if a:
                yield a, canon


from datetime import timedelta

from django.contrib.auth.hashers import check_password as _check_password, make_password
from django.utils import timezone

from apps.patients.models import RecordsPrivacy


def mobile_hash_of(raw):
    from core.utils.hashing import hash_mobile, normalize_mobile
    return hash_mobile(normalize_mobile(raw))


def set_password(patient, raw):
    patient.password = make_password(raw)


def check_password(patient, raw):
    return _check_password(raw, patient.password)


def accounts():
    return Patient.objects.using("default").exclude(password="")


def accounts_with_mobile(raw):
    try:
        return accounts().filter(mobile_hash=mobile_hash_of(raw))
    except ValueError:
        return Patient.objects.none()


def create_account(**fields):
    if "mobile" in fields:
        fields["mobile_hash"] = mobile_hash_of(fields.pop("mobile"))
    identity, _ = Patient._base_manager.using("default").get_or_create(
        awpid=fields["awpid"], defaults={"full_name": fields.get("full_name") or "Patient"})
    for name, value in fields.items():
        setattr(identity, name, value)
    identity.save(using="default")
    return accounts().get(pk=identity.pk)


def awpid_of(row):
    return row.patient.awpid if row.patient_id else ""


def privacy_for_awpid(awpid):
    obj, _ = RecordsPrivacy.objects.using("default").get_or_create(patient=Patient.objects.using("default").get(awpid=awpid))
    return obj


def pending_stale(grant):
    return grant.status == grant.STATUS_PENDING and timezone.now() - grant.created_at > timedelta(minutes=grant.PENDING_TTL_MINUTES)


def device_matches(grant, raw_token):
    if not grant.device_hash:
        return True
    if not raw_token:
        return False
    return hashlib.sha256(raw_token.encode()).hexdigest() == grant.device_hash


def is_live(grant):
    return grant.status == grant.STATUS_APPROVED and grant.expires_at is not None and timezone.now() < grant.expires_at


def lapse_if_due(grant):
    if grant.status == grant.STATUS_APPROVED and grant.expires_at is not None and timezone.now() >= grant.expires_at:
        grant.status = grant.STATUS_EXPIRED
        grant.save(using="default", update_fields=["status"])
        return True
    return False


def seconds_left(grant):
    if not grant.expires_at:
        return 0
    return max(0, int((grant.expires_at - timezone.now()).total_seconds()))
