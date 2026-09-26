from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.records.models import SharedDocument, SweepConfig
from apps.records.tasks import classify_document_task, extract_document_task, recover_stuck_documents


def make_doc(**kw):
    return SharedDocument.objects.create(awpid="AWP-T1", title="doc", s3_key="k/1.pdf",
                                         mime_type="application/pdf", processing_status="queued", **kw)


@mock.patch("apps.records.services.storage.get_bytes", return_value=b"%PDF")
class ExtractDocumentTaskTests(TestCase):
    """Stage 1: text out, then hand off to classify_document_task — never classify inline."""
    databases = {"default"}

    @mock.patch("apps.records.tasks.classify_document_task.delay")
    @mock.patch("apps.records.services.extract_text", return_value="hemoglobin glucose")
    def test_success_saves_text_and_dispatches_classification(self, _extract, dispatch, _get):
        doc = make_doc()
        extract_document_task(doc.id)
        doc.refresh_from_db()
        self.assertEqual(doc.processing_status, "classifying")
        self.assertIn("hemoglobin", doc.extracted_text)
        dispatch.assert_called_once_with(doc.id)

    @mock.patch("apps.records.tasks.classify_document_task.delay")
    @mock.patch("apps.records.services.extract_text", side_effect=RuntimeError("OCR crashed"))
    def test_failure_saves_status_and_error_and_never_dispatches(self, _extract, dispatch, _get):
        doc = make_doc()
        extract_document_task(doc.id)
        doc.refresh_from_db()
        self.assertEqual(doc.processing_status, "failed")
        self.assertIn("OCR crashed", doc.error)
        dispatch.assert_not_called()

    @mock.patch("apps.records.tasks.classify_document_task.delay")
    @mock.patch("apps.records.services.extract_text", return_value="text")
    def test_a_document_already_past_extraction_is_left_untouched(self, extract, dispatch, _get):
        """A duplicate/redelivered dispatch for a document already extracted (or further along)
        must be a no-op — this is exactly the race two independently-queued stages must guard against."""
        doc = make_doc()
        SharedDocument.objects.filter(id=doc.id).update(processing_status="classifying")
        extract_document_task(doc.id)
        extract.assert_not_called()
        dispatch.assert_not_called()

    @mock.patch("apps.records.tasks.classify_document_task.delay")
    @mock.patch("apps.records.services.extract_text", return_value="hemoglobin")
    def test_a_genuinely_stuck_extraction_is_still_recoverable(self, extract, dispatch, _get):
        doc = make_doc()
        SharedDocument.objects.filter(id=doc.id).update(processing_status="ocr")
        extract_document_task(doc.id)                      # "ocr" is a valid start state, not just "queued"
        doc.refresh_from_db()
        self.assertEqual(doc.processing_status, "classifying")
        dispatch.assert_called_once()


class ClassifyDocumentTaskTests(TestCase):
    """Stage 2: rules/LLM on already-extracted text — never re-runs extraction."""
    databases = {"default"}

    def classifying_doc(self):
        doc = make_doc()
        SharedDocument.objects.filter(id=doc.id).update(
            processing_status="classifying",
            extracted_text="laboratory hemoglobin glucose cholesterol reference range")
        doc.refresh_from_db()
        return doc

    def test_success_saves_type_score_method_and_status(self):
        doc = self.classifying_doc()
        classify_document_task(doc.id)
        doc.refresh_from_db()
        self.assertEqual((doc.processing_status, doc.doc_type, doc.score, doc.method),
                         ("completed", "lab_report", 100.0, "rule"))
        self.assertEqual(doc.error, "")

    @mock.patch("apps.records.services.classify", side_effect=RuntimeError("LLM down"))
    def test_failure_saves_status_and_error(self, _classify):
        doc = self.classifying_doc()
        classify_document_task(doc.id)
        doc.refresh_from_db()
        self.assertEqual(doc.processing_status, "failed")
        self.assertIn("LLM down", doc.error)

    def test_a_document_not_yet_extracted_is_left_untouched(self):
        """A document still "queued"/"ocr" has no text yet — classification must not run early."""
        doc = make_doc()
        with mock.patch("apps.records.services.classify") as classify:
            classify_document_task(doc.id)
            classify.assert_not_called()


