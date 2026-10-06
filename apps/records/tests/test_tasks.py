"""The pipeline: extraction, classification, retries, the batch counters, and what a person can do afterwards."""
from unittest import mock

from django.test import TestCase

from apps.records import classification as cls, services
from apps.records.models import DocumentBatch, DocumentText, MedicalDocument, PatientDocumentClassification
from apps.records.tasks import classify_document_task, extract_document_task
from apps.records.tests.helpers import PDF, identity, make_doc, reload

S = MedicalDocument.Status
RX = "Dr ABC Rx Paracetamol Syrup 5 ml TDS Diagnosis: Viral fever"


def row(doc):
    return MedicalDocument.objects.get(pk=doc.id)


def classification(doc):
    return PatientDocumentClassification.objects.get(document_id=doc.id)


@mock.patch("core.storage.get_bytes", return_value=PDF)
class ExtractDocumentTests(TestCase):
    """Stage 1: file → content check → text, then hand off to classification."""
    databases = {"default"}

    @mock.patch("apps.records.tasks.classify_document_task.delay")
    @mock.patch("apps.records.services.extract_text", return_value=("hemoglobin glucose", "pdf_text"))
    def test_success_saves_the_text_and_type_and_queues_classification(self, _extract, delay, _get):
        doc = make_doc(status=S.QUEUED)
        extract_document_task(doc.id)
        doc = row(doc)
        self.assertEqual((doc.status, doc.mime_type, doc.size), (S.CLASSIFYING, "application/pdf", len(PDF)))
        text = DocumentText.objects.get(document=doc)
        self.assertEqual((text.extracted_text, text.engine), ("hemoglobin glucose", "pdf_text"))
        delay.assert_called_once_with(doc.id)

    @mock.patch("apps.records.tasks.classify_document_task.delay")
    @mock.patch("apps.records.services.extract_text", return_value=("text", "ocr"))
    def test_the_file_is_read_through_the_file_field(self, _extract, _delay, get):
        doc = make_doc(status=S.QUEUED)
        extract_document_task(doc.id)
        get.assert_called_once_with("documents/AWP-T1/1/1.pdf")

    @mock.patch("apps.records.tasks.classify_document_task.delay")
    def test_a_file_that_is_not_a_pdf_or_image_fails_at_once_with_a_clear_reason(self, delay, get):
        get.return_value = b"just some text"
        doc = make_doc(status=S.QUEUED)
        extract_document_task(doc.id)                    # no exception: nothing to retry
        self.assertEqual(row(doc).status, S.FAILED)
        self.assertIn("not a valid", row(doc).error_message)
        delay.assert_not_called()

    @mock.patch("apps.records.tasks.classify_document_task.delay")
    def test_an_empty_file_fails_with_a_clear_reason(self, delay, get):
        get.return_value = b""
        doc = make_doc(status=S.QUEUED)
        extract_document_task(doc.id)
        self.assertEqual((row(doc).status, row(doc).error_message), (S.FAILED, "The file is empty."))
        delay.assert_not_called()

    @mock.patch("apps.records.tasks.classify_document_task.delay")
    def test_a_file_over_the_limit_fails(self, delay, _get):
        doc = make_doc(status=S.QUEUED)
        with mock.patch("apps.records.services.MAX_FILE_BYTES", 10):
            extract_document_task(doc.id)
        self.assertEqual((row(doc).status, row(doc).error_message), (S.FAILED, "The file is over 250 MB."))
        delay.assert_not_called()

    @mock.patch("apps.records.tasks.classify_document_task.delay")
    @mock.patch("apps.records.services.extract_text", side_effect=RuntimeError("OCR crashed"))
    def test_an_unexpected_error_is_raised_so_celery_retries_and_the_document_stays_in_progress(self, _extract, delay, _get):
        doc = make_doc(status=S.QUEUED)
        with self.assertRaises(RuntimeError):
            extract_document_task(doc.id)
        self.assertEqual(row(doc).status, S.EXTRACTING)
        delay.assert_not_called()

    @mock.patch("apps.records.tasks.classify_document_task.delay")
    @mock.patch("apps.records.services.extract_text", side_effect=RuntimeError("OCR crashed"))
    def test_when_the_retries_are_used_up_the_document_is_failed_for_the_patient_to_retry(self, _extract, delay, _get):
        doc = make_doc(status=S.QUEUED)
        extract_document_task.apply(args=(doc.id,), retries=extract_document_task.max_retries)   # the last attempt
        self.assertEqual(row(doc).status, S.FAILED)
        self.assertIn("OCR crashed", row(doc).error_message)
        delay.assert_not_called()

    @mock.patch("apps.records.tasks.classify_document_task.delay")
    @mock.patch("apps.records.services.extract_text")
    def test_only_a_document_still_in_the_pipeline_is_touched(self, extract, delay, get):
        for status in (S.COMPLETED, S.FAILED, S.REVIEW_REQUIRED):
            doc = make_doc(status=status)
            extract_document_task(doc.id)
            self.assertEqual(row(doc).status, status)
        extract.assert_not_called()
        get.assert_not_called()
        delay.assert_not_called()

    @mock.patch("apps.records.tasks.classify_document_task.delay")
    @mock.patch("apps.records.services.extract_text")
    def test_a_retry_after_the_text_was_saved_only_repeats_the_hand_off(self, extract, delay, get):
        doc = make_doc(status=S.CLASSIFYING, text="already read")
        extract_document_task(doc.id)
        get.assert_not_called()
        extract.assert_not_called()
        delay.assert_called_once_with(doc.id)

    @mock.patch("apps.records.tasks.classify_document_task.delay")
    @mock.patch("apps.records.services.extract_text", return_value=("text", "ocr"))
    def test_identical_files_are_both_kept(self, _extract, _delay, _get):
        """There is no duplicate detection any more: the same file twice is two documents."""
        a, b = make_doc(status=S.QUEUED), make_doc(status=S.QUEUED)
        extract_document_task(a.id)
        extract_document_task(b.id)
        self.assertEqual((row(a).status, row(b).status), (S.CLASSIFYING, S.CLASSIFYING))


