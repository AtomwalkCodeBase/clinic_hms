"""
apps/patients/consult_pad_views.py
-----------------------------------
The public phone side of the consultation handwriting pad.

A doctor opens a ConsultSession from an encounter (apps/opd/views.py
::EncounterConsultSessionView), shows the patient's permanent QR, and the
phone talks to this endpoint. Two tabs — Prescription and Internal Note —
each a multi-page canvas; every autosave lands here and kicks off vision-LLM
recognition for that tab. Nothing is "submitted": the session stays live
until the doctor signs the encounter on the web.

Deliberately unauthenticated (reached by scanning a QR, no login) — the same
exception apps/patients/emergency_views.py is, gated by a 43-char random
token and a per-IP throttle.
"""

import base64
import logging
import re
import threading
import time
from datetime import date, timedelta

from django.db import connections
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle

from core.response import success, error
from core.file_validation import validate_data_uri, FileValidationError
from apps.registry.models import PatientIdentity, ConsultSession

logger = logging.getLogger(__name__)

# Total base64 budget for one tab's page images. Finger strokes on white
# compress tiny; this comfortably fits ~15 pages and just rejects an
# abusive/malformed PUT before we decode it.
_MAX_TAB_BASE64_CHARS = 9_000_000
_TABS = {"rx", "note"}

# A burst of autosaves (the phone saves every few strokes) each spawn a
# recognition thread. Each thread waits this long, then bails if a newer
# autosave has superseded it — so only the last save in a burst hits the
# vision API.
_RECOG_DEBOUNCE_SECONDS = 2.5


def _age_years(dob):
    if not dob:
        return None
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


# Drug-name normalisation. The recognition model is told it MAY fix an
# obvious misspelling of a real drug; this pass then grounds that against the
# hospital's OWN drug catalog (prescriptions.Drug) — the authoritative
# spelling for that clinic. It only ever rewrites the drug NAME; dose,
# frequency, route and duration are never touched, and the doctor still
# reviews every row before signing. `drug_name_raw` keeps what was read so
# the encounter screen can show "read X -> matched Y".
_DRUG_MATCH_MIN = 85     # rapidfuzz WRatio; below this we leave the name alone
_DRUG_MATCH_GAP = 6      # winner must beat the next DIFFERENT drug by at least this
_DRUG_MATCH_STRONG = 90  # a hit this good is accepted even without the gap
_DRUG_MIN_LEN = 5        # don't fuzzy-match short tokens / abbreviations (e.g. "pcm")
_RX_FORM_WORDS = {
    "tab", "tabs", "tablet", "tablets", "cap", "caps", "capsule", "capsules",
    "syp", "syr", "syrup", "susp", "suspension", "inj", "injection", "amp",
    "ampoule", "oint", "ointment", "cream", "gel", "lotion", "drop", "drops",
    "gtt", "soln", "solution", "spray", "inh", "inhaler", "sachet", "powder",
}


def _strip_form_word(name: str) -> str:
    words = (name or "").strip().split()
    while words and words[0].strip(".").lower() in _RX_FORM_WORDS:
        words = words[1:]
    return " ".join(words)


def _candidate_map(rows, alias_pairs_iter=None):
    """
    Build {probe_lower: canonical Drug.name} from catalog rows, plus
    doctor-shorthand aliases whose generic/brand is already present in the
    catalog. Pure (no DB / no network) so it can be unit-tested directly.

    `rows`: iterable of dicts with "name" and "generic_name".
    `alias_pairs_iter`: iterable of (surface_lower, generic_lower) — an alias
    only takes effect when its generic resolves to a real catalog entry.
    """
    candidates = {}
    generics = {}  # generic_lower -> canonical name (first wins)
    for r in rows:
        canon = (r.get("name") or "").strip()
        if not canon:
            continue
        candidates.setdefault(canon.lower(), canon)
        gen = (r.get("generic_name") or "").strip().lower()
        if gen:
            candidates.setdefault(gen, canon)
            generics.setdefault(gen, canon)

    if alias_pairs_iter:
        cat_generics = list(generics.items())
        for surface, seed_gen in alias_pairs_iter:
            if not surface or surface in candidates:
                continue
            canon = generics.get(seed_gen)
            if not canon:
                # tolerate strength suffixes on the catalog generic, e.g. seed
                # "amoxicillin" vs catalog generic "amoxicillin 500 mg"
                for cg, cn in cat_generics:
                    if seed_gen in cg.split() or cg.startswith(seed_gen + " "):
                        canon = cn
                        break
            if canon:
                candidates[surface] = canon
    return candidates


