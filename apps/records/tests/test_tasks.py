import hashlib
from datetime import timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from apps.records import services
from apps.records.models import MedicalDocument, SweepConfig
from apps.records.tasks import (
    classify_document_task, dispatch_documents, extract_document_task, recover_stuck_documents,
)
from apps.records.tests.helpers import PDF, make_doc, reload

S = MedicalDocument.Status
PDF_HASH = hashlib.sha256(PDF).hexdigest()


def row(doc):
    return MedicalDocument.objects.get(pk=doc.id)


@mock.patch("apps.records.services.storage.get_bytes", return_value=PDF)
class ExtractDocumentTests(TestCase):
    """Stage 1: one read (content check + hash), duplicate check, text, then hand off to classification."""
    databases = {"default"}

    @mock.patch("apps.records.tasks.classify_document_task.delay")
    @mock.patch("apps.records.services.extract_text", return_value="hemoglobin glucose")
    def test_success_saves_text_type_and_hash_and_dispatches_classification(self, _extract, dispatch, _get):
        doc = make_doc(status=S.EXTRACTING)
        extract_document_task(doc.id)
        doc = reload(doc)
        self.assertEqual((row(doc).status, doc.mime_type, doc.content_hash, doc.size),
                         (S.CLASSIFYING, "application/pdf", PDF_HASH, len(PDF)))
        self.assertEqual(row(doc).classification_details["extracted_text"], "hemoglobin glucose")
        dispatch.assert_called_once_with(doc.id)

    @mock.patch("apps.records.tasks.classify_document_task.delay")
    def test_a_file_that_is_not_a_pdf_or_image_fails_with_a_clear_reason(self, dispatch, get):
        get.return_value = b"just some text"
        doc = make_doc(status=S.EXTRACTING)
        extract_document_task(doc.id)
        self.assertEqual(row(doc).status, S.FAILED)
        self.assertIn("not a valid", row(doc).error)
        dispatch.assert_not_called()

    @mock.patch("apps.records.tasks.classify_document_task.delay")
    def test_an_empty_file_fails_with_a_clear_reason(self, dispatch, get):
        get.return_value = b""
        doc = make_doc(status=S.EXTRACTING)
        extract_document_task(doc.id)
        self.assertEqual((row(doc).status, row(doc).error), (S.FAILED, "The file is empty."))
        dispatch.assert_not_called()

    @mock.patch("apps.records.tasks.classify_document_task.delay")
    @mock.patch("apps.records.services.extract_text", side_effect=RuntimeError("OCR crashed"))
    def test_an_extraction_error_fails_the_document_and_never_dispatches(self, _extract, dispatch, _get):
        doc = make_doc(status=S.EXTRACTING)
        extract_document_task(doc.id)
        self.assertEqual(row(doc).status, S.FAILED)
        self.assertIn("OCR crashed", row(doc).error)
        dispatch.assert_not_called()

    @mock.patch("apps.records.tasks.classify_document_task.delay")
    @mock.patch("apps.records.services.extract_text")
    def test_only_a_document_being_extracted_is_touched(self, extract, dispatch, _get):
        for status in (S.QUEUED, S.CLASSIFYING, S.COMPLETED, S.FAILED, S.REJECTED):
            extract_document_task(make_doc(status=status).id)
        extract.assert_not_called()
        dispatch.assert_not_called()


