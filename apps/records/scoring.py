"""
Rule-based scoring. The confidence of a verdict answers two questions, not "what share of the keyword list
was found" (which shrinks every time someone adds a keyword):

    evidence    how much matched?      100 · (1 − e^(−W / scale)) — flattens out, so a long list costs nothing
    separation  how clearly does it win?   1 − runner-up / winner   — a tie is 0, a clear winner is near 1

    confidence = 60 % evidence + 40 % separation

W is the weight of the distinct keywords of a type found in the text, whole words only. A type's keywords are
written in Platform Admin as  pipe|separated  and may carry a weight and a minus:

    laboratory report^3|glucose|reference range^2|-discharge summary

    word^3     counts 3 instead of 1 (a strong phrase)
    -word      rules the type out: its weight is taken away when the word is found
"""
import math
import re
from functools import lru_cache

EVIDENCE_SHARE = 0.6        # the rest of the confidence is separation
MIN_EVIDENCE = 3.0          # weighted hits the winner needs at all, whatever its confidence


@lru_cache(maxsize=8192)
def _whole_word(word):
    return re.compile(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])")


def parse_keywords(text):
    """'lab report^3|glucose|-discharge' → ([('lab report', 3.0), ('glucose', 1.0)], [('discharge', 1.0)])."""
    positive, negative = [], []
    for raw in (text or "").split("|"):
        raw = raw.strip().lower()
        if not raw:
            continue
        is_negative = raw.startswith("-")
        word, _, weight = raw.lstrip("-").strip().partition("^")
        word = word.strip()
        try:
            weight = min(max(float(weight), 0.1), 10.0) if weight.strip() else 1.0
        except ValueError:
            weight = 1.0
        if word:
            (negative if is_negative else positive).append((word, weight))
    return positive, negative


def evidence(text, keywords_text):
    """(W, matched words) for one type. `text` is already normalised (see score)."""
    positive, negative = parse_keywords(keywords_text)
    found = [(w, wt) for w, wt in positive if _whole_word(w).search(text)]
    ruled_out = sum(wt for w, wt in negative if _whole_word(w).search(text))
    return max(0.0, sum(wt for _, wt in found) - ruled_out), [w for w, _ in found]


def score(text, rules, *, scale=10.0):
    """`rules` = {type: keywords text}. Returns (best type | "", confidence 0–100, details). Never decides:
    whether the confidence is enough is for the caller's bar."""
    text = " ".join((text or "").lower().split())
    ranked = sorted(((*evidence(text, kw), t) for t, kw in rules.items()), key=lambda r: (-r[0], r[2]))
    if not ranked or ranked[0][0] <= 0:
        return "", 0.0, {"best_guess": "", "evidence": 0.0, "matched": [], "runner_up": ""}
    best_w, matched, best = ranked[0]
    second_w, _, second = ranked[1] if len(ranked) > 1 else (0.0, [], "")
    ev = 1 - math.exp(-best_w / max(scale, 0.1))
    sep = 1 - second_w / best_w
    confidence = round(100 * (EVIDENCE_SHARE * ev + (1 - EVIDENCE_SHARE) * sep), 1)
    return best, confidence, {"best_guess": best, "evidence": round(best_w, 2), "matched": matched[:25],
                              "runner_up": second if second_w else ""}