def _resolve_item_name(it, candidates, keys, process, fuzz):
    """Canonicalise one recognised Rx item's drug_name against `candidates`.
    Mutates `it` in place; never changes dose/frequency/route/duration."""
    raw = (it.get("drug_name") or "").strip()
    it["drug_name_raw"] = raw
    it["name_source"] = "verbatim"
    it.setdefault("flags", [])
    probe = _strip_form_word(raw).lower()
    if not probe:
        return

    # Exact catalog hit (canonical name, generic, or a known alias) — safe.
    if len(probe) >= 3 and probe in candidates:
        canon = candidates[probe]
        if canon != raw:
            it["drug_name"] = canon
        it["name_source"] = "catalog"
        return

    # Fuzzy: only for tokens long enough to be meaningful. Accept when the top
    # hit is either near-exact (>= _DRUG_MATCH_STRONG) or clearly ahead of the
    # next DIFFERENT drug (>= _DRUG_MATCH_GAP). Runner-ups that resolve to the
    # same canonical (e.g. "Paracetamol" vs "Paracetamol Syrup" sharing the
    # generic, or a brand alias) don't count as competition. Weaker matches
    # are left verbatim and flagged for the doctor.
    if len(probe) < _DRUG_MIN_LEN:
        it["flags"].append("not found in catalog — check the name")
        return
    hits = process.extract(probe, keys, scorer=fuzz.WRatio, limit=8)
    if not hits or hits[0][1] < _DRUG_MATCH_MIN:
        it["flags"].append("not found in catalog — check the name")
        return
    s1 = hits[0][1]
    win_canon = candidates[hits[0][0]]
    rival = next((sc for (k, sc, *_ ) in hits[1:] if candidates.get(k) != win_canon), 0)
    if s1 >= _DRUG_MATCH_STRONG or (s1 - rival) >= _DRUG_MATCH_GAP:
        if win_canon.lower() != raw.lower():
            it["drug_name"] = win_canon
        it["name_source"] = "catalog_fuzzy"
        it["flags"].append(f'best-guess match for "{raw}" — confirm')
    else:
        it["flags"].append("not found in catalog — check the name")


def _drug_candidate_map(catalog_rows, seed_iter):
    """Build {probe_lower: canonical drug name}. `seed_iter` is
    (surface_lower, canonical) from consult_pad_drug_aliases.seed_name_pairs()
    — the standalone base, so drug names still resolve when the tenant has no
    Drug catalog. `catalog_rows` (dicts with "name"/"generic_name") are layered
    on top and win for spelling — a clinic that stocks "Dolo 650" gets that
    exact string. Pure (no DB / no network)."""
    candidates = {}
    for surface, canon in seed_iter or []:
        surface = (surface or "").strip().lower()
        canon = (canon or "").strip()
        if surface and canon:
            candidates.setdefault(surface, canon)
    for r in catalog_rows or []:
        canon = (r.get("name") or "").strip()
        if not canon:
            continue
        candidates[canon.lower()] = canon            # catalog overrides the seed
        gen = (r.get("generic_name") or "").strip().lower()
        if gen:
            candidates.setdefault(gen, canon)
    return candidates


def _normalise_rx_against_catalog(recognized: dict, tenant_id):
    """Mutate recognized['prescription'] in place: canonicalise each drug_name
    against a standard drug-name table (consult_pad_drug_aliases), enriched
    with the tenant's own Drug catalog when it has one. Best-effort — any
    failure leaves the names exactly as recognised."""
    items = recognized.get("prescription") or []
    if not items:
        return

    # Make sure every item carries these keys even if we bail out early below
    # (rapidfuzz missing) so the encounter page's review panel renders
    # consistently.
    for it in items:
        it.setdefault("drug_name_raw", (it.get("drug_name") or "").strip())
        it.setdefault("name_source", "verbatim")
        it.setdefault("flags", [])

    try:
        from rapidfuzz import process, fuzz
    except Exception:
        return

    # Tenant Drug catalog — nice-to-have, not required. Any failure (no
    # tenant, DB down, empty catalog) just leaves catalog_rows empty and the
    # seed table does the work.
    catalog_rows = []
    if tenant_id:
        try:
            from apps.tenants.models import Tenant
            tenant = Tenant.objects.using("default").filter(pk=tenant_id).first()
            if tenant:
                from apps.prescriptions.models import Drug
                catalog_rows = list(Drug.objects.using(tenant.db_name)
                                    .filter(is_active=True).values("name", "generic_name"))
        except Exception:
            logger.debug("consult-pad: drug catalog unavailable for tenant %s — seed table only", tenant_id)

    try:
        from apps.patients.consult_pad_drug_aliases import seed_name_pairs
        seed_iter = list(seed_name_pairs())
    except Exception:
        seed_iter = []

    candidates = _drug_candidate_map(catalog_rows, seed_iter)
    keys = list(candidates)
    for it in items:
        _resolve_item_name(it, candidates, keys, process, fuzz)