@mock.patch("apps.records.services.storage.get_bytes", return_value=PDF)
@mock.patch("apps.records.tasks.classify_document_task.delay")
@mock.patch("apps.records.services.extract_text", return_value="text")
class DuplicateTests(TestCase):
    """A file the patient already has is rejected before any OCR is spent on it."""
    databases = {"default"}

    def test_the_same_file_again_is_rejected_without_ocr(self, extract, dispatch, _get):
        first = make_doc(status=S.COMPLETED, content_hash=PDF_HASH, name="first.pdf")
        second = make_doc(status=S.EXTRACTING, name="second.pdf")
        extract_document_task(second.id)
        self.assertEqual(row(second).status, S.REJECTED)
        self.assertIn("Same as first.pdf", row(second).error)
        extract.assert_not_called()
        dispatch.assert_not_called()
        self.assertEqual(row(first).status, S.COMPLETED)

    def test_a_rejected_duplicate_remembers_which_document_it_is_the_same_as(self, extract, dispatch, _get):
        first = make_doc(status=S.COMPLETED, content_hash=PDF_HASH)
        second = make_doc(status=S.EXTRACTING)
        extract_document_task(second.id)
        self.assertEqual(reload(second).duplicate_of, first.id)

    def test_a_duplicate_the_patient_chose_to_keep_goes_through(self, extract, dispatch, _get):
        make_doc(status=S.COMPLETED, content_hash=PDF_HASH)
        kept = make_doc(status=S.EXTRACTING, data={"keep_duplicate": True})
        extract_document_task(kept.id)
        self.assertEqual(row(kept).status, S.CLASSIFYING)

    def test_another_patient_having_the_same_file_is_not_a_duplicate(self, extract, dispatch, _get):
        make_doc("AWP-OTHER", status=S.COMPLETED, content_hash=PDF_HASH)
        mine = make_doc(status=S.EXTRACTING)
        extract_document_task(mine.id)
        self.assertEqual(row(mine).status, S.CLASSIFYING)

    def test_a_deleted_or_failed_original_does_not_count(self, extract, dispatch, _get):
        make_doc(status=S.COMPLETED, content_hash=PDF_HASH, deleted_at=timezone.now())
        make_doc(status=S.FAILED, content_hash=PDF_HASH)
        mine = make_doc(status=S.EXTRACTING)
        extract_document_task(mine.id)
        self.assertEqual(row(mine).status, S.CLASSIFYING)

    def test_an_earlier_upload_is_never_rejected_because_of_a_later_one(self, extract, dispatch, _get):
        earlier = make_doc(status=S.COMPLETED, content_hash=PDF_HASH)
        make_doc(status=S.COMPLETED, content_hash=PDF_HASH)
        self.assertIsNone(services._duplicate_of(reload(earlier)))

    def test_the_last_guard_in_classification_catches_a_twin_that_raced_through(self, extract, dispatch, _get):
        make_doc(status=S.COMPLETED, content_hash=PDF_HASH, name="first.pdf")
        raced = make_doc(status=S.CLASSIFYING, content_hash=PDF_HASH, data={"extracted_text": "x"})
        classify_document_task(raced.id)
        self.assertEqual(row(raced).status, S.REJECTED)


class ClassifyDocumentTests(TestCase):
    """Stage 2: keyword rules on the already-extracted text — never re-runs extraction."""
    databases = {"default"}

    def classifying_doc(self, text="laboratory hemoglobin glucose cholesterol reference range", **kw):
        return make_doc(status=S.CLASSIFYING, data={"extracted_text": text}, **kw)

    def test_success_saves_type_who_score_and_status(self):
        doc = self.classifying_doc()
        classify_document_task(doc.id)
        doc = reload(doc)
        self.assertEqual((doc.processing_status, doc.doc_type, row(doc).classification_source, doc.method),
                         (S.COMPLETED, "lab_report", "system", "rule"))
        self.assertGreaterEqual(doc.score, 60)
        self.assertEqual(row(doc).classification_details["extracted_text"][:10], "laboratory")        # the text is kept
        self.assertEqual(doc.error, "")

    def test_a_document_no_configured_type_fits_is_completed_without_a_type_not_failed(self):
        doc = self.classifying_doc(text="nothing recognisable here")
        classify_document_task(doc.id)
        doc = reload(doc)
        self.assertEqual((doc.processing_status, doc.doc_type, doc.classification_id), (S.COMPLETED, "", None))
        self.assertIn("Unable to classify", row(doc).classification_details["note"])

    def test_the_verdict_keeps_what_it_was_based_on(self):
        doc = self.classifying_doc()
        classify_document_task(doc.id)
        data = row(doc).classification_details
        self.assertEqual((data["best_guess"], data["method"], data["evidence"]), ("lab_report", "rule", 5.0))
        self.assertIn("glucose", data["matched"])

    def test_a_persons_verdict_is_never_overwritten(self):
        doc = self.classifying_doc(doc_type="scan", by="human")
        classify_document_task(doc.id)
        doc = reload(doc)
        self.assertEqual((doc.processing_status, doc.doc_type, row(doc).classification_source), (S.COMPLETED, "scan", "human"))

    @mock.patch("apps.records.services.classify", side_effect=RuntimeError("rules broke"))
    def test_failure_saves_status_and_error(self, _classify):
        doc = self.classifying_doc()
        classify_document_task(doc.id)
        self.assertEqual(row(doc).status, S.FAILED)
        self.assertIn("rules broke", row(doc).error)

    def test_only_a_document_being_classified_is_touched(self):
        doc = make_doc(status=S.EXTRACTING)
        classify_document_task(doc.id)
        self.assertEqual(row(doc).status, S.EXTRACTING)