class ClassifyDocumentTests(TestCase):
    """Stage 2: the rule engine on the extracted text."""
    databases = {"default"}

    def test_a_clear_verdict_completes_the_document_with_its_type(self):
        batch = DocumentBatch.objects.create(patient=identity(), total_files=1)
        doc = make_doc(status=S.CLASSIFYING, text=RX, batch=batch)
        classify_document_task(doc.id)
        doc = row(doc)
        self.assertEqual((doc.status, doc.document_type, doc.error_message), (S.COMPLETED, "prescription", ""))
        c = classification(doc)
        self.assertEqual((c.status, c.final_document_type, c.rule_score, c.second_best_score, c.score_margin),
                         ("rule_classified", "prescription", 21, 1, 20))
        batch.refresh_from_db()
        self.assertEqual((batch.processed_files, batch.failed_files, batch.status), (1, 0, "completed"))

    def test_text_the_rules_cannot_place_needs_review(self):
        batch = DocumentBatch.objects.create(patient=identity(), total_files=1)
        doc = make_doc(status=S.CLASSIFYING, text="hello world", batch=batch)
        classify_document_task(doc.id)
        doc = row(doc)
        self.assertEqual((doc.status, doc.document_type), (S.REVIEW_REQUIRED, "not_classified"))
        self.assertEqual(classification(doc).status, "review_required")
        batch.refresh_from_db()
        self.assertEqual((batch.processed_files, batch.status), (1, "completed"))     # finished, awaiting a person

    def test_a_document_with_no_text_needs_review(self):
        doc = make_doc(status=S.CLASSIFYING)
        classify_document_task(doc.id)
        self.assertEqual((row(doc).status, row(doc).document_type), (S.REVIEW_REQUIRED, "not_classified"))

    def test_a_persons_choice_is_not_overwritten_and_the_document_completes(self):
        doc = make_doc(status=S.CLASSIFYING, text=RX, document_type="lab_report", by="human")
        classify_document_task(doc.id)
        doc = row(doc)
        self.assertEqual((doc.status, doc.document_type), (S.COMPLETED, "lab_report"))
        self.assertEqual(classification(doc).status, "human_classified")

    def test_only_a_document_being_classified_is_touched(self):
        for status in (S.QUEUED, S.EXTRACTING, S.COMPLETED, S.FAILED, S.REVIEW_REQUIRED):
            doc = make_doc(status=status, text=RX)
            classify_document_task(doc.id)
            self.assertEqual(row(doc).status, status)
            self.assertFalse(PatientDocumentClassification.objects.filter(document=doc).exists())

    @mock.patch("apps.records.services.rules.classify_document_by_rules", side_effect=RuntimeError("boom"))
    def test_an_error_is_retried_and_fails_the_document_once_the_retries_are_used_up(self, _rules):
        doc = make_doc(status=S.CLASSIFYING, text=RX)
        with self.assertRaises(RuntimeError):
            classify_document_task(doc.id)
        self.assertEqual(row(doc).status, S.CLASSIFYING)
        classify_document_task.apply(args=(doc.id,), retries=classify_document_task.max_retries)   # the last attempt
        self.assertEqual(row(doc).status, S.FAILED)
        self.assertIn("boom", row(doc).error_message)