# ── Investigation-name normalisation ────────────────────────────────────────
# Same idea as the drug pass above, for the recognised `investigations` string
# on the Internal Note tab: turn "CBC, LFT, USG abd" into standard test names
# the front desk and lab will recognise. Deterministic and reversible — the
# raw string each token came from is kept, every rewrite is shown to the
# doctor on the review panel, and `raw_text` is never touched.
#
# Unlike drugs, this does NOT require a tenant catalog: the seed alias table
# (apps/patients/consult_pad_lab_aliases.py) stands on its own because most
# clinics don't maintain a lab_test catalog and a test name carries no dosing
# risk. Where the tenant DOES have one, its names are layered on top and win
# for spelling.
_LAB_MATCH_MIN = 88   # rapidfuzz WRatio; below this the token is left as written
_LAB_MATCH_GAP = 6    # winner must beat the runner-up by at least this much
_LAB_MIN_LEN = 4      # don't fuzzy-match shorter tokens — 3-letter acronyms
                      # (cbc/lft/esr/…) must come through the exact alias path
# Split on comma / semicolon / newline (tight), and on slash, ampersand, plus
# or the word "and" ONLY when surrounded by whitespace — so "Urine R/M",
# "RFT/electrolytes" written solid, "Na+ K+" and "c/s" survive as one token.
_LAB_SPLIT_RE = re.compile(r"\s*[,;\n]\s*|\s+/\s+|\s+&\s+|\s+\+\s+|\s+and\s+", re.I)
_LAB_LIST_PREFIX_RE = re.compile(r"^\s*(?:\d+\s*[.)\-]|[-*•·])\s*")


def _split_investigations(text: str) -> list:
    """A recognised `investigations` string -> ordered, de-duplicated list of
    individual test tokens. Pure; safe on '' (returns [])."""
    if not text or not text.strip():
        return []
    out, seen = [], set()
    for chunk in _LAB_SPLIT_RE.split(text):
        tok = _LAB_LIST_PREFIX_RE.sub("", (chunk or "").strip()).strip(" .:-")
        if not tok:
            continue
        key = tok.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(tok)
    return out


def _lab_candidate_map(catalog_names, alias_pairs_iter):
    """Build {probe_lower: canonical test name}. `catalog_names` is an iterable
    of the tenant's LabTest.name strings (may be empty); `alias_pairs_iter` is
    (surface_lower, canonical) from the seed table. Catalog names are added
    last so a clinic's own spelling wins. Pure (no DB / no network)."""
    candidates = {}
    for surface, canon in alias_pairs_iter or []:
        surface = (surface or "").strip().lower()
        canon = (canon or "").strip()
        if surface and canon:
            candidates.setdefault(surface, canon)
    for name in catalog_names or []:
        canon = (name or "").strip()
        if canon:
            candidates[canon.lower()] = canon   # catalog overrides the seed
    return candidates


def _resolve_investigation(raw, candidates, keys, process, fuzz):
    """Canonicalise one investigation token. Returns
    {raw, name, source: verbatim|catalog|catalog_fuzzy, flags:[...]}."""
    raw = (raw or "").strip()
    probe = raw.lower()
    res = {"raw": raw, "name": raw, "source": "verbatim", "flags": []}
    if not probe:
        return res

    if probe in candidates:
        res["name"] = candidates[probe]
        res["source"] = "catalog"
        return res

    if len(probe) < _LAB_MIN_LEN or not keys:
        res["flags"].append("not a recognised investigation — check")
        return res

    hits = process.extract(probe, keys, scorer=fuzz.WRatio, limit=2)
    s1 = hits[0][1] if hits else 0
    s2 = hits[1][1] if len(hits) > 1 else 0
    if hits and s1 >= _LAB_MATCH_MIN and (s1 - s2) >= _LAB_MATCH_GAP:
        res["name"] = candidates[hits[0][0]]
        res["source"] = "catalog_fuzzy"
        res["flags"].append(f'best-guess match for "{raw}" — confirm')
    else:
        res["flags"].append("not a recognised investigation — check")
    return res