class HumanCorrectionTests(TestCase):
    databases = {"default"}

    def test_correcting_a_failed_document_completes_it(self):
        doc = make_doc(status=S.FAILED)
        MedicalDocument.objects.filter(pk=doc.pk).update(error="could not read it")
        services.correct_document(reload(doc), "prescription")
        doc = reload(doc)
        self.assertEqual((doc.processing_status, doc.doc_type, row(doc).classification_source, doc.error),
                         (S.COMPLETED, "prescription", "human", ""))

    def test_a_correction_replaces_the_classification_and_only_one_is_kept(self):
        doc = make_doc(status=S.COMPLETED, doc_type="lab_report", by="system", score=71.5,
                       data={"extracted_text": "t", "method": "rule", "matched": ["glucose"], "best_guess": "lab_report"})
        services.correct_document(reload(doc), "prescription")
        doc = reload(doc)
        self.assertEqual((doc.doc_type, doc.classification_source, doc.score), ("prescription", "human", None))
        self.assertEqual(doc.classification_details, {"extracted_text": "t", "method": "human"})   # no trace of the rules' verdict
        services.correct_document(doc, "scan")                                                      # overwriting again just replaces it
        self.assertEqual((reload(doc).doc_type, reload(doc).classification_source), ("scan", "human"))

    def test_a_rejected_duplicate_stays_rejected(self):
        doc = make_doc(status=S.REJECTED)
        with self.assertRaises(ValueError):
            services.correct_document(reload(doc), "scan")
        self.assertEqual(row(doc).status, S.REJECTED)


class ClaimDocumentsTests(TestCase):
    """The dispatcher: queued and abandoned documents are claimed once, and never forever."""
    databases = {"default"}

    def test_a_queued_document_is_claimed_for_extraction(self):
        doc = make_doc()
        self.assertEqual(services.claim_documents(10), [(doc.id, "extract")])
        self.assertEqual((row(doc).status, row(doc).attempts), (S.EXTRACTING, 1))
        self.assertIsNotNone(row(doc).claimed_at)

    def test_a_claimed_document_is_not_claimed_again_while_its_claim_is_fresh(self):
        make_doc()
        services.claim_documents(10)
        self.assertEqual(services.claim_documents(10), [])

    def test_an_abandoned_document_is_re_sent_to_the_stage_it_was_in(self):
        old = timezone.now() - timedelta(minutes=services.STUCK_MINUTES + 1)
        extracting, classifying = make_doc(status=S.EXTRACTING), make_doc(status=S.CLASSIFYING)
        MedicalDocument.objects.update(claimed_at=old, attempts=1)
        self.assertCountEqual(services.claim_documents(10),
                              [(extracting.id, "extract"), (classifying.id, "classify")])

    def test_an_in_progress_document_that_was_never_claimed_is_picked_up(self):
        doc = make_doc(status=S.CLASSIFYING)
        self.assertEqual(services.claim_documents(10), [(doc.id, "classify")])

    def test_a_document_that_keeps_dying_is_failed_after_max_attempts(self):
        old = timezone.now() - timedelta(minutes=services.STUCK_MINUTES + 1)
        doc = make_doc(status=S.EXTRACTING)
        MedicalDocument.objects.update(claimed_at=old, attempts=services.MAX_ATTEMPTS)
        self.assertEqual(services.claim_documents(10), [])
        self.assertEqual(row(doc).status, S.FAILED)
        self.assertIn("attempts", row(doc).error)

    def test_limit_and_ids_are_respected_oldest_first(self):
        first, second, third = make_doc(), make_doc(), make_doc()
        self.assertEqual(services.claim_documents(1), [(first.id, "extract")])
        self.assertEqual(services.claim_documents(10, ids=[third.id]), [(third.id, "extract")])
        self.assertEqual(row(second).status, S.QUEUED)

    def test_finished_documents_are_never_claimed(self):
        for status in (S.COMPLETED, S.FAILED, S.REJECTED):
            make_doc(status=status)
        self.assertEqual(services.claim_documents(10), [])


