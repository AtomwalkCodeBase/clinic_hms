"""The review step: types list, instant/bulk upload, the patient's final answers (submit), the lock, and which
uploads still wait for review. No tables or columns are involved: "confirmed" is the classification's status."""
import datetime
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.patients.portal_views import PortalDocumentCountsView, PortalDocumentDetailView, PortalDocumentListCreateView
from apps.platform_admin.classification_rule_views import DocumentCorrectView
from apps.records import classification as cls, services
from apps.records.models import DocumentBatch, MedicalDocument
from apps.records.tests.helpers import PDF, identity, make_doc, reload
from apps.records.views import BatchDetailView, SubmitView, TypesView, UploadView
from apps.registry.models import PatientAccount
from core.authentication import MockUser

S = MedicalDocument.Status
LONG_AGO = "2000-01-01T00:00:00+00:00"
RESOLVE_RECORDS = mock.patch("apps.records.views.resolve_target_awpid_and_dob", return_value=("AWP-T1", None, None))
RESOLVE_PORTAL = mock.patch("apps.patients.portal_views.resolve_target_awpid_and_dob", return_value=("AWP-T1", None, None))


def patient_user():
    return MockUser({"user_id": 1, "role": "patient", "awpid": "AWP-T1"})


def call(view, method, path="/x/", data=None, fmt="json", **kwargs):
    request = getattr(APIRequestFactory(), method)(path, data or {}, format=fmt) if method != "get" else APIRequestFactory().get(path, data or {})
    force_authenticate(request, user=patient_user())
    return view.as_view()(request, **kwargs)


def reviewable(document_type="lab_report", by="rules", status="completed", **fields):
    return make_doc("AWP-T1", status=status, document_type=document_type, by=by, **fields)


class TypesTests(TestCase):
    databases = {"default"}

    def test_the_list_has_every_type_a_person_may_choose_and_not_the_empty_state(self):
        data = call(TypesView, "get").data["data"]["types"]
        self.assertEqual([t["code"] for t in data], list(cls.CHOOSABLE_TYPES))
        self.assertNotIn("not_classified", [t["code"] for t in data])
        self.assertEqual({"code": "lab_report", "label": "Lab Report"}, next(t for t in data if t["code"] == "lab_report"))
        self.assertEqual(len(data), 10)


@RESOLVE_RECORDS
@mock.patch("apps.records.views.start_processing")
@mock.patch("apps.records.services.storage")
@mock.patch("core.storage.put_bytes", side_effect=lambda key, data, mime_type: key)
class UploadModeTests(TestCase):
    databases = {"default"}

    def setUp(self):
        identity("AWP-T1")

    def post(self, files, **extra):
        return call(UploadView, "post", "/api/v1/records/upload/", {"files": files, **extra}, fmt="multipart")

    def pdf(self, name="a.pdf"):
        return SimpleUploadedFile(name, PDF, content_type="application/pdf")

    def test_one_file_goes_to_the_instant_queue_by_default(self, put, storage, start, _r):
        resp = self.post([self.pdf()])
        self.assertEqual((resp.status_code, resp.data["data"]["mode"]), (202, "instant"))
        self.assertEqual(start.call_args.args[1], "instant")

    def test_several_files_go_to_the_bulk_queue_by_default(self, put, storage, start, _r):
        resp = self.post([self.pdf("a.pdf"), self.pdf("b.pdf")])
        self.assertEqual((resp.status_code, resp.data["data"]["mode"]), (202, "bulk"))
        self.assertEqual(start.call_args.args[1], "bulk")

    def test_an_explicit_bulk_mode_takes_even_one_file_to_the_bulk_queue(self, put, storage, start, _r):
        resp = self.post([self.pdf()], mode="bulk")
        self.assertEqual((resp.status_code, resp.data["data"]["mode"]), (202, "bulk"))
        self.assertEqual(start.call_args.args[1], "bulk")

    def test_an_instant_upload_takes_exactly_one_file(self, put, storage, start, _r):
        resp = self.post([self.pdf("a.pdf"), self.pdf("b.pdf")], mode="instant")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(MedicalDocument.objects.count(), 0)
        start.assert_not_called()

    def test_an_unknown_mode_is_refused(self, put, storage, start, _r):
        self.assertEqual(self.post([self.pdf()], mode="turbo").status_code, 400)
        self.assertEqual(MedicalDocument.objects.count(), 0)