def _normalise_investigations_against_catalog(recognized: dict, tenant_id):
    """Mutate recognized in place: rewrite `investigations` to standard test
    names and attach `investigations_resolved` (one entry per token, with the
    raw string and any flag) for the review panel. Best-effort — any failure
    leaves `investigations` exactly as recognised."""
    recognized.setdefault("investigations_resolved", [])
    tokens = _split_investigations(recognized.get("investigations") or "")
    if not tokens:
        return

    # Passthrough shape first, so the review panel renders even if we bail out.
    recognized["investigations_resolved"] = [
        {"raw": t, "name": t, "source": "verbatim", "flags": []} for t in tokens
    ]

    try:
        from rapidfuzz import process, fuzz
    except Exception:
        return
    try:
        from apps.patients.consult_pad_lab_aliases import alias_pairs
        alias_iter = list(alias_pairs())
    except Exception:
        alias_iter = []

    catalog_names = []
    if tenant_id:
        try:
            from apps.tenants.models import Tenant
            tenant = Tenant.objects.using("default").filter(pk=tenant_id).first()
            if tenant:
                from apps.lab.models import LabTest
                catalog_names = list(
                    LabTest.objects.using(tenant.db_name)
                    .filter(is_active=True).values_list("name", flat=True)
                )
        except Exception:
            logger.debug("consult-pad: lab catalog unavailable for tenant %s — using seed table only", tenant_id)

    candidates = _lab_candidate_map(catalog_names, alias_iter)
    keys = list(candidates)
    resolved = [_resolve_investigation(t, candidates, keys, process, fuzz) for t in tokens]
    recognized["investigations_resolved"] = resolved
    recognized["investigations"] = ", ".join(dict.fromkeys(r["name"] for r in resolved if r["name"]))


def _decode_pages(page_datauris):
    out = []
    for u in page_datauris or []:
        try:
            out.append(base64.b64decode(u.split(",", 1)[1]))
        except Exception:
            pass
    return out


def _run_tab_recognition(session_id, tab: str, pending_token: str):
    """
    Background worker: recognise one tab's pages and write the structured
    result onto ConsultSession.<tab>_recognised. Runs in a plain thread
    (no task queue in this project). Never raises.

    Debounced: `pending_token` is the "at" stamp written by the PUT that
    spawned this thread. After a short wait the thread re-reads the row and
    bails if the stamp changed — meaning a newer autosave has superseded it.
    The final write is also conditional on the stamp, so a save that lands
    while the model is running can't be clobbered by a stale result.
    """
    from apps.patients.consult_pad_recognition import recognise
    field = "rx_recognised" if tab == "rx" else "note_recognised"
    pages_attr = "rx_pages" if tab == "rx" else "note_pages"
    try:
        time.sleep(_RECOG_DEBOUNCE_SECONDS)

        row = (ConsultSession.objects.using("default")
               .filter(id=session_id).values(field, pages_attr, "tenant_id").first())
        if not row:
            return
        if (row[field] or {}).get("at") != pending_token:
            logger.debug("consult-pad recognition superseded before start (session=%s tab=%s)", session_id, tab)
            return

        pages = _decode_pages(row[pages_attr])
        if not pages:
            ConsultSession.objects.using("default").filter(id=session_id).update(
                **{field: {"status": "empty", "error": "", "at": timezone.now().isoformat()}})
            return

        result = recognise(pages, focus=tab)
        blob = dict(result.get("recognized") or {})
        if result.get("status") == "done":
            if tab == "rx" and row["tenant_id"]:
                _normalise_rx_against_catalog(blob, row["tenant_id"])
            if tab != "rx":
                # investigations live on the Note tab; the seed alias table
                # works with or without a tenant lab catalog.
                _normalise_investigations_against_catalog(blob, row["tenant_id"])
        blob["status"] = result["status"]
        blob["error"] = result.get("error", "")
        blob["at"] = timezone.now().isoformat()

        # Only land the result if no newer autosave arrived while we worked.
        updated = ConsultSession.objects.using("default").filter(
            id=session_id, **{f"{field}__at": pending_token}
        ).update(**{field: blob})
        if not updated:
            logger.debug("consult-pad recognition result discarded — superseded (session=%s tab=%s)", session_id, tab)
    except Exception:
        logger.exception("consult-session recognition thread crashed: session=%s tab=%s", session_id, tab)
        ConsultSession.objects.using("default").filter(
            id=session_id, **{f"{field}__at": pending_token}
        ).update(**{field: {"status": "failed", "error": "recognition crashed", "at": timezone.now().isoformat()}})
    finally:
        connections.close_all()