@mock.patch("core.storage.get_bytes", return_value=PDF)
class WholePipelineTests(TestCase):
    databases = {"default"}

    @mock.patch("apps.records.services.extract_text", return_value=(RX, "ocr"))
    def test_a_queued_document_ends_completed_with_its_text_and_classification(self, _extract, _get):
        batch = DocumentBatch.objects.create(patient=identity(), total_files=1)
        doc = make_doc(status=S.QUEUED, batch=batch)
        with mock.patch("apps.records.tasks.classify_document_task.delay",
                        side_effect=lambda pk: classify_document_task(pk)):
            extract_document_task(doc.id)
        doc = row(doc)
        self.assertEqual((doc.status, doc.document_type, cls.method_of(doc), cls.score_of(doc)), (S.COMPLETED, "prescription", "rule", 21))
        self.assertEqual(cls.text_of(doc), RX)
        batch.refresh_from_db()
        self.assertEqual((batch.processed_files, batch.status), (1, "completed"))


class StartProcessingTests(TestCase):
    databases = {"default"}

    @mock.patch("apps.records.tasks.extract_document_task.delay")
    def test_each_document_is_queued(self, delay):
        a, b = make_doc(), make_doc()
        services.start_processing([a.id, b.id])
        self.assertEqual([c.args for c in delay.call_args_list], [(a.id,), (b.id,)])

    @mock.patch("apps.records.tasks.extract_document_task.delay", side_effect=ConnectionError("broker down"))
    def test_when_the_queue_is_unreachable_the_documents_fail_so_the_patient_can_retry(self, _delay):
        batch = DocumentBatch.objects.create(patient=identity(), total_files=1)
        doc = make_doc(batch=batch)
        services.start_processing([doc.id])
        self.assertEqual(row(doc).status, S.FAILED)
        self.assertIn("Couldn't start processing", row(doc).error_message)
        batch.refresh_from_db()
        self.assertEqual((batch.failed_files, batch.status), (1, "completed_with_errors"))


