from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.records.models import SharedDocument, SweepConfig
from apps.platform_admin.classification_rule_views import (
    DocumentCorrectView, DocumentReportView, SweepConfigView,
)
from core.authentication import MockUser


def call(view, method, data=None, **kwargs):
    request = getattr(APIRequestFactory(), method)("/x", data or {}, format="json")
    force_authenticate(request, user=MockUser({"user_id": 1, "role": "platform_admin"}))
    return view.as_view()(request, **kwargs)


class SweepConfigViewTests(TestCase):
    databases = {"default"}

    def test_get_returns_defaults_on_first_call(self):
        resp = call(SweepConfigView, "get")
        self.assertEqual(resp.data["data"], {"instant_max_files": 5, "sweep_dispatch_limit": 10,
                                              "sweep_interval_seconds": 30})

    def test_patch_updates_and_persists(self):
        call(SweepConfigView, "patch", {"instant_max_files": 8, "sweep_dispatch_limit": 20})
        self.assertEqual((SweepConfig.current().instant_max_files, SweepConfig.current().sweep_dispatch_limit), (8, 20))

    def test_patch_updates_the_interval_live_no_restart_needed(self):
        from django_celery_beat.models import PeriodicTask
        resp = call(SweepConfigView, "patch", {"sweep_interval_seconds": 60})
        self.assertEqual(resp.data["data"]["sweep_interval_seconds"], 60)
        self.assertEqual(PeriodicTask.objects.get(name=SweepConfig.TASK_NAME).interval.every, 60)

    def test_patch_rejects_a_non_positive_value(self):
        resp = call(SweepConfigView, "patch", {"instant_max_files": 0})
        self.assertEqual(resp.status_code, 400)


class DocumentReportViewTests(TestCase):
    databases = {"default"}

    def test_lists_documents_filtered_by_method(self):
        SharedDocument.objects.create(awpid="AWP-1", title="a", s3_key="k1", method="rule", score=90)
        SharedDocument.objects.create(awpid="AWP-1", title="b", s3_key="k2", method="llm", score=60)
        resp = call(DocumentReportView, "get")
        self.assertEqual(resp.data["data"]["pagination"]["total_count"], 2)

        request = APIRequestFactory().get("/x", {"method": "rule"})
        force_authenticate(request, user=MockUser({"user_id": 1, "role": "platform_admin"}))
        resp = DocumentReportView.as_view()(request)
        rows = resp.data["data"]["results"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["method"], "rule")


class DocumentCorrectViewTests(TestCase):
    databases = {"default"}

    def test_correcting_a_document_sets_type_and_marks_it_staff(self):
        doc = SharedDocument.objects.create(awpid="AWP-1", title="a", s3_key="k1",
                                             doc_type="other", method="llm", score=40)
        resp = call(DocumentCorrectView, "patch", {"doc_type": "prescription"}, pk=doc.id)
        self.assertEqual(resp.status_code, 200)
        doc.refresh_from_db()
        self.assertEqual((doc.doc_type, doc.method), ("prescription", "staff"))

    def test_rejects_an_unknown_doc_type(self):
        doc = SharedDocument.objects.create(awpid="AWP-1", title="a", s3_key="k1")
        resp = call(DocumentCorrectView, "patch", {"doc_type": "not_a_real_type"}, pk=doc.id)
        self.assertEqual(resp.status_code, 400)
