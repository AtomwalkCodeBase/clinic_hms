from unittest import mock

from django.conf import settings
from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.records import services
from apps.records.views import LLMAskView, LLMChatView, LLMStatusView
from core.authentication import MockUser


def call(view, method, path, data=None):
    factory = getattr(APIRequestFactory(), method)
    request = factory(path, data or {}, format="json") if data is not None else factory(path)
    force_authenticate(request, user=MockUser({"user_id": 1, "role": "patient", "awpid": "AWP-T1"}))
    return view.as_view()(request)


class AskChatViewTests(TestCase):
    """/llm_api/ask/ and /llm_api/chat/ — identical contract, both routed through llm_complete()."""

    @mock.patch("apps.records.views.llm_complete")
    def test_ask_request_and_response(self, complete):
        complete.return_value = {"content": "Claim 1: A method comprising...", "prompt_tokens": 450,
                                  "completion_tokens": 820, "generation_time": 12.5}
        resp = call(LLMAskView, "post", "/llm_api/ask/", {
            "system_prompt": "You are a patent attorney.", "user_prompt": "Draft a claim for...",
            "temperature": 0.3, "max_tokens": 4096,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"], complete.return_value)
        complete.assert_called_once_with("You are a patent attorney.", "Draft a claim for...",
                                          temperature=0.3, max_tokens=4096)

    @mock.patch("apps.records.views.llm_complete")
    def test_chat_has_the_same_contract_as_ask_and_applies_defaults(self, complete):
        complete.return_value = {"content": "hi", "prompt_tokens": 1, "completion_tokens": 1, "generation_time": 0.1}
        resp = call(LLMChatView, "post", "/llm_api/chat/", {"user_prompt": "hello"})
        self.assertEqual(resp.status_code, 200)
        complete.assert_called_once_with("", "hello", temperature=0.3, max_tokens=1024)

    def test_missing_user_prompt_is_rejected(self):
        resp = call(LLMAskView, "post", "/llm_api/ask/", {"system_prompt": "x"})
        self.assertEqual(resp.status_code, 400)

    def test_malformed_temperature_is_rejected(self):
        resp = call(LLMAskView, "post", "/llm_api/ask/", {"user_prompt": "hi", "temperature": "not-a-number"})
        self.assertEqual(resp.status_code, 400)

    @mock.patch("apps.records.views.llm_complete", side_effect=services.LLMUnavailable("gpu server unreachable"))
    def test_llm_unavailable_returns_503_not_a_500_and_does_not_retry_the_other_mode(self, complete):
        resp = call(LLMAskView, "post", "/llm_api/ask/", {"user_prompt": "hi"})
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(complete.call_count, 1)


class StatusViewTests(TestCase):
    @mock.patch("apps.records.views.llm_status", return_value={"mode": "local", "reachable": True})
    def test_status_reachable(self, _status):
        resp = call(LLMStatusView, "get", "/llm_api/status/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"], {"mode": "local", "reachable": True})

    @mock.patch("apps.records.views.llm_status", return_value={"mode": "production", "reachable": False})
    def test_status_unavailable_is_still_a_200_reporting_unreachable(self, _status):
        resp = call(LLMStatusView, "get", "/llm_api/status/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["data"]["reachable"])
        self.assertNotIn("url", resp.data["data"])          # no server address/secrets exposed


class ProductionIntegrationTest(TestCase):
    """
    Real network test against LLM_PRODUCTION_URL — no mocks anywhere in this class.
    Skips (does not fail the suite) when the production GPU server isn't configured or isn't
    actually reachable from wherever this test runs; only asserts once it has genuinely reached it.
    """

    def test_real_production_ask(self):
        if not getattr(settings, "LLM_PRODUCTION_URL", ""):
            self.skipTest("Production integration test not executed because the production LLM "
                           "server was unavailable (LLM_PRODUCTION_URL is not configured).")
        with override_settings(LLM_MODE="production"):
            if not services.llm_status().get("reachable"):
                self.skipTest("Production integration test not executed because the production LLM "
                               "server was unavailable.")
            result = services.llm_complete("", "Reply with only the word OK.", temperature=0, max_tokens=5)
            self.assertTrue(result["content"])
