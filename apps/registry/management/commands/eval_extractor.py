"""
eval_extractor
---------------
Accuracy harness for core.lab_value_extractor, scored against the
hand-labeled corpus in core/extractor_eval_corpus.py — NOT against real
patient data (same "no retroactive ground truth exists" reasoning as
eval_classifier.py; see that command's own docstring and
core/extractor_eval_corpus.py's).

Unlike eval_classifier, there is NO offline/deterministic mode here.
Classification has a keyword layer that works with zero LLM calls, so its
eval can run fully offline by default. Extraction has no such fallback —
extraction *is* the LLM call, there's nothing else to score. So this command
always calls the real, currently-configured LAB_EXTRACTOR_LLM_MODEL (and
LAB_EXTRACTOR_VISION_MODEL if the text layer path is exercised — it isn't
here, since every corpus case is plain text). That means every run costs
real API quota and isn't perfectly reproducible run-to-run — this is a
manual tuning tool, not something to wire into CI.

    python manage.py eval_extractor                  # score the corpus
    python manage.py eval_extractor --verbose         # print every case, not just failures
    python manage.py eval_extractor --sweep           # confidence-gate sensitivity

Outcome taxonomy, severity-sorted (worst first) — matches each expected
value in a case against the extractor's output for that same case:
  SAFETY_FAIL   — wrong value/unit, but confidence >= gate (silently trusted — the worst outcome)
  HALLUCINATED  — extracted something not present in the source at all, any confidence
  MISSED        — an expected value was never extracted
  CAUGHT_WRONG  — wrong value/unit, confidence < gate (wrong, but flows to "needs review")
  FRICTION      — correct value, confidence < gate (needlessly gated — annoying, not dangerous)
  PASS          — correct value (within ~1% tolerance) and confidence >= gate
"""

import re

from django.core.management.base import BaseCommand

_CONFIDENCE_GATE = 0.7
_TOLERANCE = 0.01   # 1% — accounts for float round-tripping, not real disagreement


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _match(expected_param: str, extracted_values: list):
    """Best-effort name match: normalized substring either direction. Good
    enough for a hand-curated corpus where names are chosen to be
    unambiguous — this is an eval convenience, not core/lab_variation's
    (Phase 2) real canonicalization."""
    en = _norm(expected_param)
    for v in extracted_values:
        vn = _norm(v["parameter"])
        if en in vn or vn in en:
            return v
    return None


class Command(BaseCommand):
    help = "Score core.lab_value_extractor against the hand-labeled corpus in core/extractor_eval_corpus.py."

    def add_arguments(self, parser):
        parser.add_argument("--verbose", action="store_true",
                             help="Print every case's per-value outcomes, not just non-PASS ones.")
        parser.add_argument("--sweep", action="store_true",
                             help="Re-run the corpus across candidate confidence-gate values.")

    def handle(self, *args, **opts):
        from core import extractor_eval_corpus as corpus

        if opts["sweep"]:
            self._sweep(corpus.CASES)
            return

        results = self._run(corpus.CASES, gate=_CONFIDENCE_GATE)
        self._report(results, verbose=opts["verbose"])

    # ------------------------------------------------------------------
    def _run(self, cases, *, gate: float):
        from core import lab_value_extractor

        out = []
        for case in cases:
            extracted = lab_value_extractor.extract_text(case.text, case.panel_slugs).get("values") or []
            matched_extracted_ids = set()

            per_value = []
            for exp in case.expected_values:
                got = _match(exp.parameter, extracted)
                if got is None:
                    per_value.append(dict(expected=exp, got=None, outcome="MISSED"))
                    continue
                matched_extracted_ids.add(id(got))
                value_ok = abs(got["value"] - exp.value) <= max(_TOLERANCE * abs(exp.value), 1e-9)
                confident = got["confidence"] >= gate
                if not value_ok:
                    outcome = "SAFETY_FAIL" if confident else "CAUGHT_WRONG"
                else:
                    outcome = "PASS" if confident else "FRICTION"
                per_value.append(dict(expected=exp, got=got, outcome=outcome))

            # Anything extracted that didn't match ANY expected value is either
            # a real find the corpus under-labeled, or a hallucination — for a
            # case with expected_values=[] (deliberately qualitative-only,
            # e.g. COVID_QUALITATIVE_ONLY), every extracted row is by
            # definition unexpected and must be reported.
            for v in extracted:
                if id(v) not in matched_extracted_ids:
                    per_value.append(dict(expected=None, got=v, outcome="HALLUCINATED"))

            out.append(dict(case=case, extracted=extracted, per_value=per_value))
        return out

    # ------------------------------------------------------------------
    _SEVERITY = {"SAFETY_FAIL": 0, "HALLUCINATED": 1, "MISSED": 2, "CAUGHT_WRONG": 3, "FRICTION": 4, "PASS": 5}

    def _report(self, results, *, verbose: bool):
        from collections import Counter
        counts = Counter()
        for r in results:
            for pv in r["per_value"]:
                counts[pv["outcome"]] += 1
        total = sum(counts.values())

        for r in results:
            rows = sorted(r["per_value"], key=lambda pv: self._SEVERITY[pv["outcome"]])
            show = rows if verbose else [pv for pv in rows if pv["outcome"] != "PASS"]
            if not show:
                continue
            self.stdout.write(f"  {r['case'].name}" + (f"  -- {r['case'].notes}" if r["case"].notes and not verbose else ""))
            for pv in show:
                exp, got, outcome = pv["expected"], pv["got"], pv["outcome"]
                exp_s = f"{exp.parameter}={exp.value}{exp.unit}" if exp else "(nothing expected)"
                got_s = f"{got['parameter']}={got['value']}{got['unit']} conf={got['confidence']:.2f}" if got else "(not found)"
                self.stdout.write(f"    [{outcome:>13}] expected: {exp_s:<32} got: {got_s}")

        self.stdout.write("")
        unsafe = counts["SAFETY_FAIL"] + counts["HALLUCINATED"]
        self.stdout.write(self.style.WARNING(f"unsafe (wrong value trusted / invented from nothing): {unsafe}")
                           if unsafe else self.style.SUCCESS("unsafe (wrong value trusted / invented from nothing): 0"))
        self.stdout.write(f"missed (never extracted): {counts['MISSED']}")
        self.stdout.write(f"caught-wrong (wrong, but flagged for review): {counts['CAUGHT_WRONG']}")
        self.stdout.write(f"friction (correct, needlessly gated): {counts['FRICTION']}")
        self.stdout.write(f"pass: {counts['PASS']} / {total}")

    # ------------------------------------------------------------------
    def _sweep(self, cases):
        for gate in (0.5, 0.6, 0.65, 0.7, 0.75, 0.8, 0.9):
            results = self._run(cases, gate=gate)
            from collections import Counter
            counts = Counter()
            for r in results:
                for pv in r["per_value"]:
                    counts[pv["outcome"]] += 1
            unsafe = counts["SAFETY_FAIL"] + counts["HALLUCINATED"]
            marker = "  <- current" if gate == _CONFIDENCE_GATE else ""
            self.stdout.write(
                f"  gate={gate:<5} unsafe={unsafe:<3} missed={counts['MISSED']:<3} "
                f"caught_wrong={counts['CAUGHT_WRONG']:<3} friction={counts['FRICTION']:<3} "
                f"pass={counts['PASS']}{marker}"
            )