class SweepConfigScheduleSyncTests(TestCase):
    """SweepConfig.save() is the one place that keeps Beat's actual schedule in sync — no restart,
    no env var, for any of the three settings (this is what makes the interval live-editable)."""
    databases = {"default"}

    def test_saving_creates_a_periodic_task_at_the_configured_interval(self):
        from django_celery_beat.models import PeriodicTask
        SweepConfig.current()                                    # first access: provisions the row
        pt = PeriodicTask.objects.get(name=SweepConfig.TASK_NAME)
        self.assertEqual((pt.task, pt.enabled, pt.interval.every), ("apps.records.tasks.recover_stuck_documents", True, 30))

    def test_changing_the_interval_updates_the_same_periodic_task_live(self):
        from django_celery_beat.models import PeriodicTask
        c = SweepConfig.current()
        c.sweep_interval_seconds = 45
        c.save()
        pt = PeriodicTask.objects.get(name=SweepConfig.TASK_NAME)  # same row, not a duplicate
        self.assertEqual(pt.interval.every, 45)
        self.assertEqual(PeriodicTask.objects.filter(name=SweepConfig.TASK_NAME).count(), 1)


@mock.patch("apps.records.tasks.classify_document_task.delay")
@mock.patch("apps.records.tasks.extract_document_task.delay")
class RecoverStuckDocumentsTests(TestCase):
    """Routes each candidate to whichever stage's task matches where it currently is."""
    databases = {"default"}

    def test_sends_freshly_queued_documents_to_extraction_without_waiting(self, extract_delay, classify_delay):
        """A bulk batch deferred at intake (still "queued", created moments ago) must be picked up
        right away — that's what lets a batch over SweepConfig.instant_max_files actually drain."""
        fresh = make_doc()                                                     # queued, created just now
        self.assertEqual(recover_stuck_documents(), 1)
        extract_delay.assert_called_once_with(fresh.id)
        classify_delay.assert_not_called()

    def test_routes_stuck_documents_to_the_stage_they_were_in(self, extract_delay, classify_delay):
        old = timezone.now() - timedelta(minutes=6)
        stuck_extract = make_doc()
        SharedDocument.objects.filter(id=stuck_extract.id).update(processing_status="ocr", updated_at=old)
        stuck_classify = make_doc()
        SharedDocument.objects.filter(id=stuck_classify.id).update(processing_status="classifying", updated_at=old)
        active = make_doc()                                                    # claimed moments ago
        SharedDocument.objects.filter(id=active.id).update(processing_status="ocr")
        done = make_doc()
        SharedDocument.objects.filter(id=done.id).update(processing_status="completed", updated_at=old)

        self.assertEqual(recover_stuck_documents(), 2)
        extract_delay.assert_called_once_with(stuck_extract.id)
        classify_delay.assert_called_once_with(stuck_classify.id)
        self.assertNotIn(active.id, [c.args[0] for c in extract_delay.call_args_list])  # not stale: still in progress

        extract_delay.reset_mock(); classify_delay.reset_mock()
        self.assertEqual(recover_stuck_documents(), 0)                          # not re-sent every run

    def test_respects_the_dispatch_limit(self, extract_delay, classify_delay):
        """A big bulk batch drains SweepConfig.sweep_dispatch_limit at a time, oldest first — not all at once."""
        SweepConfig.objects.update_or_create(pk=1, defaults={"sweep_dispatch_limit": 3})
        docs = [make_doc() for _ in range(5)]
        self.assertEqual(recover_stuck_documents(), 3)
        self.assertEqual(sorted(c.args[0] for c in extract_delay.call_args_list), sorted(d.id for d in docs[:3]))
