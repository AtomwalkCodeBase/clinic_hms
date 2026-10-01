import math

from django.test import SimpleTestCase

from apps.records.scoring import MIN_EVIDENCE, evidence, parse_keywords, score


def confidence(hits, runner_up, scale=10.0):
    return round(100 * (0.6 * (1 - math.exp(-hits / scale)) + 0.4 * (1 - runner_up / hits)), 1)


class ParseKeywordsTests(SimpleTestCase):
    def test_weights_and_minus_words(self):
        positive, negative = parse_keywords("Lab Report^3 | glucose | reference range^2 | -discharge summary | ")
        self.assertEqual(positive, [("lab report", 3.0), ("glucose", 1.0), ("reference range", 2.0)])
        self.assertEqual(negative, [("discharge summary", 1.0)])

    def test_a_bad_or_extreme_weight_is_tamed(self):
        self.assertEqual(parse_keywords("a^x|b^99|c^0")[0], [("a", 1.0), ("b", 10.0), ("c", 0.1)])


class EvidenceTests(SimpleTestCase):
    def test_whole_words_only(self):
        # "im" and "iv" used to match inside ordinary words
        self.assertEqual(evidence("the time of the section", "im|iv|sc")[0], 0)
        self.assertEqual(evidence("give iv fluids; rx: tablet", "iv|rx")[1], ["iv", "rx"])

    def test_a_phrase_matches_across_a_line_break(self):
        text = " ".join("Sample\n  collected on 4 Sept".lower().split())
        self.assertEqual(evidence(text, "sample collected")[0], 1)

    def test_a_weighted_word_counts_more_and_a_minus_word_takes_away(self):
        self.assertEqual(evidence("laboratory report glucose", "laboratory report^3|glucose")[0], 4)
        self.assertEqual(evidence("laboratory report discharge summary", "laboratory report^3|-discharge summary^2")[0], 1)
        self.assertEqual(evidence("discharge summary", "laboratory report|-discharge summary")[0], 0)      # never below zero


class ScoreTests(SimpleTestCase):
    RULES = {"lab_report": "laboratory|hemoglobin|glucose|cholesterol|reference range",
             "prescription": "tablet|dosage|rx|medicine"}

    def test_a_clear_winner_has_a_high_confidence(self):
        best, conf, details = score("Laboratory report: hemoglobin, glucose, cholesterol, reference range. Rx", self.RULES)
        self.assertEqual((best, details["runner_up"], details["evidence"]), ("lab_report", "prescription", 5.0))
        self.assertEqual(conf, confidence(5, 1))
        self.assertEqual(details["matched"], ["laboratory", "hemoglobin", "glucose", "cholesterol", "reference range"])

    def test_the_length_of_the_keyword_list_does_not_change_the_confidence(self):
        text = "laboratory hemoglobin glucose cholesterol"
        short = score(text, {"lab": "laboratory|hemoglobin|glucose|cholesterol"})[1]
        long = score(text, {"lab": "laboratory|hemoglobin|glucose|cholesterol|" + "|".join(f"word{i}" for i in range(200))})[1]
        self.assertEqual(short, long)

    def test_more_evidence_means_more_confidence(self):
        confs = [score(" ".join(f"w{i}" for i in range(n)), {"t": "|".join(f"w{i}" for i in range(30))})[1] for n in (3, 8, 15, 25)]
        self.assertEqual(confs, sorted(confs))
        self.assertGreater(confs[-1], 90)

    def test_a_tie_is_not_confident(self):
        _, conf, details = score("tablet laboratory", {"a": "tablet|x1", "b": "laboratory|x2"})
        self.assertLess(conf, 30)
        self.assertEqual(details["runner_up"], "b")

    def test_nothing_found_is_zero(self):
        self.assertEqual(score("hello", self.RULES), ("", 0.0, {"best_guess": "", "evidence": 0.0, "matched": [], "runner_up": ""}))
        self.assertEqual(score("", self.RULES)[:2], ("", 0.0))
        self.assertEqual(score("laboratory", {})[:2], ("", 0.0))

    def test_the_scale_sets_how_much_evidence_is_plenty(self):
        text = "laboratory hemoglobin glucose"
        loose = score(text, self.RULES, scale=3)[1]
        strict = score(text, self.RULES, scale=30)[1]
        self.assertGreater(loose, strict)

    def test_the_minimum_evidence_is_a_few_hits(self):
        self.assertEqual(MIN_EVIDENCE, 3.0)