class DispatchTests(TestCase):
    databases = {"default"}

    @mock.patch("apps.records.tasks.classify_document_task.delay")
    @mock.patch("apps.records.tasks.extract_document_task.delay")
    def test_each_document_goes_to_its_own_stage(self, extract, classify):
        queued, stuck = make_doc(), make_doc(status=S.CLASSIFYING)
        MedicalDocument.objects.filter(pk=stuck.pk).update(
            claimed_at=timezone.now() - timedelta(minutes=services.STUCK_MINUTES + 1), attempts=1)
        self.assertEqual(dispatch_documents(10), 2)
        extract.assert_called_once_with(queued.id)
        classify.assert_called_once_with(stuck.id)

    @mock.patch("apps.records.tasks.extract_document_task.delay", side_effect=[RuntimeError("broker down"), None])
    def test_a_broker_error_on_one_document_does_not_stop_the_rest(self, extract):
        make_doc()
        make_doc()
        self.assertEqual(dispatch_documents(10), 1)
        self.assertEqual(extract.call_count, 2)

    @mock.patch("apps.records.tasks.extract_document_task.delay")
    def test_the_periodic_task_uses_the_configured_limit(self, extract):
        for _ in range(3):
            make_doc()
        cfg = SweepConfig.current()
        cfg.sweep_dispatch_limit = 2
        cfg.save()
        self.assertEqual(recover_stuck_documents(), 2)
        self.assertEqual(extract.call_count, 2)


class FullPipelineTests(TestCase):
    """Upload → dispatcher → extraction → classification with real PDFs; only S3 and the broker are faked."""
    databases = {"default"}

    @staticmethod
    def pdf_with(text):
        import fitz
        doc = fitz.open()
        doc.new_page().insert_text((50, 80), text, fontsize=10)
        return doc.tobytes()

    def test_a_batch_with_a_good_file_a_twin_and_a_bad_file_ends_with_each_in_a_final_state(self):
        from apps.records.tests.helpers import identity
        identity("AWP-T1")
        bucket = {}
        fake = mock.Mock()
        fake.put_bytes.side_effect = lambda path, data, mime_type: bucket.setdefault(path, data) and path
        fake.get_bytes.side_effect = lambda path: bucket[path]
        lab = self.pdf_with("City laboratory. Hemoglobin 13 g/dL, glucose 90, cholesterol 180. Reference range attached.")
        junk = b"not a pdf at all"
        files = [(SimpleUploadedFile(n, b, content_type="application/pdf"), b)
                 for n, b in (("lab.pdf", lab), ("lab-copy.pdf", lab), ("junk.pdf", junk))]

        with mock.patch("apps.records.services.storage", fake), \
                mock.patch("apps.records.tasks.classify_document_task.delay", side_effect=services.classify_document), \
                mock.patch("apps.records.tasks.extract_document_task.delay", side_effect=services.extract_document):
            batch, docs = services.save_upload("AWP-T1", files)
            self.assertEqual(dispatch_documents(10), 3)

        good, twin, bad = (reload(d) for d in docs)
        self.assertEqual((good.processing_status, good.doc_type, row(good).classification_source), (S.COMPLETED, "lab_report", "system"))
        self.assertIn("Hemoglobin", row(good).classification_details["extracted_text"])
        self.assertEqual(twin.processing_status, S.REJECTED)
        self.assertIn("Same as lab.pdf", twin.error)
        self.assertEqual(bad.processing_status, S.FAILED)

        batch.refresh_from_db()
        summary = services.batch_summary(batch)
        self.assertEqual(summary["status"], "completed")
        self.assertEqual((summary["counts"]["completed"], summary["counts"]["rejected"], summary["counts"]["failed"]), (1, 1, 1))
        self.assertEqual([d["file_name"] for d in summary["documents"]], ["lab.pdf", "lab-copy.pdf", "junk.pdf"])
