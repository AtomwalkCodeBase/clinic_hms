"""The rule engine (classification.py): pure scoring, then how a verdict is recorded."""
from django.test import SimpleTestCase, TestCase

from apps.records import classification as c
from apps.records.models import PatientDocumentClassification
from apps.records.tests.helpers import make_doc, reload

RX = "Dr ABC Rx Paracetamol Syrup 5 ml TDS Diagnosis: Viral fever"
LAB = "Laboratory Report Hemoglobin 13.2 g/dL Reference Range 12-16 Glucose Result Normal"


class RulesTests(SimpleTestCase):
    """The hardcoded rules are consistent."""

    def test_every_rule_belongs_to_a_known_type_and_level(self):
        for document_type, levels in c.DOCUMENT_RULES.items():
            self.assertIn(document_type, c.DOCUMENT_TYPES)
            self.assertLessEqual(set(levels), set(c.WEIGHTS))

    def test_every_type_a_rule_can_assign_has_rules_and_the_rest_are_a_persons_choice(self):
        self.assertEqual(set(c.DOCUMENT_TYPES) - set(c.DOCUMENT_RULES), {"other", c.NOT_CLASSIFIED})

    def test_keywords_are_lower_case_and_not_repeated_within_a_type(self):
        for levels in c.DOCUMENT_RULES.values():
            words = [w for ws in levels.values() for w in ws]
            self.assertTrue(all(w == w.lower() for w in words))
            self.assertEqual(len(words), len(set(words)))

    def test_not_classified_is_a_state_not_a_choice(self):
        self.assertIn(c.NOT_CLASSIFIED, c.DOCUMENT_TYPES)
        self.assertNotIn(c.NOT_CLASSIFIED, c.CHOOSABLE_TYPES)
        self.assertIn("other", c.CHOOSABLE_TYPES)

    def test_codes_are_lower_case_snake_case(self):
        self.assertTrue(all(code == code.lower() and " " not in code for code in c.DOCUMENT_TYPES))


class EngineTests(SimpleTestCase):
    def test_text_is_normalised(self):
        self.assertEqual(c.normalize_text("  Lab\n\n  REPORT\t"), "lab report")
        self.assertEqual(c.normalize_text(None), "")

    def test_keywords_match_whole_words_only(self):
        self.assertEqual(c.calculate_document_scores("xerox copy")["prescription"]["score"], 0)       # "rx" is not in "xerox"
        self.assertEqual(c.calculate_document_scores("billion")["medical_bill"]["score"], 0)          # "bill no"/"bill" not "billion"
        self.assertEqual(c.calculate_document_scores("500mg")["prescription"]["score"], 3)            # a unit glued to a number counts

    def test_a_phrase_the_ocr_ran_together_still_matches(self):
        glued = c.calculate_document_scores("ReferenceRange")["lab_report"]
        self.assertEqual([m["keyword"] for m in glued["matched_rules"]], ["reference range"])
        self.assertEqual(glued["score"], 10)
        # a single word is never found inside a longer one, even when the text is squashed
        self.assertEqual(c.calculate_document_scores("abnormality")["lab_report"]["score"], 0)

    def test_a_unit_is_not_a_dose_and_a_ref_doctor_line_is_not_a_prescriber(self):
        scores = c.calculate_document_scores("Haemoglobin 13.6 mg/dL\nRef. Doctor : Dr. A. Rao MBBS\nSodium 140 mmol/L")["prescription"]
        self.assertEqual(scores["score"], 0)
        self.assertEqual(c.calculate_document_scores("Tab Metformin 500 mg")["prescription"]["score"], 6)      # tab + mg

    def test_weights_are_ten_three_and_one(self):
        scores = c.calculate_document_scores(RX)["prescription"]
        levels = {m["keyword"]: m["weight"] for m in scores["matched_rules"]}
        self.assertEqual(levels, {"rx": 10, "syrup": 3, "ml": 3, "tds": 3, "diagnosis": 1, "dr": 1})
        self.assertEqual(scores["score"], 21)

    def test_a_keyword_counts_once_however_often_it_appears(self):
        self.assertEqual(c.calculate_document_scores("rx rx rx rx")["prescription"]["score"], 10)

    def test_a_clear_winner_is_classified(self):
        result = c.classify_document_by_rules(RX)
        self.assertEqual((result["document_type"], result["status"], result["best_guess"]),
                         ("prescription", c.RULE_CLASSIFIED, "prescription"))
        self.assertEqual((result["score"], result["second_best_score"], result["score_margin"]), (21, 1, 20))
        self.assertTrue(result["matched_rules"])

    def test_a_lab_report_is_classified(self):
        result = c.classify_document_by_rules(LAB)
        self.assertEqual((result["document_type"], result["status"]), ("lab_report", c.RULE_CLASSIFIED))

    def test_a_tie_needs_a_person(self):
        result = c.classify_document_by_rules("discharge summary and invoice")
        self.assertEqual((result["document_type"], result["status"]), (c.NOT_CLASSIFIED, c.REVIEW_REQUIRED))
        self.assertEqual((result["score"], result["score_margin"]), (13, 3))           # discharge summary 10 + discharge 3, against invoice 10
        self.assertEqual(result["best_guess"], "discharge_summary")          # what it came closest to, for the reviewer

    def test_weak_words_alone_never_classify(self):
        result = c.classify_document_by_rules("diagnosis follow up advice")
        self.assertEqual((result["document_type"], result["status"]), (c.NOT_CLASSIFIED, c.REVIEW_REQUIRED))

    def test_a_winner_must_lead_by_the_margin(self):
        # medical_bill 30 (invoice, tax invoice, gst) against prescription 26 (rx, prescription, tablet, syrup):
        # it leads by 4, which is under MIN_MARGIN, so nobody wins
        result = c.classify_document_by_rules("rx prescription tablet syrup invoice tax invoice gst")
        self.assertEqual((result["score"], result["second_best_score"], result["score_margin"]), (30, 26, 4))
        self.assertLess(result["score_margin"], c.MIN_MARGIN)
        self.assertEqual((result["document_type"], result["best_guess"]), (c.NOT_CLASSIFIED, "medical_bill"))
        # two more medium words on the winner's side and it leads by 13: classified ("subtotal" also matches the phrase "sub total")
        clear = c.classify_document_by_rules("rx prescription tablet syrup invoice tax invoice gst discount subtotal")
        self.assertEqual((clear["score_margin"], clear["document_type"]), (13, "medical_bill"))

    def test_text_with_no_match_is_not_classified_with_no_guess(self):
        result = c.classify_document_by_rules("hello world")
        self.assertEqual((result["document_type"], result["status"], result["best_guess"], result["score"]),
                         (c.NOT_CLASSIFIED, c.REVIEW_REQUIRED, "", 0))
        self.assertEqual(c.classify_document_by_rules("")["document_type"], c.NOT_CLASSIFIED)

    def test_other_is_never_assigned_by_the_rules(self):
        for text in (RX, LAB, "hello", "diagnosis"):
            self.assertNotEqual(c.classify_document_by_rules(text)["document_type"], "other")