@RESOLVE_RECORDS
class SubmitTests(TestCase):
    """The only call that saves a decision; each file is judged on its own."""
    databases = {"default"}

    def setUp(self):
        identity("AWP-T1")

    def submit(self, *pairs):
        return call(SubmitView, "post", "/api/v1/records/submit/",
                    {"decisions": [{"document_id": d, "document_type": t} for d, t in pairs]})

    def test_a_confirmed_file_takes_the_persons_type_and_is_locked(self, _r):
        doc = reviewable("lab_report")
        data = self.submit((doc.id, "prescription")).data["data"]
        self.assertEqual((data["submitted"], data["rejected"]), ([doc.id], []))
        doc = reload(doc)
        self.assertEqual((doc.document_type, cls.method_of(doc), cls.is_confirmed(doc)), ("prescription", "staff", True))
        classification = doc.classification
        self.assertEqual((classification.status, classification.human_document_type, classification.final_document_type,
                          classification.ai_document_type), ("human_classified", "prescription", "prescription", "lab_report"))

    def test_confirming_the_suggestion_also_locks_it(self, _r):
        doc = reviewable("lab_report")
        self.submit((doc.id, "lab_report"))
        self.assertTrue(cls.is_confirmed(reload(doc)))

    def test_a_file_the_rules_could_not_place_can_be_filed_by_the_person(self, _r):
        doc = reviewable(cls.NOT_CLASSIFIED, status="review_required")
        self.assertEqual(self.submit((doc.id, "other")).data["data"]["submitted"], [doc.id])
        self.assertEqual((reload(doc).document_type, reload(doc).status), ("other", "completed"))

    def test_sending_the_same_list_twice_changes_nothing(self, _r):
        doc = reviewable("lab_report")
        self.submit((doc.id, "prescription"))
        data = self.submit((doc.id, "imaging_report")).data["data"]
        self.assertEqual((data["submitted"], data["rejected"]), ([], [{"document_id": doc.id, "reason": "already_confirmed"}]))
        self.assertEqual(reload(doc).document_type, "prescription")

    def test_each_bad_entry_is_reported_without_stopping_the_rest(self, _r):
        good = reviewable("lab_report")
        queued = make_doc("AWP-T1", status="queued")
        failed = make_doc("AWP-T1", status="failed", error_message="boom")
        theirs = make_doc("AWP-OTHER", status="completed", document_type="lab_report", by="rules")
        issued = make_doc("AWP-T1", status="completed", document_type="lab_report", by="issued", uploaded_by="staff", source_tenant_id="7")
        data = self.submit((good.id, "prescription"), (queued.id, "lab_report"), (failed.id, "lab_report"), (theirs.id, "lab_report"),
                           (issued.id, "lab_report"), (good.id + 9999, "lab_report"), (reviewable().id, "made_up")).data["data"]
        self.assertEqual(data["submitted"], [good.id])
        reasons = {r["document_id"]: r["reason"] for r in data["rejected"]}
        self.assertEqual(reasons[queued.id], "still_processing")
        self.assertEqual(reasons[failed.id], "failed")
        self.assertEqual(reasons[theirs.id], "not_found")
        self.assertEqual(reasons[issued.id], "not_found")
        self.assertEqual(reasons[good.id + 9999], "not_found")
        self.assertIn("invalid_type", reasons.values())
        self.assertFalse(cls.is_confirmed(reload(theirs)))

    def test_an_empty_or_oversized_list_is_refused_as_a_whole(self, _r):
        self.assertEqual(self.submit().status_code, 400)
        doc = reviewable()
        self.assertEqual(self.submit(*[(doc.id, "lab_report")] * 101).status_code, 400)

    def test_the_answer_says_how_many_still_wait(self, _r):
        with override_settings(RECORDS_REVIEW_FROM=LONG_AGO):
            a, b = reviewable(), reviewable()
            data = self.submit((a.id, "lab_report")).data["data"]
        self.assertEqual(data["counts"], {"awaiting_review": 1})


class LockTests(TestCase):
    databases = {"default"}

    def setUp(self):
        identity("AWP-T1")
        self.acct = PatientAccount.objects.using("default").create(awpid="AWP-T1", full_name="P", mobile="9333333333", password="x")

    def test_a_confirmed_document_cannot_be_changed_again(self):
        doc = reviewable("lab_report")
        services.correct_document(doc, "prescription")
        with self.assertRaises(cls.DocumentLocked):
            services.correct_document(reload(doc), "imaging_report")
        self.assertEqual(reload(doc).document_type, "prescription")

    @RESOLVE_PORTAL
    def test_the_patient_gets_a_clear_locked_answer(self, _r):
        doc = reviewable("lab_report")
        services.correct_document(doc, "prescription")
        resp = call(PortalDocumentDetailView, "patch", data={"doc_type": "imaging_report"}, doc_id=doc.id)
        self.assertEqual((resp.status_code, resp.data["errors"]), (409, {"code": "locked"}))
        self.assertEqual(reload(doc).document_type, "prescription")

    def test_not_even_a_platform_admin_can_change_it(self):
        doc = reviewable("lab_report")
        services.correct_document(doc, "prescription")
        request = APIRequestFactory().patch("/x/", {"doc_type": "imaging_report"}, format="json")
        force_authenticate(request, user=MockUser({"user_id": 1, "role": "platform_admin", "is_platform": True}))
        with mock.patch("core.permissions.IsPlatformAdmin.has_permission", return_value=True):
            resp = DocumentCorrectView.as_view()(request, pk=doc.id)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(reload(doc).document_type, "prescription")