def _open_session_for_token(token: str):
    """token -> (identity, latest open ConsultSession | None)."""
    identity = PatientIdentity.objects.using("default").filter(consult_pad_token=token).first()
    if not identity:
        return None, None
    sess = None
    if identity.consult_pad_owner_tenant_id:
        sess = (ConsultSession.objects.using("default")
                .filter(awpid=identity.awpid, tenant_id=identity.consult_pad_owner_tenant_id,
                        status=ConsultSession.STATUS_OPEN)
                .order_by("-created_at").first())
        # Auto-expire a stale session so the phone doesn't keep writing to it.
        if sess and sess.expires_at and sess.expires_at < timezone.now():
            ConsultSession.objects.using("default").filter(id=sess.id).update(status=ConsultSession.STATUS_EXPIRED)
            sess = None
    return identity, sess


class ConsultPadView(APIView):
    """
    GET  /api/v1/consult-pad/<token>/   — patient header + both tabs' saved state
    PUT  /api/v1/consult-pad/<token>/   — autosave one tab
                                          Body: { "tab": "rx"|"note", "pages": ["data:image/png;base64,...", ...] }

    No auth. GET's "active" is false when the doctor hasn't started a session
    yet. PUT is a no-op (404-ish) once the session is signed/expired.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "consult_pad"

    def get(self, request, token):
        identity, sess = _open_session_for_token(token)
        if not identity:
            return error(message="This code is not valid. Ask the front desk for a fresh QR.", status=404)
        if not sess:
            return success(data={
                "active": False,
                "patient_name": identity.full_name,
                "patient_awpid": identity.awpid,
            })
        return success(data={
            "active": True,
            # Identifies THIS consultation. The pad token is permanent and
            # reused for every visit, so the phone uses this to tell whether
            # crash-saved local writing belongs to the session it's resuming
            # or to a previous one (which it then discards).
            "session_id": sess.id,
            "patient_name": identity.full_name,
            "patient_awpid": identity.awpid,
            "age_years": _age_years(identity.date_of_birth),
            "gender": identity.gender,
            "updated_at": sess.updated_at,
            "tabs": {
                "rx":   {"pages": sess.rx_pages or [],   "recognised": sess.rx_recognised or None},
                "note": {"pages": sess.note_pages or [], "recognised": sess.note_recognised or None},
            },
        })

    def put(self, request, token):
        identity, sess = _open_session_for_token(token)
        if not identity:
            return error(message="This code is not valid. Ask the front desk for a fresh QR.", status=404)
        if not sess:
            return error(message="This consultation isn't active. The doctor needs to start it.", status=409)

        tab = (request.data.get("tab") or "").strip()
        if tab not in _TABS:
            return error("tab must be 'rx' or 'note'.", errors={"tab": "Required."})

        pages = request.data.get("pages")
        if not isinstance(pages, list):
            return error("pages must be a list.", errors={"pages": "Required."})
        pages = [p for p in pages if p]
        if len(pages) > 20:
            return error("Please keep a note under 20 pages.")
        if sum(len(p) for p in pages) > _MAX_TAB_BASE64_CHARS:
            return error("That tab is too large to save — fewer / simpler pages.")
        for p in pages:
            try:
                validate_data_uri(p, allowed_types=("image/png",))
            except FileValidationError as exc:
                return error(str(exc), errors={"pages": str(exc)})

        pages_field = "rx_pages" if tab == "rx" else "note_pages"
        recog_field = "rx_recognised" if tab == "rx" else "note_recognised"
        # This stamp is the debounce/idempotency token: the recognition thread
        # only acts (and only writes back) while it's still the latest one.
        pending_token = timezone.now().isoformat()
        ConsultSession.objects.using("default").filter(id=sess.id).update(**{
            pages_field: pages,
            recog_field: {"status": "pending", "at": pending_token},
            "updated_at": timezone.now(),
        })
        if pages:
            threading.Thread(target=_run_tab_recognition, args=(sess.id, tab, pending_token), daemon=True).start()

        return success(data={"tab": tab, "saved_pages": len(pages), "recognise_status": "pending" if pages else "idle"},
                       message="Saved.")
