"""Tests of the patient portal, consult pad and record sharing."""
import uuid
from apps.documents.lib_documents import batch_counts
from unittest import mock
from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate, APIClient
from apps.patients.views import PortalRegisterView, PortalProfileView, PortalDocumentDetailView, PortalDocumentListCreateView
from django.core.exceptions import FieldDoesNotExist
from core.auth.otp_views import OTPRequestView
from core.auth.views import PatientLoginView
from core.auth.otp import Purpose
from apps.patients.models import Patient, RecordsShareRequest
from apps.opd.models import ConsultSession
from core.utils import new_pad_token
from core.api.authentication import MockUser
from django.urls import NoReverseMatch, reverse
from apps.documents.models import CHOOSABLE_TYPES
from apps.documents.models import DocumentBatch, MedicalDocument, DocumentClassification
from apps.documents.tests.tests import identity, make_doc, reload
from datetime import timedelta
from django.utils import timezone
from apps.patients.views import ConsultPadView, _open_session_for_token
from core.tests.testing import HospitalDBTestCase, ensure_hospital, make_branch, make_patient, make_staff, requires_hospital_db
from apps.patients.views import _vault_documents
from apps.hospital_patients.services import PatientService
from apps.patients.services import accounts, create_account, set_password, check_password


BODY = {"action_token": "t", "full_name": "Asha Rao", "mobile": "9876543210", "password": "Str0ng!pass"}
class PortalAccountTests(TestCase):
    databases = {"default"}

    def register(self):
        request = APIRequestFactory().post("/api/v1/portal/register/", BODY, format="json")
        with mock.patch("core.auth.otp.decode_action_token", return_value={"identifier": "asha@example.com"}), \
                mock.patch("core.validation.validate_mobile_real", return_value=(True, "")):
            return PortalRegisterView.as_view()(request)

    def test_signing_up_creates_one_row_that_is_both_the_identity_and_the_login(self):
        self.assertEqual(self.register().status_code, 200)
        self.assertEqual(Patient.objects.count(), 1)
        account = accounts().get()
        self.assertEqual((account.mobile, account.email), ("9876543210", "asha@example.com"))
        self.assertTrue(check_password(account, "Str0ng!pass"))

    def test_a_walk_in_who_later_signs_up_keeps_the_awpid_they_already_have(self):
        walk_in = Patient.objects.create(
            awpid="AW-WALKIN", full_name="Asha Rao", mobile="9876543210")
        self.assertEqual(accounts().count(), 0)          # registered at a front desk: no login yet
        self.assertEqual(self.register().status_code, 200)
        self.assertEqual(Patient.objects.count(), 1)
        self.assertEqual(accounts().get().awpid, walk_in.awpid)

    def test_signing_up_twice_with_the_same_mobile_is_refused(self):
        self.register()
        self.assertEqual(self.register().status_code, 400)
        self.assertEqual(Patient.objects.count(), 1)