@override_settings(RECORDS_REVIEW_FROM="2026-06-01T00:00:00+00:00")
@RESOLVE_PORTAL
class AwaitingReviewTests(TestCase):
    """Which uploads wait for the patient: new ones, after the review step began, not yet confirmed."""
    databases = {"default"}

    def setUp(self):
        identity("AWP-T1")

    def listing(self, **params):
        return [r["id"] for r in call(PortalDocumentListCreateView, "get", data=params).data["results"]]

    def old(self, doc):
        MedicalDocument.objects.filter(pk=doc.pk).update(created_at=timezone.now() - datetime.timedelta(days=400))
        return reload(doc)

    def test_a_new_unconfirmed_upload_is_pending_and_leaves_my_documents(self, _r):
        new = reviewable("lab_report")
        self.assertEqual(self.listing(review="pending"), [new.id])
        self.assertEqual(self.listing(), [])                       # My Documents (default: confirmed)
        self.assertEqual(self.listing(review="all"), [new.id])

    def test_confirming_moves_it_to_my_documents(self, _r):
        new = reviewable("lab_report")
        services.correct_document(new, "lab_report")
        self.assertEqual(self.listing(review="pending"), [])
        self.assertEqual(self.listing(), [new.id])

    def test_documents_from_before_the_review_step_never_need_review(self, _r):
        legacy = self.old(reviewable("lab_report"))
        self.assertEqual(self.listing(review="pending"), [])
        self.assertEqual(self.listing(), [legacy.id])
        self.assertFalse(cls.is_confirmed(legacy))              # they keep working as before, just not locked

    def test_hospital_issued_and_staff_documents_never_need_review(self, _r):
        issued = make_doc("AWP-T1", status="completed", document_type="prescription", by="issued", uploaded_by="staff", source_tenant_id="7")
        self.assertEqual(self.listing(), [issued.id])
        self.assertEqual(self.listing(review="pending"), [])

    def test_a_file_still_being_read_is_pending_too(self, _r):
        queued = make_doc("AWP-T1", status="queued")
        self.assertEqual(self.listing(review="pending"), [queued.id])

    def test_the_list_can_be_narrowed_to_one_type(self, _r):
        a = self.old(reviewable("lab_report"))
        b = self.old(reviewable("prescription"))
        self.assertEqual(self.listing(doc_type="prescription"), [b.id])
        self.assertEqual(sorted(self.listing()), sorted([a.id, b.id]))

    def test_with_the_step_switched_off_nothing_is_ever_pending(self, _r):
        with override_settings(RECORDS_REVIEW_FROM=""):
            doc = reviewable("lab_report")
            self.assertEqual(self.listing(review="pending"), [])
            self.assertEqual(self.listing(), [doc.id])

    def test_the_counts_cover_every_type_and_keep_pending_files_apart(self, _r):
        self.old(reviewable("lab_report"))
        self.old(reviewable("lab_report"))
        self.old(reviewable("prescription"))
        self.old(reviewable(cls.NOT_CLASSIFIED, status="review_required"))
        reviewable("imaging_report")                                    # new and unconfirmed: waiting, not counted as a type
        reviewable(cls.NOT_CLASSIFIED, status="review_required")
        make_doc("AWP-T1", status="queued")                              # still being read: not reviewable yet
        data = call(PortalDocumentCountsView, "get").data["data"]
        self.assertEqual(set(data["by_type"]), set(cls.CHOOSABLE_TYPES))
        self.assertEqual((data["by_type"]["lab_report"], data["by_type"]["prescription"], data["by_type"]["imaging_report"]), (2, 1, 0))
        self.assertEqual((data["total"], data["unclassified"], data["awaiting_review"]), (4, 1, 2))

    def test_a_row_carries_the_suggestion_the_score_and_whether_it_is_locked(self, _r):
        doc = reviewable("lab_report")
        row = call(PortalDocumentListCreateView, "get", data={"review": "pending"}).data["results"][0]
        self.assertEqual((row["suggested_type"], row["score"], row["confirmed"]), ("lab_report", 20, False))
        self.assertNotIn("best_guess", row)
        services.correct_document(doc, "lab_report")
        row = call(PortalDocumentListCreateView, "get").data["results"][0]
        self.assertEqual((row["suggested_type"], row["confirmed"], row["doc_type"]), (None, True, "lab_report"))


class BatchProgressTests(TestCase):
    databases = {"default"}

    @RESOLVE_RECORDS
    def test_the_batch_reports_how_far_it_has_got(self, _r):
        batch = DocumentBatch.objects.create(patient=identity("AWP-T1"), total_files=4)
        for status in ("completed", "review_required", "failed", "extracting"):
            make_doc("AWP-T1", status=status, batch=batch)
        data = call(BatchDetailView, "get", batch_id=batch.id).data["data"]
        self.assertEqual((data["progress_percent"], data["total_files"]), (75, 4))
        self.assertEqual(data["counts"]["extracting"], 1)
        self.assertNotIn("second_best_score", str(data))
