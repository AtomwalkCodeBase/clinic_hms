"""
eval_classifier
---------------
Accuracy harness for core.doc_classifier, scored against the hand-labeled
corpus in core/classifier_eval_corpus.py — NOT against real patient data.

Why a synthetic corpus instead of the SharedDocument table: when a human
corrects a document in the review tray, PortalDocumentDetailView.patch()
overwrites doc_type/report_categories/classification_method in place with no
history kept, so there is no (classifier-guess, human-truth) pair anywhere
in the schema to evaluate against. See the "report-classification" project
memory. Until that's fixed (a snapshot column written at classify-time,
never touched by the patient-facing PATCH), this corpus is the only ground
truth in the repo.

Scope: text-layer classification only (kind / panel / non-medical routing),
via classify_text() — the same entry point core/tests_doc_classifier.py's
unit tests use. It does NOT exercise the image-quality blur/brightness gate
(core/image_quality.py) or the vision layer's OCR-thin fallback — those need
real image bytes, not text, and already have their own tests.

Default run is fully offline and deterministic: the text-LLM and vision
layers are force-disabled (same as the unit tests) so only the keyword
pass is scored. Pass --live to run the *configured* LLM/vision layers
instead (whatever DOC_CLASSIFIER_LLM_MODEL / DOC_CLASSIFIER_VISION_MODEL
point at right now) — this hits the real Groq API, costs quota, and is not
reproducible run-to-run if the provider's output varies.

    python manage.py eval_classifier                  # keyword layer only
    python manage.py eval_classifier --verbose         # print every case
    python manage.py eval_classifier --live            # + configured LLM/vision
    python manage.py eval_classifier --sweep           # threshold sensitivity

What "safe" means here: a SAFETY_FAIL is a case the pipeline was confident
enough to auto-file (no human ever sees it) but got wrong — that's a document
silently misfiled in someone's medical vault. A FALSE_SKIP is worse: a real
medical record wrongly judged non-medical and never stored at all. FRICTION
just means a case that could safely have been auto-filed instead asked a
human to confirm — annoying, not dangerous. The --sweep table exists so
threshold changes can be judged by how they move SAFETY_FAIL/FALSE_SKIP
counts, not guessed at.
"""

from django.core.management.base import BaseCommand
from django.test.utils import override_settings