class StoreTests(TestCase):
    databases = {"default"}

    def test_the_rules_verdict_is_recorded_on_the_classification_and_the_document(self):
        doc = make_doc(status="classifying")
        result = c.classify_document_by_rules(RX)
        classification = c.store_rule_result(doc, result)
        self.assertEqual(doc.document_type, "prescription")
        self.assertEqual((classification.classifier, classification.ai_document_type, classification.final_document_type,
                          classification.status), ("rule_engine", "prescription", "prescription", "rule_classified"))
        self.assertEqual((classification.rule_score, classification.second_best_score, classification.score_margin),
                         (21, 1, 20))
        self.assertEqual({m["keyword"] for m in classification.rule_matches}, {"rx", "syrup", "ml", "tds", "diagnosis", "dr"})

    def test_an_ambiguous_verdict_keeps_what_it_came_closest_to(self):
        doc = make_doc(status="classifying")
        classification = c.store_rule_result(doc, c.classify_document_by_rules("discharge summary and invoice"))
        self.assertEqual((doc.document_type, classification.ai_document_type, classification.final_document_type,
                          classification.status), (c.NOT_CLASSIFIED, "discharge_summary", c.NOT_CLASSIFIED, c.REVIEW_REQUIRED))

    def test_running_the_rules_again_updates_the_same_row(self):
        doc = make_doc(status="classifying")
        c.store_rule_result(doc, c.classify_document_by_rules("hello"))
        c.store_rule_result(doc, c.classify_document_by_rules(RX))
        self.assertEqual(PatientDocumentClassification.objects.filter(document=doc).count(), 1)
        self.assertEqual(PatientDocumentClassification.objects.get(document=doc).final_document_type, "prescription")

    def test_a_persons_choice_is_never_overwritten_by_the_rules(self):
        doc = make_doc(status="classifying")
        c.store_human_choice(doc, "imaging_report")
        doc.save()
        c.store_rule_result(doc, c.classify_document_by_rules(RX))
        row = PatientDocumentClassification.objects.get(document=doc)
        self.assertEqual((row.status, row.final_document_type, row.human_document_type),
                         (c.HUMAN_CLASSIFIED, "imaging_report", "imaging_report"))
        self.assertEqual(doc.document_type, "imaging_report")

    def test_a_person_can_only_choose_a_real_type(self):
        doc = make_doc()
        for bad in ("made_up", c.NOT_CLASSIFIED, "LAB_REPORT", ""):
            with self.assertRaises(ValueError):
                c.store_human_choice(doc, bad)

    def test_a_hospital_issued_type_is_kept_and_an_unknown_one_becomes_other(self):
        doc = make_doc()
        c.store_issued_type(doc, "lab_report")
        row = PatientDocumentClassification.objects.get(document=doc)
        self.assertEqual((doc.document_type, row.classifier, row.status), ("lab_report", c.CLASSIFIER_HOSPITAL, c.ISSUED))
        c.store_issued_type(doc, "something_new")
        self.assertEqual(doc.document_type, "other")

    def test_the_rules_never_replace_an_issued_type(self):
        doc = make_doc()
        c.store_issued_type(doc, "prescription")
        c.store_rule_result(doc, c.classify_document_by_rules(LAB))
        self.assertEqual(doc.document_type, "prescription")

    def test_the_documents_method_score_and_best_guess_follow_its_classification(self):
        doc = make_doc(status="completed", document_type="lab_report", by="rules")
        self.assertEqual((c.method_of(doc), c.score_of(doc), c.best_guess_of(doc)), ("rule", 20, ""))
        guess = make_doc(status="review_required", by="rules")
        PatientDocumentClassification.objects.filter(document=guess).update(ai_document_type="lab_report")
        self.assertEqual((c.method_of(reload(guess)), c.best_guess_of(reload(guess))), ("rule", "lab_report"))
        self.assertEqual(c.method_of(make_doc(status="completed", document_type="other", by="human")), "staff")
        self.assertEqual(c.method_of(make_doc(status="completed", document_type="prescription", by="issued")), "staff")
        self.assertEqual(c.method_of(make_doc(status="queued")), "")
        self.assertEqual(c.text_of(make_doc(text="hello")), "hello")
        self.assertEqual(c.text_of(make_doc()), "")
