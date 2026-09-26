from unittest import mock

import fitz
import requests
from django.conf import settings
from django.test import TestCase, override_settings

from apps.records import services
from apps.records.models import ClassificationRule

LAB_TEXT = "City laboratory. Hemoglobin 13 g/dL, glucose 90, cholesterol 180. Reference range attached."


def llm_reply(content):
    resp = mock.Mock()
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    return resp


class RuleTests(TestCase):
    databases = {"default"}

    def test_rules_come_from_the_database(self):
        self.assertIn("lab_report", services.load_rules())                    # seeded by the migration
        self.assertEqual(services.rule_classify(LAB_TEXT, services.load_rules()), ("lab_report", 100.0))

    def test_a_rule_change_applies_to_the_next_document(self):
        ClassificationRule.objects.create(doc_type="dental", keywords="tooth|molar|dentist")
        rules = services.load_rules()
        self.assertEqual(rules["dental"], ["tooth", "molar", "dentist"])
        self.assertEqual(services.rule_classify("dentist removed a molar tooth", rules), ("dental", 100.0))

        ClassificationRule.objects.filter(doc_type="dental").update(is_active=False)
        self.assertNotIn("dental", services.load_rules())


class ClassifyTests(TestCase):
    databases = {"default"}

    @mock.patch("apps.records.services.requests.post")
    def test_score_75_or_more_uses_the_rules_only(self, post):
        self.assertEqual(services.classify(LAB_TEXT), ("lab_report", 100.0, "rule"))
        post.assert_not_called()

    @mock.patch("apps.records.services.requests.post", return_value=llm_reply("prescription|88"))
    def test_under_75_asks_the_llm_with_the_same_rules(self, post):
        result = services.classify("Take one tablet after food")                 # prescription 40%
        self.assertEqual(result, ("prescription", 88.0, "llm"))
        prompt = post.call_args.kwargs["json"]["messages"][0]["content"]
        for rule in ClassificationRule.objects.filter(is_active=True):
            self.assertIn(f"{rule.doc_type}: {rule.keywords}", prompt)

    @mock.patch("apps.records.services.requests.post", return_value=llm_reply("invoice|95"))
    def test_an_llm_type_outside_the_rules_becomes_other(self, post):
        self.assertEqual(services.classify("some unclear text"), ("other", 95.0, "llm"))

    def test_no_text_is_other_without_calling_anything(self):
        self.assertEqual(services.classify("   "), ("other", 0.0, "rule"))


class LLMModeTests(TestCase):
    """LLM_MODE selects local vs production for llm_classify()/llm_complete() — same Ollama
    /chat/completions contract for both, no fallback either way, and no silent default on a typo."""
    databases = {"default"}

    @override_settings(LLM_MODE="local")
    @mock.patch("apps.records.services.requests.post", return_value=llm_reply("prescription|88"))
    def test_local_mode_hits_the_local_ollama_url_and_existing_classification_is_unaffected(self, post):
        self.assertEqual(services.classify("Take one tablet after food"), ("prescription", 88.0, "llm"))
        self.assertIn("chat/completions", post.call_args.args[0])
        self.assertIn(settings.DOC_CLASSIFIER_LLM_BASE.rstrip("/"), post.call_args.args[0])

    @override_settings(LLM_MODE="production", LLM_PRODUCTION_URL="http://gpu-server:9000")
    @mock.patch("apps.records.services.requests.post", return_value=llm_reply("prescription|88"))
    def test_production_mode_hits_the_production_url_with_the_same_contract(self, post):
        self.assertEqual(services.classify("Take one tablet after food"), ("prescription", 88.0, "llm"))
        self.assertEqual(post.call_args.args[0], "http://gpu-server:9000/chat/completions")
        self.assertEqual(post.call_args.kwargs["json"]["model"], settings.LLM_PRODUCTION_MODEL)
        self.assertEqual(post.call_args.kwargs["json"]["options"], {"num_ctx": settings.LLM_NUM_CTX})

    @override_settings(LLM_MODE="production", LLM_PRODUCTION_URL="http://gpu-server:9000")
    @mock.patch("apps.records.services.requests.post", side_effect=requests.RequestException("gpu down"))
    def test_production_failure_does_not_fall_back_to_local(self, post):
        with self.assertRaises(services.LLMUnavailable):
            services.llm_complete("", "hello")
        self.assertEqual(post.call_count, 1)                              # never a second, local attempt
        self.assertEqual(post.call_args.args[0], "http://gpu-server:9000/chat/completions")

    @override_settings(LLM_MODE="production", LLM_PRODUCTION_URL="")
    def test_production_mode_without_a_url_configured_is_unavailable_not_local(self):
        with self.assertRaises(services.LLMUnavailable):
            services.llm_complete("", "hello")

    @override_settings(LLM_MODE="banana")
    def test_an_invalid_llm_mode_raises_instead_of_silently_using_local(self):
        with mock.patch("apps.records.services.requests.post") as post:
            with self.assertRaises(ValueError):
                services.llm_complete("", "hello")
            post.assert_not_called()                                      # never silently ran locally

    def test_rule_based_classification_is_unaffected_by_llm_mode(self):
        """Above the rule threshold, no LLM call happens at all — LLM_MODE is irrelevant here."""
        with mock.patch("apps.records.services.requests.post") as post:
            self.assertEqual(services.classify(LAB_TEXT), ("lab_report", 100.0, "rule"))
            post.assert_not_called()

    @override_settings(LLM_MODE="production", LLM_PRODUCTION_URL="http://gpu-server:9000")
    @mock.patch("apps.records.services.requests.get")
    def test_status_checks_the_same_endpoint_shape_for_production_as_local(self, get):
        get.return_value = mock.Mock(ok=True)
        self.assertEqual(services.llm_status(), {"mode": "production", "reachable": True})
        self.assertEqual(get.call_args.args[0], "http://gpu-server:9000/models")

    @override_settings(LLM_MODE="banana")
    def test_status_reports_an_invalid_mode_instead_of_raising(self):
        status = services.llm_status()
        self.assertEqual(status["mode"], "invalid")
        self.assertFalse(status["reachable"])
        self.assertIn("LLM_MODE", status["error"])


class ExtractTextTests(TestCase):
    def test_pdf_with_a_text_layer_needs_no_ocr(self):
        doc = fitz.open()
        doc.new_page().insert_text((50, 80), LAB_TEXT, fontsize=10)
        with mock.patch("apps.records.services.ocr") as ocr:
            text = services.extract_text(doc.tobytes(), "application/pdf")
        self.assertIn("Hemoglobin", text)
        ocr.run.assert_not_called()

    def test_image_goes_through_rapidocr(self):
        with mock.patch("apps.records.services.ocr") as ocr:
            ocr.run.return_value.text = " Rx tablet "
            self.assertEqual(services.extract_text(b"\xff\xd8\xff...", "image/jpeg"), "Rx tablet")
            ocr.run.assert_called_once()
