"""
core/doc_rules.py
-----------------
The keyword vocabulary behind the rule-based document classifier, read from
the `doc_classification_rule` table (platform admin → Classification rules)
so keywords can be added or retired without a code change.

    hints(doc_type)  -> tuple of lower-case keywords for that type — what
                        core.doc_classifier's keyword pass scores against.
    score(text)      -> per-type {"score", "hits", "required", "matched"}:
                        score = hits / required_hits, capped at 1.0
                        (4 of 5 required keywords present = 0.8).

Rows are cached in-process for _TTL seconds and the cache is dropped
whenever the admin API saves a rule (invalidate()). If the table is empty
or unreachable (tests, a fresh DB before migrate) the hard-coded tuples in
core.doc_classifier are used, so classification never breaks on config.
"""

import logging
import time

logger = logging.getLogger(__name__)

TYPES = ("prescription", "lab_report", "scan", "discharge_summary", "not_medical")
_TTL = 60
_cache = {"at": 0.0, "rules": None}


def _fallback():
    from core import doc_classifier as dc
    return {
        "lab_report":        [("built-in", dc._LAB_HINTS, 5)],
        "prescription":      [("built-in", dc._RX_HINTS, 5)],
        "scan":              [("built-in", dc._IMG_HINTS, 3)],
        "discharge_summary": [("built-in", dc._DISCHARGE_HINTS, 3)],
        "not_medical":       [("built-in", dc._NON_MEDICAL_HINTS, 2)],
    }


def _load():
    """{doc_type: [(rule_name, keywords_tuple, required_hits), ...]}"""
    now = time.monotonic()
    if _cache["rules"] is not None and now - _cache["at"] < _TTL:
        return _cache["rules"]
    rules = None
    try:
        from apps.registry.models import DocumentClassificationRule
        rows = list(DocumentClassificationRule.objects.using("default").filter(is_active=True))
        if rows:
            rules = {t: [] for t in TYPES}
            for r in rows:
                kws = tuple(r.keyword_list())
                if kws and r.doc_type in rules:
                    rules[r.doc_type].append((r.name, kws, max(1, r.required_hits or 1)))
            # A type with no active rows falls back to the built-in list rather
            # than silently never matching.
            fb = _fallback()
            for t in TYPES:
                if not rules[t]:
                    rules[t] = fb[t]
    except Exception:
        logger.debug("doc_rules: rule table unavailable; using built-in vocabulary", exc_info=True)
    if rules is None:
        rules = _fallback()
    _cache.update(at=now, rules=rules)
    return rules


def invalidate():
    _cache.update(at=0.0, rules=None)


def hints(doc_type):
    """Union of every active keyword for `doc_type`, order-preserving."""
    seen, out = set(), []
    for _name, kws, _req in _load().get(doc_type, []):
        for k in kws:
            if k not in seen:
                seen.add(k)
                out.append(k)
    return tuple(out)


def score(text_lower):
    """Per-type hit-ratio scores; the best-scoring rule row wins for a type."""
    out = {}
    for t, rows in _load().items():
        best = {"score": 0.0, "hits": 0, "required": 0, "matched": [], "rule": ""}
        for name, kws, req in rows:
            matched = [k for k in kws if k in text_lower]
            s = min(1.0, len(matched) / req)
            if s > best["score"] or (s == best["score"] and len(matched) > best["hits"]):
                best = {"score": round(s, 2), "hits": len(matched), "required": req,
                        "matched": matched[:12], "rule": name}
        out[t] = best
    return out