class CorrectionTests(TestCase):
    databases = {"default"}

    def test_a_person_files_a_document_that_needs_review(self):
        doc = make_doc(status=S.REVIEW_REQUIRED, by="rules")
        services.correct_document(doc, "lab_report")
        doc = row(doc)
        self.assertEqual((doc.status, doc.document_type, cls.method_of(doc)), (S.COMPLETED, "lab_report", "staff"))
        c = classification(doc)
        self.assertEqual((c.human_document_type, c.final_document_type, c.status), ("lab_report", "lab_report", "human_classified"))

    def test_a_person_can_change_the_type_the_rules_chose(self):
        doc = make_doc(status=S.COMPLETED, document_type="lab_report", by="rules")
        services.correct_document(doc, "prescription")
        self.assertEqual((row(doc).document_type, classification(doc).final_document_type), ("prescription", "prescription"))

    def test_a_failed_file_becomes_a_normal_completed_one(self):
        doc = make_doc(status=S.FAILED, error_message="unreadable")
        services.correct_document(doc, "other")
        self.assertEqual((row(doc).status, row(doc).error_message, row(doc).document_type), (S.COMPLETED, "", "other"))

    def test_a_file_still_being_read_cannot_be_filed(self):
        for status in (S.QUEUED, S.EXTRACTING, S.CLASSIFYING):
            with self.assertRaises(ValueError):
                services.correct_document(make_doc(status=status), "lab_report")

    def test_only_a_real_type_can_be_chosen(self):
        doc = make_doc(status=S.COMPLETED)
        for bad in ("made_up", "not_classified", "LAB_REPORT"):
            with self.assertRaises(ValueError):
                services.correct_document(doc, bad)

    def test_only_a_failed_file_can_be_retried(self):
        doc = make_doc(status=S.FAILED, error_message="boom")
        services.retry_document(doc)
        self.assertEqual((row(doc).status, row(doc).error_message), (S.QUEUED, ""))
        for status in (S.QUEUED, S.COMPLETED, S.REVIEW_REQUIRED, S.CLASSIFYING):
            with self.assertRaises(ValueError):
                services.retry_document(make_doc(status=status))


class ReclassifyTests(TestCase):
    databases = {"default"}

    def test_the_rules_run_again_over_what_the_rules_classified(self):
        doc = make_doc(status=S.REVIEW_REQUIRED, by="rules", text=RX)
        counts = services.reclassify_existing()
        self.assertEqual(counts, {"checked": 1, "changed": 1, "classified": 1, "unclassified": 0})
        self.assertEqual((row(doc).status, row(doc).document_type), (S.COMPLETED, "prescription"))

    def test_a_document_the_rules_now_cannot_place_goes_back_to_review(self):
        doc = make_doc(status=S.COMPLETED, document_type="prescription", by="rules", text="hello world")
        services.reclassify_existing()
        self.assertEqual((row(doc).status, row(doc).document_type), (S.REVIEW_REQUIRED, "not_classified"))

    def test_a_persons_choice_and_a_hospital_document_are_never_touched(self):
        human = make_doc(status=S.COMPLETED, document_type="lab_report", by="human", text=RX)
        issued = make_doc(status=S.COMPLETED, document_type="lab_report", by="issued", text=RX, source_tenant_id="3")
        self.assertEqual(services.reclassify_existing()["checked"], 0)
        self.assertEqual((row(human).document_type, row(issued).document_type), ("lab_report", "lab_report"))

    def test_a_document_without_text_is_skipped(self):
        make_doc(status=S.REVIEW_REQUIRED, by="rules")
        self.assertEqual(services.reclassify_existing()["checked"], 0)


class BatchCounterTests(TestCase):
    databases = {"default"}

    def test_the_batch_counts_follow_its_documents(self):
        batch = DocumentBatch.objects.create(patient=identity(), total_files=4)
        make_doc(batch=batch, status=S.COMPLETED, document_type="lab_report", by="rules")
        make_doc(batch=batch, status=S.REVIEW_REQUIRED, by="rules")
        make_doc(batch=batch, status=S.CLASSIFYING)
        make_doc(batch=batch, status=S.FAILED)
        batch.refresh()
        self.assertEqual((batch.processed_files, batch.failed_files, batch.status), (2, 1, "processing"))
        MedicalDocument.objects.filter(batch=batch, status=S.CLASSIFYING).update(status=S.COMPLETED)
        batch.refresh()
        self.assertEqual((batch.processed_files, batch.status), (3, "completed_with_errors"))