class MobileIsStoredAsTheNumberTests(TestCase):
    """The mobile number exists once, as the plain 10 digits: hospitals match on it and the patient logs in with it."""
    databases = {"default"}

    def setUp(self):
        self.acct = create_account(
            awpid="AWPID-LOGIN1", full_name="Asha", mobile="9876543210", email="asha@example.com", password="x")
        set_password(self.acct, "Str0ng!pass")
        self.acct.save(using="default")

    def post(self, view, data):
        return view.as_view()(APIRequestFactory().post("/x/", data, format="json"))

    def test_the_mobile_is_stored_as_the_plain_number_and_there_is_no_hash_column(self):
        with self.assertRaises(FieldDoesNotExist):
            Patient._meta.get_field("mobile_hash")
        self.assertEqual(self.acct.mobile, "9876543210")

    def test_a_patient_logs_in_with_the_number_however_they_type_it(self):
        for typed in ("9876543210", "+91 98765 43210", "98765-43210"):
            resp = self.post(PatientLoginView, {"mobile": typed, "password": "Str0ng!pass"})
            self.assertEqual(resp.status_code, 200, typed)
        self.assertEqual(self.post(PatientLoginView, {"mobile": "9876543210", "password": "wrong"}).status_code, 400)
        self.assertEqual(self.post(PatientLoginView, {"mobile": "9000000000", "password": "Str0ng!pass"}).status_code, 400)
        for junk in ("abc", "12", "not a number"):                     # something that isn't a phone number is just a failed login
            self.assertEqual(self.post(PatientLoginView, {"mobile": junk, "password": "x"}).status_code, 400, junk)

    def test_a_walk_in_with_the_same_number_but_no_password_cannot_log_in(self):
        Patient.objects.using("default").create(awpid="AW-WALK", full_name="Walk In", mobile="9111111111")
        self.assertEqual(self.post(PatientLoginView, {"mobile": "9111111111", "password": ""}).status_code, 400)

    def test_the_profile_says_a_number_is_on_file_without_showing_it(self):
        request = APIRequestFactory().get("/x/")
        force_authenticate(request, user=MockUser({"user_id": self.acct.pk, "role": "patient", "awpid": "AWPID-LOGIN1"}))
        data = PortalProfileView.as_view()(request).data["data"]
        self.assertEqual((data["mobile"], data["mobile_on_file"]), ("", True))

    def test_a_code_for_someone_who_typed_their_awpid_goes_to_their_email(self):
        with mock.patch("core.auth.otp_views._send_code", return_value=True) as send:
            resp = self.post(OTPRequestView, {"purpose": Purpose.LOGIN_PATIENT, "identifier": "AWPID-LOGIN1"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(send.call_args.args[0], "asha@example.com")
        self.assertEqual(send.call_args.args[1], "email")

    def test_an_account_with_no_email_is_asked_to_use_its_mobile_instead(self):
        accounts().filter(pk=self.acct.pk).update(email="")
        with mock.patch("core.auth.otp_views._send_code", return_value=True) as send:
            resp = self.post(OTPRequestView, {"purpose": Purpose.LOGIN_PATIENT, "identifier": "AWPID-LOGIN1"})
        self.assertEqual(resp.status_code, 400)
        send.assert_not_called()


@override_settings(RECORDS_REVIEW_FROM="")
class PortalDocumentTests(TestCase):
    databases = {"default"}

    def setUp(self):
        self.acct = create_account(
            awpid="AW-DOC-1", full_name="P", mobile="9222222222", password="x",
        )
        identity(self.acct.awpid)

    def make_doc(self, **kw):
        return make_doc(self.acct.awpid, status="completed", document_type="lab_report", by="rules", **kw)

    def user(self):
        return MockUser({"user_id": self.acct.pk, "role": "patient", "awpid": self.acct.awpid})

    def call(self, view, method, data=None, **kwargs):
        factory = getattr(APIRequestFactory(), method)
        request = factory("/x/", data, format="json") if data is not None else factory("/x/")
        force_authenticate(request, user=self.user())
        return view.as_view()(request, **kwargs)

    def patch(self, doc, **body):
        return self.call(PortalDocumentDetailView, "patch", body, doc_id=doc.pk)

    # ── only a failed file, or an upload still waiting for the patient's review, can be removed ──
    def dismiss(self, doc):
        return self.call(PortalDocumentDetailView, "delete", doc_id=doc.pk)

    def test_a_document_in_the_patients_records_cannot_be_deleted(self):
        for status in ("completed", "review_required", "queued", "extracting"):
            doc = make_doc(self.acct.awpid, status=status)
            resp = self.dismiss(doc)
            self.assertEqual(resp.status_code, 409, status)
            self.assertTrue(MedicalDocument.objects.filter(pk=doc.pk).exists(), status)
        with self.assertRaises(NoReverseMatch):
            reverse("portal-documents-bulk-delete")

    def test_a_failed_file_can_be_dismissed_and_its_stored_copy_is_removed(self):
        doc = make_doc(self.acct.awpid, status="failed", error_message="boom")
        name = doc.file_name.name
        with mock.patch("core.storage.delete") as delete:
            resp = self.dismiss(doc)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(MedicalDocument.objects.filter(pk=doc.pk).exists())
        delete.assert_called_once_with(name)

    REVIEW_ON = "2000-01-01T00:00:00+00:00"

    @override_settings(RECORDS_REVIEW_FROM=REVIEW_ON)
    def test_a_read_upload_waiting_for_review_can_be_removed_and_its_stored_copy_is_removed(self):
        suggested = make_doc(self.acct.awpid, status="completed", document_type="lab_report", by="rules")
        unclassified = make_doc(self.acct.awpid, status="review_required", by="rules")
        with mock.patch("core.storage.delete") as delete:
            for doc in (suggested, unclassified):
                self.assertEqual(self.dismiss(doc).status_code, 200, doc.status)
                self.assertFalse(MedicalDocument.objects.filter(pk=doc.pk).exists())
        self.assertEqual(delete.call_count, 2)

    @override_settings(RECORDS_REVIEW_FROM=REVIEW_ON)
    def test_a_confirmed_upload_or_one_still_being_read_cannot_be_removed(self):
        confirmed = make_doc(self.acct.awpid, status="completed", document_type="lab_report", by="human")
        for doc in (confirmed,
                    make_doc(self.acct.awpid, status="queued"),
                    make_doc(self.acct.awpid, status="extracting"),
                    make_doc(self.acct.awpid, status="classifying")):
            with mock.patch("core.storage.delete") as delete:
                self.assertEqual(self.dismiss(doc).status_code, 409, doc.status)
            delete.assert_not_called()
            self.assertTrue(MedicalDocument.objects.filter(pk=doc.pk).exists(), doc.status)

    @override_settings(RECORDS_REVIEW_FROM=REVIEW_ON)
    def test_someone_elses_upload_waiting_for_review_cannot_be_removed(self):
        other = make_doc("AW-OTHER", status="completed", document_type="lab_report", by="rules")
        self.assertEqual(self.dismiss(other).status_code, 404)
        self.assertTrue(MedicalDocument.objects.filter(pk=other.pk).exists())

    def test_dismissing_keeps_the_batch_counters_right(self):
        batch = DocumentBatch.objects.create(patient=identity(self.acct.awpid))
        good = make_doc(self.acct.awpid, status="completed", batch=batch)
        make_doc(self.acct.awpid, status="completed", batch=batch)
        bad = make_doc(self.acct.awpid, status="failed", batch=batch)
        with mock.patch("core.storage.delete"):
            self.assertEqual(self.dismiss(bad).status_code, 200)
        batch.refresh_from_db()
        self.assertEqual((batch_counts(batch)["total_files"], batch_counts(batch)["processed_files"], batch_counts(batch)["failed_files"], batch_counts(batch)["status"]), (2, 2, 0, "completed"))
        self.assertTrue(MedicalDocument.objects.filter(pk=good.pk).exists())

    def test_dismissing_the_only_file_of_a_batch_removes_the_batch(self):
        batch = DocumentBatch.objects.create(patient=identity(self.acct.awpid))
        bad = make_doc(self.acct.awpid, status="failed", batch=batch)
        with mock.patch("core.storage.delete"):
            self.assertEqual(self.dismiss(bad).status_code, 200)
        self.assertFalse(DocumentBatch.objects.filter(pk=batch.pk).exists())

    def test_someone_elses_failed_file_cannot_be_dismissed(self):
        other = make_doc("AW-OTHER", status="failed")
        self.assertEqual(self.dismiss(other).status_code, 404)
        self.assertTrue(MedicalDocument.objects.filter(pk=other.pk).exists())

    def test_a_hospital_issued_file_cannot_be_dismissed(self):
        doc = make_doc(self.acct.awpid, status="failed", created_by_type="H")
        self.assertEqual(self.dismiss(doc).status_code, 400)
        self.assertTrue(MedicalDocument.objects.filter(pk=doc.pk).exists())

    # ── the list ──
    def test_the_list_shows_status_and_type(self):
        doc = self.make_doc(name="rx.pdf")
        results = self.call(PortalDocumentListCreateView, "get").data["results"]
        self.assertEqual([(r["medical_document_id"], r["file_name"], r["title"], r["processing_status"], r["doc_type"])
                          for r in results], [(doc.pk, "rx.pdf", "rx.pdf", "completed", "lab_report")])

    def test_someone_elses_documents_are_not_listed(self):
        make_doc("AW-OTHER", status="completed", document_type="lab_report")
        self.assertEqual(self.call(PortalDocumentListCreateView, "get").data["results"], [])

    def test_the_row_carries_the_number_a_hospital_printed_on_the_document(self):
        make_doc(self.acct.awpid, status="completed", document_type="prescription", by="issued", created_by_type="H",
                 source_hospital_id="7", name="RX-1")
        row = self.call(PortalDocumentListCreateView, "get").data["results"][0]
        self.assertEqual((row["public_document_id"], row["source_hospital_id"], row["method"]), ("RX-1", 7, "staff"))
        self.assertNotIn("hospital_label", row)
        self.assertNotIn("doctor_label", row)

    def test_an_unclassified_row_shows_no_guess_at_all(self):
        doc = make_doc(self.acct.awpid, status="review_required", by="rules", name="u.pdf")
        DocumentClassification.objects.filter(document=doc).update(ai_classification="lab_report")
        row = self.call(PortalDocumentListCreateView, "get").data["results"][0]
        self.assertEqual((row["doc_type"], row["suggested_type"], row["confirmed"], row["processing_status"]),
                         ("not_classified", None, False, "review_required"))
        self.assertNotIn("best_guess", row)

    def test_a_failed_row_carries_its_reason(self):
        make_doc(self.acct.awpid, status="failed", error_message="The file is empty.")
        self.assertEqual(self.call(PortalDocumentListCreateView, "get").data["results"][0]["error"], "The file is empty.")

    def test_the_list_can_be_filtered_by_status(self):
        make_doc(self.acct.awpid, status="queued", name="q.pdf")
        make_doc(self.acct.awpid, status="review_required", name="r.pdf")
        make_doc(self.acct.awpid, status="completed", name="c.pdf")
        request = APIRequestFactory().get("/x/", {"status": "queued,review_required"})
        force_authenticate(request, user=self.user())
        results = PortalDocumentListCreateView.as_view()(request).data["results"]
        self.assertEqual(sorted(r["processing_status"] for r in results), ["queued", "review_required"])

    # ── choosing a type ──
    def test_the_patient_can_file_a_document_the_rules_could_not_place(self):
        doc = make_doc(self.acct.awpid, status="review_required", by="rules")
        resp = self.patch(doc, doc_type="prescription")
        self.assertEqual(resp.status_code, 200)
        doc = reload(doc)
        self.assertEqual((doc.doc_classification, doc.status), ("prescription", "completed"))
        self.assertEqual(resp.data["data"]["method"], "staff")

    def test_the_patient_can_only_choose_one_of_the_fixed_types(self):
        doc = make_doc(self.acct.awpid, status="review_required", by="rules")
        for bad in ("made_up", "not_classified", "LAB_REPORT"):
            self.assertEqual(self.patch(doc, doc_type=bad).status_code, 400, bad)
        self.assertEqual(reload(doc).doc_classification, "not_classified")

    def test_the_type_of_a_hospital_issued_report_cannot_be_changed(self):
        doc = self.make_doc(created_by_type="H", source_hospital_id="7", source_type="encounter", source_id=uuid.UUID(int=1))
        self.assertEqual(self.patch(doc, doc_type="imaging_report").status_code, 400)

    def test_the_detail_offers_the_fixed_types(self):
        doc = self.make_doc()
        data = self.call(PortalDocumentDetailView, "get", doc_id=doc.pk).data["data"]
        self.assertEqual(sorted(data["doc_types"]), sorted(CHOOSABLE_TYPES))

    # ── retry ──
    def test_a_failed_file_can_be_tried_again(self):
        doc = make_doc(self.acct.awpid, status="failed", error_message="boom")
        with mock.patch("apps.documents.tasks.extract_document_task.apply_async") as delay:
            resp = self.patch(doc, action="retry")
        self.assertEqual(resp.status_code, 200)
        delay.assert_called_once_with(args=[doc.pk, "instant"], queue="instant")
        self.assertEqual((reload(doc).status, reload(doc).error_message), ("queued", ""))

    def test_only_a_failed_file_can_be_retried(self):
        for status in ("completed", "review_required", "queued"):
            doc = make_doc(self.acct.awpid, status=status)
            self.assertEqual(self.patch(doc, action="retry").status_code, 400, status)

    def test_keeping_a_duplicate_is_gone_because_duplicates_are_no_longer_rejected(self):
        doc = make_doc(self.acct.awpid, status="completed")
        self.assertEqual(self.patch(doc, action="keep").status_code, 400)

    # ── the activity ──
    def events(self, doc):
        return [e["text"] for e in self.call(PortalDocumentDetailView, "get", doc_id=doc.pk).data["data"]["events"]]

    def test_the_detail_tells_what_happened_to_the_report(self):
        doc = make_doc(self.acct.awpid, status="completed", document_type="lab_report", by="rules", name="x.pdf")
        self.assertEqual(self.events(doc), ["You uploaded this file", "Filed as Lab report by the rules"])
        self.patch(doc, doc_type="prescription")
        self.assertEqual(self.events(doc), ["You uploaded this file", "You set the type to Prescription"])

    def test_the_activity_of_a_document_that_needs_review_and_of_a_failure(self):
        review = make_doc(self.acct.awpid, status="review_required", by="rules")
        DocumentClassification.objects.filter(document=review).update(ai_classification="lab_report")
        failed = make_doc(self.acct.awpid, status="failed", error_message="The file is empty.")
        self.assertEqual(self.events(review)[-1], "The rules couldn’t tell what it is - choose its type")
        self.assertEqual(self.events(failed)[-1], "We couldn’t read it — The file is empty.")


@requires_hospital_db
class ConsultPadTokenTests(HospitalDBTestCase):
    def setUp(self):
        super().setUp()
        from apps.hospital_master.models import Hospital
        from apps.opd.models import Appointment, OPDEncounter
        db = self.hospital_alias
        self.hospital = Hospital.objects.using("default").update_or_create(
            pk=1, defaults={"name": "Pad Hospital", "hospital_code": "pad-1", "db_name": db, "is_active": True})[0]
        branch, place = make_branch(db)
        doctor = make_staff(db, "doctor", phone="9000000071", place=place)
        patient = make_patient(db, "AW-PAD", branch=branch, full_name="Pad Patient", gender="F")
        self.patient, self.doctor, self.place = patient, doctor, place
        self.encounter = self.new_encounter()

    def new_encounter(self):
        from apps.opd.models import Appointment, OPDEncounter
        db = self.hospital_alias
        appt = Appointment.objects.using(db).create(patient=self.patient, doctor=self.doctor, branch_department=self.place, scheduled_date=timezone.now().date())
        return OPDEncounter.objects.using(db).create(appointment=appt)

    def sign(self, encounter):
        encounter.sign(using=self.hospital_alias)

    def session(self, encounter=None, **fields):
        return ConsultSession.objects.using(self.hospital_alias).create(
            encounter=encounter or self.encounter, token=f"{self.hospital.pk}.{new_pad_token()}", **fields)

    def test_every_session_gets_its_own_random_token(self):
        a, b = self.session(), self.session(self.new_encounter())
        self.assertNotEqual(a.token, b.token)
        self.assertGreaterEqual(len(a.token), 40)

    def test_an_open_session_is_found_by_its_token_with_the_patient(self):
        s = self.session()
        identity, found = _open_session_for_token(s.token)
        self.assertEqual((identity.awpid, found.pk), ("AW-PAD", s.pk))

    def test_an_unknown_token_is_not_valid(self):
        self.assertEqual(_open_session_for_token("nope"), (None, None))
        self.assertEqual(_open_session_for_token("999.nope"), (None, None))           # no such hospital

    def test_a_signed_encounters_session_still_names_the_patient_but_is_not_writable(self):
        signed = self.session()
        self.sign(self.encounter)
        identity, found = _open_session_for_token(signed.token)
        self.assertEqual((identity.awpid, found), ("AW-PAD", None))

    def test_an_old_untouched_session_stays_open_while_the_encounter_is_a_draft(self):
        s = self.session()
        ConsultSession.objects.using(self.hospital_alias).filter(pk=s.pk).update(updated_at=timezone.now() - timedelta(days=3))
        self.assertEqual(_open_session_for_token(s.token)[1].pk, s.pk)

    def test_an_encounter_cannot_have_two_sessions(self):
        from django.db import IntegrityError, transaction
        self.session()
        with self.assertRaises(IntegrityError), transaction.atomic(using=self.hospital_alias):
            self.session()

    def test_the_phone_page_reports_whether_a_consultation_is_active(self):
        view = ConsultPadView.as_view()
        open_session = self.session()
        data = view(APIRequestFactory().get("/x/"), token=open_session.token).data["data"]
        self.assertEqual((data["active"], data["session_id"], data["patient_name"]), (True, open_session.pk, "Pad Patient"))
        closed_enc = self.new_encounter()
        closed = self.session(closed_enc)
        self.sign(closed_enc)
        self.assertFalse(view(APIRequestFactory().get("/x/"), token=closed.token).data["data"]["active"])
        self.assertEqual(view(APIRequestFactory().get("/x/"), token="nope").status_code, 404)

    def test_autosave_from_the_phone_works_on_a_draft_and_not_after_signing(self):
        view = ConsultPadView.as_view()
        s = self.session()
        res = view(APIRequestFactory().put("/x/", {"tab": "note", "pages": []}, format="json"), token=s.token)
        self.assertEqual(res.status_code, 200)
        self.sign(self.encounter)
        res = view(APIRequestFactory().put("/x/", {"tab": "note", "pages": []}, format="json"), token=s.token)
        self.assertEqual(res.status_code, 409)


AWPID = "AW-SHARE-W1"


@override_settings(RECORDS_REVIEW_FROM="2000-01-01T00:00:00+00:00")
class WaitingUploadsAreNotSharedTests(TestCase):
    databases = {"default"}

    def setUp(self):
        identity(AWPID)
        self.waiting = make_doc(AWPID, status="completed", document_type="lab_report", by="rules", name="waiting.pdf")
        self.confirmed = make_doc(AWPID, status="completed", document_type="lab_report", by="human", name="confirmed.pdf")
        self.issued = make_doc(AWPID, status="completed", document_type="prescription", by="issued", name="issued.pdf",
                               created_by_type="H")
        self.grant = RecordsShareRequest.objects.using("default").create(
            token="tok-wait-1", code="654321", patient=identity(AWPID), status=RecordsShareRequest.STATUS_APPROVED,
            expires_at=timezone.now() + timedelta(hours=1),
        )

    def test_the_vault_leaves_out_a_waiting_upload(self):
        ids = {d["medical_document_id"] for d in _vault_documents(AWPID)}
        self.assertEqual(ids, {self.confirmed.pk, self.issued.pk})

    def test_a_waiting_upload_cannot_be_viewed_by_id(self):
        res = APIClient().get(f"/api/v1/records-share/{self.grant.token}/documents/{self.waiting.pk}/view/")
        self.assertEqual(res.status_code, 404)

    def test_a_waiting_upload_cannot_be_requested_for_download(self):
        res = APIClient().post(f"/api/v1/records-share/{self.grant.token}/downloads/", {"doc_id": self.waiting.pk}, format="json")
        self.assertEqual(res.status_code, 404)
        self.grant.refresh_from_db()
        self.assertIsNone(self.grant.pending_download_id)

    def test_a_confirmed_upload_can_still_be_requested(self):
        res = APIClient().post(f"/api/v1/records-share/{self.grant.token}/downloads/", {"doc_id": self.confirmed.pk}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["data"]["state"], "requested")

    def test_the_hospital_history_leaves_out_a_waiting_upload(self):
        docs = PatientService.get_shared_history(awpid=AWPID)["documents"]
        self.assertEqual({d["medical_document_id"] for d in docs}, {self.confirmed.pk, self.issued.pk})

    def test_the_hospital_history_lists_the_prescriptions_a_hospital_issued(self):
        rx = make_doc(AWPID, status="completed", document_type="prescription", by="issued", name="rx.pdf", created_by_type="H",
                      source_type="encounter", source_id=uuid.uuid4(), document_date=timezone.now().date())
        history = PatientService.get_shared_history(awpid=AWPID)
        self.assertEqual(history["prescriptions"], [{"prescribed_on": rx.document_date, "items": []}])

    @override_settings(RECORDS_REVIEW_FROM="")
    def test_with_the_review_step_off_everything_is_shared_as_before(self):
        ids = {d["medical_document_id"] for d in _vault_documents(AWPID)}
        self.assertEqual(ids, {self.waiting.pk, self.confirmed.pk, self.issued.pk})


class PatientIntegrityRulesTests(TestCase):
    databases = {"default"}

    def test_a_patient_cannot_be_their_own_guardian(self):
        from django.db import IntegrityError, transaction
        from apps.patients.models import PatientRelationship
        p = identity("AW-SELF-1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            PatientRelationship.objects.create(dependent=p, guardian=p)

    def test_two_main_accounts_cannot_share_a_mobile_but_dependents_can_use_their_guardians(self):
        from django.db import IntegrityError, transaction
        Patient.objects.create(awpid="AW-M-1", full_name="Parent", mobile="9000011111")
        Patient.objects.create(awpid="AW-M-2", full_name="Child", mobile="9000011111", is_dependent=True)
        Patient.objects.create(awpid="AW-M-3", full_name="Child 2", mobile="9000011111", is_dependent=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Patient.objects.create(awpid="AW-M-4", full_name="Other", mobile="9000011111")

    def test_the_access_log_survives_the_patient_and_still_says_who_it_was_about(self):
        from apps.patients.models import EmergencyAccessLog
        p = identity("AW-LOG-1")
        log = EmergencyAccessLog.objects.create(patient=p, event=EmergencyAccessLog.EVENT_VIEWED)
        self.assertEqual(log.awpid, "AW-LOG-1")
        p.delete()
        log.refresh_from_db()
        self.assertEqual((log.patient_id, log.awpid), (None, "AW-LOG-1"))