class Command(BaseCommand):
    help = "Score core.doc_classifier against the hand-labeled corpus in core/classifier_eval_corpus.py."

    def add_arguments(self, parser):
        parser.add_argument("--live", action="store_true",
                             help="Use the configured LLM/vision layers instead of forcing them off "
                                  "(hits the real Groq API).")
        parser.add_argument("--verbose", action="store_true",
                             help="Print every case, not just non-PASS outcomes.")
        parser.add_argument("--sweep", action="store_true",
                             help="Re-run the corpus across candidate values of the confidence "
                                  "thresholds and report how SAFETY_FAIL / FRICTION counts move.")

    def handle(self, *args, **opts):
        from core import classifier_eval_corpus as corpus

        live = opts["live"]
        verbose = opts["verbose"]

        if opts["sweep"]:
            self._sweep(corpus.CASES, live=live)
            return

        results = self._run(corpus.CASES, live=live)
        self._report(results, verbose=verbose)

    # ------------------------------------------------------------------
    def _run(self, cases, *, live: bool):
        from core import doc_classifier, report_types

        def _classify(text):
            if live:
                return doc_classifier.classify_text(text)
            with override_settings(DOC_CLASSIFIER_LLM="", DOC_CLASSIFIER_VISION_MODEL=""):
                return doc_classifier.classify_text(text)

        out = []
        for case in cases:
            r = _classify(case.text)

            kind_ok = (r.doc_type == case.doc_type)
            if case.doc_type == "lab_report" and case.categories:
                if len(case.categories) > 1:
                    # Multi-panel (health package): nothing downstream reads
                    # categories[0] specifically — report_categories is
                    # stored and filtered as a full list (see
                    # apps/patients/portal_views.py), so only "is every
                    # expected panel present" is a real correctness question.
                    # Which one ranks first is cosmetic, not scored here.
                    category_ok = set(case.categories).issubset(set(r.categories))
                else:
                    predicted_primary = r.categories[0] if r.categories else None
                    category_ok = predicted_primary == case.categories[0]
            else:
                category_ok = True
            nonmed_ok = (r.non_medical == case.non_medical)
            content_correct = kind_ok and category_ok and nonmed_ok

            panel_confident = (r.doc_type != "lab_report") or (r.category_confidence >= report_types.CONFIDENT)
            if r.non_medical:
                predicted_action = "skip"
            elif r.confident and panel_confident:
                predicted_action = "file"
            else:
                predicted_action = "ask"
            expected_action = "skip" if case.non_medical else ("file" if case.should_autofile else "ask")

            outcome = self._outcome(case, predicted_action, content_correct)

            out.append(dict(
                case=case, result=r, kind_ok=kind_ok, category_ok=category_ok, nonmed_ok=nonmed_ok,
                content_correct=content_correct, predicted_action=predicted_action,
                expected_action=expected_action, outcome=outcome,
            ))
        return out

    @staticmethod
    def _outcome(case, predicted_action, content_correct) -> str:
        if case.non_medical:
            if predicted_action == "skip":
                return "PASS"
            if predicted_action == "file":
                return "DATA_RISK"          # a non-medical/private doc auto-filed as a real record
            return "ASK_INSTEAD_OF_SKIP"    # sent to review, not skipped — mild friction

        if predicted_action == "skip":
            return "FALSE_SKIP"             # a real record silently dropped — worst outcome

        if predicted_action == "file":
            if not content_correct:
                return "SAFETY_FAIL"        # auto-filed and wrong — no human ever sees the error
            return "PASS" if case.should_autofile else "OVERCONFIDENT"  # right answer, shouldn't have been sure

        # predicted_action == "ask"
        if case.should_autofile:
            return "FRICTION"               # could safely have been auto-filed, asked anyway
        return "PASS" if content_correct else "CAUGHT_WRONG_PREFILL"    # flagged for review; pre-fill is wrong but a human will fix it

    # ------------------------------------------------------------------
    _SEVERITY = {
        "SAFETY_FAIL": 0, "FALSE_SKIP": 0, "DATA_RISK": 0,
        "CAUGHT_WRONG_PREFILL": 1, "OVERCONFIDENT": 1,
        "FRICTION": 2, "ASK_INSTEAD_OF_SKIP": 2,
        "PASS": 3,
    }

    def _report(self, results, *, verbose: bool):
        from collections import Counter
        counts = Counter(r["outcome"] for r in results)
        total = len(results)

        rows = sorted(results, key=lambda r: (self._SEVERITY[r["outcome"]], r["case"].name))
        for r in rows:
            if not verbose and r["outcome"] == "PASS":
                continue
            c, res = r["case"], r["result"]
            self.stdout.write(
                f"  [{r['outcome']:>21}] {c.name:<32} "
                f"expected={c.doc_type}{c.categories[:1]!s:<10} "
                f"got={res.doc_type}{res.categories[:1]!s:<10} "
                f"conf={res.confidence:.2f} catconf={res.category_confidence:.2f}"
                + (f"   -- {c.notes}" if c.notes else "")
            )

        self.stdout.write("")
        unsafe = counts["SAFETY_FAIL"] + counts["FALSE_SKIP"] + counts["DATA_RISK"]
        self.stdout.write(self.style.WARNING(f"unsafe (auto-filed wrong / dropped a record): {unsafe}")
                           if unsafe else self.style.SUCCESS("unsafe (auto-filed wrong / dropped a record): 0"))
        self.stdout.write(f"calibration-only (flagged but wrong pre-fill, or right-by-luck): "
                           f"{counts['CAUGHT_WRONG_PREFILL'] + counts['OVERCONFIDENT']}")
        self.stdout.write(f"friction (safe to auto-file, asked anyway): "
                           f"{counts['FRICTION'] + counts['ASK_INSTEAD_OF_SKIP']}")
        self.stdout.write(f"pass: {counts['PASS']} / {total}")

    # ------------------------------------------------------------------
    def _sweep(self, cases, *, live: bool):
        from core import doc_classifier, report_types

        params = [
            ("doc_classifier.CONFIDENT", doc_classifier, "CONFIDENT",
             [0.65, 0.70, 0.75, 0.80, 0.85]),
            ("doc_classifier._STRONG_KEYWORD", doc_classifier, "_STRONG_KEYWORD",
             [0.85, 0.90, 0.93, 0.95]),
            ("report_types.CONFIDENT", report_types, "CONFIDENT",
             [0.65, 0.70, 0.72, 0.75, 0.80]),
            ("report_types.MULTI_KEEP", report_types, "MULTI_KEEP",
             [0.45, 0.50, 0.55, 0.60, 0.65]),
        ]

        for label, module, attr, values in params:
            original = getattr(module, attr)
            self.stdout.write(self.style.MIGRATE_HEADING(f"{label} (current: {original})"))
            for v in values:
                setattr(module, attr, v)
                try:
                    results = self._run(cases, live=live)
                finally:
                    setattr(module, attr, original)
                from collections import Counter
                counts = Counter(r["outcome"] for r in results)
                unsafe = counts["SAFETY_FAIL"] + counts["FALSE_SKIP"] + counts["DATA_RISK"]
                friction = counts["FRICTION"] + counts["ASK_INSTEAD_OF_SKIP"]
                marker = "  <- current" if v == original else ""
                self.stdout.write(
                    f"    {v:<6} unsafe={unsafe:<3} friction={friction:<3} "
                    f"pass={counts['PASS']}/{len(cases)}{marker}"
                )
            self.stdout.write("")
