"""core/tests/tests_pagination.py — a list is paged only when the caller asks for a page."""
from django.test import SimpleTestCase
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from core.api.pagination import page_payload


def ask(query=""):
    return Request(APIRequestFactory().get("/x/" + query))


class PagePayloadTests(SimpleTestCase):
    def test_a_caller_that_does_not_ask_for_a_page_gets_nothing_to_page(self):
        self.assertIsNone(page_payload(ask(), list(range(5))))

    def test_one_page_comes_back_with_its_pagination_block(self):
        payload = page_payload(ask("?page=2&page_size=2"), list(range(5)))
        self.assertEqual(payload["results"], [2, 3])
        self.assertEqual(payload["pagination"], {"page": 2, "page_size": 2, "total_count": 5, "total_pages": 3, "has_next": True, "has_previous": True})

    def test_a_page_past_the_end_falls_back_to_the_last_page_and_the_rows_are_serialized(self):
        payload = page_payload(ask("?page=9&page_size=2"), list(range(5)), serialize=lambda rows: [{"n": r} for r in rows])
        self.assertEqual(payload["results"], [{"n": 4}])
        self.assertEqual(payload["pagination"]["page"], 3)

    def test_an_empty_list_is_one_empty_page(self):
        payload = page_payload(ask("?page=1"), [])
        self.assertEqual((payload["results"], payload["pagination"]["total_pages"], payload["pagination"]["has_next"]), ([], 1, False))
