from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.records.models import DocumentClassification, MedicalDocument, SweepConfig
from apps.records.tests.helpers import make_doc
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
        self.assertEqual(resp.data["data"], {"instant_max_files": 50, "sweep_dispatch_limit": 10,
                                              "sweep_interval_seconds": 30, "min_confidence": 50, "evidence_scale": 10})

    def test_patch_updates_and_persists(self):
        call(SweepConfigView, "patch", {"instant_max_files": 8, "sweep_dispatch_limit": 20})
        self.assertEqual((SweepConfig.current().instant_max_files, SweepConfig.current().sweep_dispatch_limit), (8, 20))

    def test_patch_updates_the_interval_live_no_restart_needed(self):
        from django_celery_beat.models import PeriodicTask
        resp = call(SweepConfigView, "patch", {"sweep_interval_seconds": 120})
        self.assertEqual(resp.data["data"]["sweep_interval_seconds"], 120)
        self.assertEqual(PeriodicTask.objects.get(name=SweepConfig.TASK_NAME).interval.every, 120)

    def test_patch_sets_how_a_verdict_is_judged_within_limits(self):
        call(SweepConfigView, "patch", {"min_confidence": 70, "evidence_scale": 8})
        self.assertEqual((SweepConfig.current().min_confidence, SweepConfig.current().evidence_scale), (70, 8))
        self.assertEqual(call(SweepConfigView, "patch", {"min_confidence": 101}).status_code, 400)
        self.assertEqual(call(SweepConfigView, "patch", {"min_confidence": 0}).status_code, 400)

    def test_patch_rejects_a_non_positive_value(self):
        resp = call(SweepConfigView, "patch", {"instant_max_files": 0})
        self.assertEqual(resp.status_code, 400)


class DocumentReportViewTests(TestCase):
    databases = {"default"}

    def test_lists_documents_filtered_by_method_and_status(self):
        make_doc(status="completed", doc_type="lab_report", by="system", name="a.pdf")
        make_doc(status="completed", doc_type="lab_report", by="human", name="b.pdf")
        make_doc(status="failed", name="c.pdf")
        resp = call(DocumentReportView, "get")
        self.assertEqual(resp.data["data"]["pagination"]["total_count"], 3)

        def rows(**params):
            request = APIRequestFactory().get("/x", params)
            force_authenticate(request, user=MockUser({"user_id": 1, "role": "platform_admin"}))
            return DocumentReportView.as_view()(request).data["data"]["results"]

        self.assertEqual([r["method"] for r in rows(method="rule")], ["rule"])
        self.assertEqual([r["method"] for r in rows(method="staff")], ["staff"])
        self.assertEqual([r["processing_status"] for r in rows(status="failed")], ["failed"])


class DocumentCorrectViewTests(TestCase):
    databases = {"default"}

    def test_correcting_a_document_sets_type_and_marks_it_human(self):
        doc = make_doc(status="completed", doc_type="lab_report", by="system")
        resp = call(DocumentCorrectView, "patch", {"doc_type": "prescription"}, pk=doc.id)
        self.assertEqual(resp.status_code, 200)
        doc = MedicalDocument.objects.get(pk=doc.pk)
        self.assertEqual((doc.doc_type, doc.classification_source), ("prescription", "human"))
        self.assertEqual(resp.data["data"]["method"], "staff")

    def test_rejects_an_unknown_doc_type(self):
        doc = make_doc()
        self.assertEqual(call(DocumentCorrectView, "patch", {"doc_type": "not_a_real_type"}, pk=doc.id).status_code, 400)

    def test_a_type_added_as_a_rule_is_accepted(self):
        DocumentClassification.objects.create(code="x_ray_report", name="X-Ray report", keywords="x-ray")
        doc = make_doc()
        self.assertEqual(call(DocumentCorrectView, "patch", {"doc_type": "x_ray_report"}, pk=doc.id).status_code, 200)

    def test_correcting_a_failed_document_completes_it(self):
        doc = make_doc(status="failed", error="unreadable")
        call(DocumentCorrectView, "patch", {"doc_type": "lab_report"}, pk=doc.id)
        doc = MedicalDocument.objects.get(pk=doc.pk)
        self.assertEqual((doc.status, doc.error), ("completed", ""))

    def test_a_rejected_duplicate_cannot_be_corrected(self):
        doc = make_doc(status="rejected")
        self.assertEqual(call(DocumentCorrectView, "patch", {"doc_type": "lab_report"}, pk=doc.id).status_code, 400)


class SweepIntervalMigrationTests(TestCase):
    databases = {"default"}

    def migrate(self):
        import importlib
        from django.apps import apps
        importlib.import_module("apps.records.migrations.0014_sweep_interval_30_seconds").back_to_30_seconds(apps, None)

    def beat_every(self):
        from django_celery_beat.models import PeriodicTask
        return PeriodicTask.objects.get(name=SweepConfig.TASK_NAME).interval.every

    def test_the_default_is_30_seconds(self):
        self.assertEqual(SweepConfig.current().sweep_interval_seconds, 30)
        self.assertEqual(self.beat_every(), 30)

    def test_a_setting_left_at_the_60_minute_default_moves_back_to_30_seconds(self):
        cfg = SweepConfig.current()
        cfg.sweep_interval_seconds = 3600
        cfg.save()
        self.migrate()
        self.assertEqual((SweepConfig.current().sweep_interval_seconds, self.beat_every()), (30, 30))

    def test_a_value_an_admin_chose_is_left_alone(self):
        cfg = SweepConfig.current()
        cfg.sweep_interval_seconds = 900
        cfg.save()
        self.migrate()
        self.assertEqual((SweepConfig.current().sweep_interval_seconds, self.beat_every()), (900, 900))

    def test_instant_dispatch_covers_a_full_upload_by_default(self):
        import importlib
        from django.apps import apps
        self.assertEqual(SweepConfig.current().instant_max_files, 50)
        SweepConfig.objects.filter(pk=1).update(instant_max_files=5)
        importlib.import_module("apps.records.migrations.0013_instant_max_files_50").raise_to_50(apps, None)
        self.assertEqual(SweepConfig.current().instant_max_files, 50)
        SweepConfig.objects.filter(pk=1).update(instant_max_files=8)           # an admin's own value stays
        importlib.import_module("apps.records.migrations.0013_instant_max_files_50").raise_to_50(apps, None)
        self.assertEqual(SweepConfig.current().instant_max_files, 8)


class ReclassifyViewTests(TestCase):
    databases = {"default"}

    def test_reclassify_runs_the_rules_again(self):
        from apps.platform_admin.classification_rule_views import ReclassifyView
        make_doc(status="completed", doc_type=None, by="system",
                 data={"extracted_text": "City laboratory. Hemoglobin, glucose, cholesterol, reference range."})
        resp = call(ReclassifyView, "post")
        self.assertEqual(resp.data["data"], {"checked": 1, "changed": 1, "classified": 1, "unclassified": 0})
