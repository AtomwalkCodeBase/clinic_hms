"""Tests of documents, extraction, classification, timeline, vitals, episodes, vaccinations and schedules."""
import uuid
import datetime
import base64
import datetime as dt
from apps.documents.lib_documents import batch_counts
from apps.documents.lib_vitals import bmi
from apps.documents.models import (
    DocumentExtraction,
    MedicalDocument,
    DocumentClassification,
    DocumentBatch,
    ClinicalEvent,
    LabResult,
    SharedAllergy,
    GrowthMeasurement,
    Vitals,
    ImmunizationRecord,
    ScheduleRule,
    MilestoneRecord,
    BirthHistory,
    Schedule,
)
from apps.patients.models import Patient, ConsultSession, PatientRelationship
from core.tests.testing import ensure_hospital, HospitalDBTestCase, requires_hospital_db
from django.test import SimpleTestCase, TestCase, override_settings
from unittest import mock
from rest_framework.test import APIRequestFactory, force_authenticate
from apps.opd.views import EncounterInternalNoteView
from core.api.authentication import MockUser
from django.db import IntegrityError, connection, transaction
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from apps.patients.views import PortalDocumentCountsView, PortalDocumentDetailView, PortalDocumentListCreateView
from apps.hospital_master.classification_rule_views import DocumentCorrectView
from apps.documents.views import (
    BatchDetailView,
    SubmitView,
    TypesView,
    UploadView,
)
from apps.documents.tasks import classify_document_task, extract_document_task
from types import SimpleNamespace
from apps.opd.models import HospitalPatient, Allergy
from apps.lab.models import LabReport, LabRequest, LabTest
from apps.lab.views import LabRequestAttachDocumentView
from apps.opd.models import Appointment, OPDEncounter
from apps.documents.lib_vitals import sync_encounter_to_hie
from apps.hospital_setup.models import Branch
from apps.hospital_setup.models import StaffUser
from apps.hospital_master.models import Hospital, HospitalParameters
from decimal import Decimal
from datetime import timedelta
from apps.documents import views as views
from apps.documents import views as vax_views
from apps.documents import views as ped_views
from apps.documents import urls as org_urls
from apps.documents.lib_roadmap import build_roadmap, summarize_roadmap
from apps.documents.lib_roadmap import milestone_rule_dict, schedule_dict, template_dict, vaccination_rule_dict
from apps.hospital_master import platform_urls
from apps.patients.services import create_account
from apps.documents import lib_documents as classification_rules
from apps.documents import lib_vitals as growth_reference
from apps.documents import lib_documents as records
from apps.documents import lib_roadmap as roadmap
from apps.documents import lib_vitals as vitals
from apps.documents.models import CHOOSABLE_TYPES, CLASSIFIER_HOSPITAL, DOCUMENT_TYPES, HUMAN_CLASSIFIED, ISSUED, NOT_CLASSIFIED, REVIEW_REQUIRED, RULE_CLASSIFIED


PDF = b"%PDF-1.4\n" + b"x" * 100
def identity(awpid="AWP-T1"):
    """documents.patient is a real foreign key to patient (by AWPID)."""
    return Patient.objects.get_or_create(awpid=awpid, defaults={"full_name": "Test Patient"})[0]
def make_doc(awpid="AWP-T1", *, status="queued", document_type=NOT_CLASSIFIED, by=None, text=None, batch=None,
             name="doc.pdf", **fields):
    """A MedicalDocument in `status` and of `document_type`. `by` records how the type was decided"""
    if fields.get("source_hospital_id") is not None:
        fields["source_hospital_id"] = int(fields["source_hospital_id"])
        ensure_hospital(fields["source_hospital_id"])
    doc = MedicalDocument(patient=identity(awpid), batch=batch, document_ref_name=name, status=status,
                          doc_classification=document_type, **fields)
    doc.file_name = "patients/AWP-T1/documents/1.pdf"
    doc.save()
    if text is not None:
        DocumentExtraction.objects.create(document=doc, extracted_text=text, engine="ocr")
    if by == "rules":
        DocumentClassification.objects.create(
            document=doc, ai_classification=document_type, rule_score=20,
            status=RULE_CLASSIFIED if document_type != NOT_CLASSIFIED else REVIEW_REQUIRED)
    elif by == "human":
        DocumentClassification.objects.create(
            document=doc, human_classification=document_type,
            status=HUMAN_CLASSIFIED)
    elif by == "issued":
        DocumentClassification.objects.create(
            document=doc, classifier=CLASSIFIER_HOSPITAL, status=ISSUED)
    return reload(doc)
def reload(doc):
    return MedicalDocument.objects.get(pk=doc.pk)


RX = "Dr ABC Rx Paracetamol Syrup 5 ml TDS Diagnosis: Viral fever"
LAB = "Laboratory Report Hemoglobin 13.2 g/dL Reference Range 12-16 Glucose Result Normal"
class RulesTests(SimpleTestCase):
    """The hardcoded rules are consistent."""

    def test_every_rule_belongs_to_a_known_type_and_level(self):
        for document_type, levels in classification_rules.DOCUMENT_RULES.items():
            self.assertIn(document_type, DOCUMENT_TYPES)
            self.assertLessEqual(set(levels), set(classification_rules.WEIGHTS))

    def test_every_type_a_rule_can_assign_has_rules_and_the_rest_are_a_persons_choice(self):
        self.assertEqual(set(DOCUMENT_TYPES) - set(classification_rules.DOCUMENT_RULES), {"other", NOT_CLASSIFIED})

    def test_keywords_are_lower_case_and_not_repeated_within_a_type(self):
        for levels in classification_rules.DOCUMENT_RULES.values():
            words = [w for ws in levels.values() for w in ws]
            self.assertTrue(all(w == w.lower() for w in words))
            self.assertEqual(len(words), len(set(words)))

    def test_not_classified_is_a_state_not_a_choice(self):
        self.assertIn(NOT_CLASSIFIED, DOCUMENT_TYPES)
        self.assertNotIn(NOT_CLASSIFIED, CHOOSABLE_TYPES)
        self.assertIn("other", CHOOSABLE_TYPES)

    def test_codes_are_lower_case_snake_case(self):
        self.assertTrue(all(code == code.lower() and " " not in code for code in DOCUMENT_TYPES))
class EngineTests(SimpleTestCase):
    def test_text_is_normalised(self):
        self.assertEqual(classification_rules.normalize_text("  Lab\n\n  REPORT\t"), "lab report")
        self.assertEqual(classification_rules.normalize_text(None), "")

    def test_keywords_match_whole_words_only(self):
        self.assertEqual(classification_rules.calculate_document_scores("xerox copy")["prescription"]["score"], 0)       # "rx" is not in "xerox"
        self.assertEqual(classification_rules.calculate_document_scores("billion")["medical_bill"]["score"], 0)          # "bill no"/"bill" not "billion"
        self.assertEqual(classification_rules.calculate_document_scores("500mg")["prescription"]["score"], 3)            # a unit glued to a number counts

    def test_a_phrase_the_ocr_ran_together_still_matches(self):
        glued = classification_rules.calculate_document_scores("ReferenceRange")["lab_report"]
        self.assertEqual([m["keyword"] for m in glued["matched_rules"]], ["reference range"])
        self.assertEqual(glued["score"], 10)
        # a single word is never found inside a longer one, even when the text is squashed
        self.assertEqual(classification_rules.calculate_document_scores("abnormality")["lab_report"]["score"], 0)

    def test_a_unit_is_not_a_dose_and_a_ref_doctor_line_is_not_a_prescriber(self):
        scores = classification_rules.calculate_document_scores("Haemoglobin 13.6 mg/dL\nRef. Doctor : Dr. A. Rao MBBS\nSodium 140 mmol/L")["prescription"]
        self.assertEqual(scores["score"], 0)
        self.assertEqual(classification_rules.calculate_document_scores("Tab Metformin 500 mg")["prescription"]["score"], 6)      # tab + mg

    def test_weights_are_ten_three_and_one(self):
        scores = classification_rules.calculate_document_scores(RX)["prescription"]
        levels = {m["keyword"]: m["weight"] for m in scores["matched_rules"]}
        self.assertEqual(levels, {"rx": 10, "syrup": 3, "ml": 3, "tds": 3, "diagnosis": 1, "dr": 1})
        self.assertEqual(scores["score"], 21)

    def test_a_keyword_counts_once_however_often_it_appears(self):
        self.assertEqual(classification_rules.calculate_document_scores("rx rx rx rx")["prescription"]["score"], 10)

    def test_a_clear_winner_is_classified(self):
        result = classification_rules.classify_document_by_rules(RX)
        self.assertEqual((result["document_type"], result["status"], result["best_guess"]),
                         ("prescription", RULE_CLASSIFIED, "prescription"))
        self.assertEqual((result["score"], result["second_best_score"], result["score_margin"]), (21, 1, 20))
        self.assertTrue(result["matched_rules"])

    def test_a_lab_report_is_classified(self):
        result = classification_rules.classify_document_by_rules(LAB)
        self.assertEqual((result["document_type"], result["status"]), ("lab_report", RULE_CLASSIFIED))

    def test_a_tie_needs_a_person(self):
        result = classification_rules.classify_document_by_rules("discharge summary and invoice")
        self.assertEqual((result["document_type"], result["status"]), (NOT_CLASSIFIED, REVIEW_REQUIRED))
        self.assertEqual((result["score"], result["score_margin"]), (13, 3))           # discharge summary 10 + discharge 3, against invoice 10
        self.assertEqual(result["best_guess"], "discharge_summary")          # what it came closest to, for the reviewer

    def test_weak_words_alone_never_classify(self):
        result = classification_rules.classify_document_by_rules("diagnosis follow up advice")
        self.assertEqual((result["document_type"], result["status"]), (NOT_CLASSIFIED, REVIEW_REQUIRED))

    def test_a_winner_must_lead_by_the_margin(self):
        # prescription 26 (rx, prescription, tablet, syrup) against medical_bill 23 (invoice, tax invoice, gst):
        result = classification_rules.classify_document_by_rules("rx prescription tablet syrup invoice tax invoice gst")
        self.assertEqual((result["score"], result["second_best_score"], result["score_margin"]), (26, 23, 3))
        self.assertLess(result["score_margin"], classification_rules.MIN_MARGIN)
        self.assertEqual((result["document_type"], result["best_guess"]), (NOT_CLASSIFIED, "prescription"))
        # a strong and two medium words more on the bill's side and it leads by 13: classified ("subtotal" also matches the phrase "sub total")
        clear = classification_rules.classify_document_by_rules("rx prescription tablet syrup invoice tax invoice gst discount subtotal net payable")
        self.assertEqual((clear["score_margin"], clear["document_type"]), (13, "medical_bill"))

    def test_text_with_no_match_is_not_classified_with_no_guess(self):
        result = classification_rules.classify_document_by_rules("hello world")
        self.assertEqual((result["document_type"], result["status"], result["best_guess"], result["score"]),
                         (NOT_CLASSIFIED, REVIEW_REQUIRED, "", 0))
        self.assertEqual(classification_rules.classify_document_by_rules("")["document_type"], NOT_CLASSIFIED)

    def test_other_is_never_assigned_by_the_rules(self):
        for text in (RX, LAB, "hello", "diagnosis"):
            self.assertNotEqual(classification_rules.classify_document_by_rules(text)["document_type"], "other")
class StoreTests(TestCase):
    databases = {"default"}

    def test_the_rules_verdict_is_recorded_on_the_classification_and_the_document(self):
        doc = make_doc(status="classifying")
        result = classification_rules.classify_document_by_rules(RX)
        classification = classification_rules.store_rule_result(doc, result)
        self.assertEqual(doc.doc_classification, "prescription")
        self.assertEqual((classification.classifier, classification.ai_classification, classification.document.doc_classification,
                          classification.status), ("rule_engine", "prescription", "prescription", "rule_classified"))
        self.assertEqual((classification.rule_score, classification.second_best_score), (21, 1))
        self.assertEqual({m["keyword"] for m in classification.rule_matches}, {"rx", "syrup", "ml", "tds", "diagnosis", "dr"})

    def test_an_ambiguous_verdict_keeps_what_it_came_closest_to(self):
        doc = make_doc(status="classifying")
        classification = classification_rules.store_rule_result(doc, classification_rules.classify_document_by_rules("discharge summary and invoice"))
        self.assertEqual((doc.doc_classification, classification.ai_classification, classification.document.doc_classification,
                          classification.status), (NOT_CLASSIFIED, "discharge_summary", NOT_CLASSIFIED, REVIEW_REQUIRED))

    def test_running_the_rules_again_updates_the_same_row(self):
        doc = make_doc(status="classifying")
        classification_rules.store_rule_result(doc, classification_rules.classify_document_by_rules("hello"))
        classification_rules.store_rule_result(doc, classification_rules.classify_document_by_rules(RX))
        self.assertEqual(DocumentClassification.objects.filter(document=doc).count(), 1)
        self.assertEqual(doc.doc_classification, "prescription")

    def test_a_persons_choice_is_never_overwritten_by_the_rules(self):
        doc = make_doc(status="classifying")
        classification_rules.store_human_choice(doc, "imaging_report")
        doc.save()
        classification_rules.store_rule_result(doc, classification_rules.classify_document_by_rules(RX))
        row = DocumentClassification.objects.get(document=doc)
        self.assertEqual((row.status, row.document.doc_classification, row.human_classification),
                         (HUMAN_CLASSIFIED, "imaging_report", "imaging_report"))
        self.assertEqual(doc.doc_classification, "imaging_report")

    def test_a_person_can_only_choose_a_real_type(self):
        doc = make_doc()
        for bad in ("made_up", NOT_CLASSIFIED, "LAB_REPORT", ""):
            with self.assertRaises(ValueError):
                classification_rules.store_human_choice(doc, bad)

    def test_a_hospital_issued_type_is_kept_and_an_unknown_one_becomes_other(self):
        doc = make_doc()
        classification_rules.store_issued_type(doc, "lab_report")
        row = DocumentClassification.objects.get(document=doc)
        self.assertEqual((doc.doc_classification, row.classifier, row.status), ("lab_report", CLASSIFIER_HOSPITAL, ISSUED))
        classification_rules.store_issued_type(doc, "something_new")
        self.assertEqual(doc.doc_classification, "other")

    def test_the_rules_never_replace_an_issued_type(self):
        doc = make_doc()
        classification_rules.store_issued_type(doc, "prescription")
        classification_rules.store_rule_result(doc, classification_rules.classify_document_by_rules(LAB))
        self.assertEqual(doc.doc_classification, "prescription")

    def test_the_documents_method_score_and_best_guess_follow_its_classification(self):
        doc = make_doc(status="completed", document_type="lab_report", by="rules")
        self.assertEqual((classification_rules.method_of(doc), classification_rules.score_of(doc), classification_rules.best_guess_of(doc)), ("rule", 20, ""))
        guess = make_doc(status="review_required", by="rules")
        DocumentClassification.objects.filter(document=guess).update(ai_classification="lab_report")
        self.assertEqual((classification_rules.method_of(reload(guess)), classification_rules.best_guess_of(reload(guess))), ("rule", "lab_report"))
        self.assertEqual(classification_rules.method_of(make_doc(status="completed", document_type="other", by="human")), "staff")
        self.assertEqual(classification_rules.method_of(make_doc(status="completed", document_type="prescription", by="issued")), "staff")
        self.assertEqual(classification_rules.method_of(make_doc(status="queued")), "")
        self.assertEqual(classification_rules.text_of(make_doc(text="hello")), "hello")
        self.assertEqual(classification_rules.text_of(make_doc()), "")


class InternalNoteViewTests(TestCase):
    databases = {"default"}

    def setUp(self):
        identity("AWP-T1")
        self.enc = uuid.uuid4()
        self.sess = ConsultSession.objects.create(patient=identity("AWP-T1"), hospital=ensure_hospital(3), encounter_id=self.enc,
                                                  note_pdf="patients/AWP-T1/consult-notes/n.pdf")

    def get(self, role="doctor", hospital_id=3, enc=None, **params):
        request = APIRequestFactory().get("/x/", params)
        force_authenticate(request, user=MockUser({"user_id": 1, "role": role}))
        request.hospital_id = hospital_id
        return EncounterInternalNoteView.as_view()(request, pk=enc or self.enc)

    @mock.patch("core.storage.signed_url", return_value="https://s3/signed")
    def test_a_doctor_of_the_hospital_opens_the_note(self, signed):
        resp = self.get()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual((resp.data["data"]["file_data"], resp.data["data"]["mime_type"]), ("https://s3/signed", "application/pdf"))
        signed.assert_called_once_with("patients/AWP-T1/consult-notes/n.pdf", download_name=None)

    @mock.patch("core.storage.signed_url", return_value="https://s3/signed")
    def test_the_download_variant_asks_for_an_attachment(self, signed):
        self.get(download="1")
        self.assertEqual(signed.call_args.kwargs["download_name"], "Handwritten Consultation Note.pdf")

    def test_another_hospital_cannot_open_it(self):
        self.assertEqual(self.get(hospital_id=99).status_code, 404)

    def test_only_a_doctor_can(self):
        for role in ("patient", "nurse", "front_desk"):
            self.assertEqual(self.get(role=role).status_code, 403, role)

    def test_a_visit_without_a_note_has_nothing_to_open(self):
        self.assertEqual(self.get(enc=uuid.uuid4()).status_code, 404)

    def test_the_note_is_never_one_of_the_patients_documents(self):
        self.assertEqual(MedicalDocument.objects.count(), 0)


class IssuedDocumentTests(TestCase):
    databases = {"default"}

    def setUp(self):
        ensure_hospital(3)

    def test_a_hospital_issued_document_is_stored_typed_and_complete_with_what_is_printed_on_it(self):
        identity("AWP-T1")
        doc = records.create_issued_document(
            awpid="AWP-T1", file_path="patients/AWP-T1/prescriptions/x.pdf", name="Prescription RX-000123 — 2026-09-12.pdf",
            doc_type="prescription", source_hospital_id=3, source_type="encounter", source_id=uuid.UUID(int=9), public_document_id="RX-000123",
            document_date=datetime.date(2026, 9, 12))
        self.assertEqual((doc.status, doc.doc_classification, doc.created_by_type), ("completed", "prescription", "H"))
        self.assertEqual((doc.document_ref_name, doc.document_date, doc.source_hospital_id, f"{doc.source_type}:{doc.source_id}"),
                         ("RX-000123", datetime.date(2026, 9, 12), 3, f"encounter:{uuid.UUID(int=9)}"))
        self.assertEqual((doc.patient.awpid, doc.file_name.name), ("AWP-T1", "patients/AWP-T1/prescriptions/x.pdf"))

    def test_the_file_is_the_one_already_in_the_bucket(self):
        identity("AWP-T1")
        doc = records.create_issued_document(awpid="AWP-T1", file_path="patients/AWP-T1/lab-reports/r.pdf", name="r.pdf",
                                              doc_type="lab_report", source_hospital_id=3, source_type="lab_report", source_id="1")
        self.assertEqual((doc.file_name.name, doc.document_ref_name), ("patients/AWP-T1/lab-reports/r.pdf", "r.pdf"))

    def test_a_long_name_is_cut_to_fit(self):
        identity("AWP-T1")
        doc = records.create_issued_document(awpid="AWP-T1", file_path="p", name="x" * 150 + ".pdf", doc_type="other",
                                              source_hospital_id=3, source_type="encounter", source_id="x")
        self.assertEqual(len(doc.document_ref_name), 50)

    def test_it_skips_the_rules_and_records_that_the_hospital_chose_the_type(self):
        identity("AWP-T1")
        doc = records.create_issued_document(awpid="AWP-T1", file_path="p", name="x.pdf", doc_type="lab_report",
                                              source_hospital_id=3, source_type="lab_report", source_id="1")
        c = DocumentClassification.objects.get(document=doc)
        self.assertEqual((c.classifier, c.status, c.document.doc_classification, c.rule_score), ("hospital", "issued", "lab_report", None))

    def test_a_type_that_is_not_one_of_the_fixed_types_becomes_other(self):
        identity("AWP-T1")
        doc = records.create_issued_document(awpid="AWP-T1", file_path="p", name="x.pdf", doc_type="vaccination_card",
                                              source_hospital_id=3, source_type="encounter", source_id="x")
        self.assertEqual(doc.doc_classification, "other")
class PatientLinkTests(TestCase):
    databases = {"default"}

    def test_a_document_and_a_batch_need_a_real_patient(self):
        for create in (lambda: DocumentBatch.objects.create(patient_id=999999),
                       lambda: MedicalDocument.objects.create(patient_id=999999, file_name="x")):
            with self.assertRaises(IntegrityError), transaction.atomic():
                create()
                connection.check_constraints()

    def test_a_document_and_its_text_and_classification_go_with_the_patient(self):
        """The patient link is a cascade: remove the patient and everything filed under them goes too."""
        patient = identity("AWP-T1")
        make_doc(text="some text", by="rules")
        patient.delete()
        self.assertEqual(MedicalDocument.objects.count(), 0)
        self.assertEqual(DocumentClassification.objects.count(), 0)

    def test_a_documents_patient_is_reached_through_the_link(self):
        doc = make_doc("AWP-T1")
        self.assertEqual(MedicalDocument.objects.filter(patient__awpid="AWP-T1").get().id, doc.id)
        self.assertEqual(MedicalDocument.objects.filter(patient__awpid="NOBODY").count(), 0)


S = MedicalDocument.Status
LONG_AGO = "2000-01-01T00:00:00+00:00"
RESOLVE_RECORDS = mock.patch("apps.documents.views.resolve_target_awpid_and_dob", return_value=("AWP-T1", None, None))
RESOLVE_PORTAL = mock.patch("apps.patients.views.resolve_target_awpid_and_dob", return_value=("AWP-T1", None, None))
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
        self.assertEqual([t["code"] for t in data], list(CHOOSABLE_TYPES))
        self.assertNotIn("not_classified", [t["code"] for t in data])
        self.assertEqual({"code": "lab_report", "label": "Lab Report"}, next(t for t in data if t["code"] == "lab_report"))
        self.assertEqual(len(data), 10)
@RESOLVE_RECORDS
@mock.patch("apps.documents.views.start_processing")
@mock.patch("apps.documents.lib_documents.storage")
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
        self.assertEqual((doc.doc_classification, classification_rules.method_of(doc), classification_rules.is_confirmed(doc)), ("prescription", "staff", True))
        classification = doc.d_classification
        self.assertEqual((classification.status, classification.human_classification, classification.document.doc_classification,
                          classification.ai_classification), ("human_classified", "prescription", "prescription", "lab_report"))

    def test_confirming_the_suggestion_also_locks_it(self, _r):
        doc = reviewable("lab_report")
        self.submit((doc.id, "lab_report"))
        self.assertTrue(classification_rules.is_confirmed(reload(doc)))

    def test_a_file_the_rules_could_not_place_can_be_filed_by_the_person(self, _r):
        doc = reviewable(NOT_CLASSIFIED, status="review_required")
        self.assertEqual(self.submit((doc.id, "other")).data["data"]["submitted"], [doc.id])
        self.assertEqual((reload(doc).doc_classification, reload(doc).status), ("other", "completed"))

    def test_sending_the_same_list_twice_changes_nothing(self, _r):
        doc = reviewable("lab_report")
        self.submit((doc.id, "prescription"))
        data = self.submit((doc.id, "imaging_report")).data["data"]
        self.assertEqual((data["submitted"], data["rejected"]), ([], [{"document_id": doc.id, "reason": "already_confirmed"}]))
        self.assertEqual(reload(doc).doc_classification, "prescription")

    def test_each_bad_entry_is_reported_without_stopping_the_rest(self, _r):
        good = reviewable("lab_report")
        queued = make_doc("AWP-T1", status="queued")
        failed = make_doc("AWP-T1", status="failed", error_message="boom")
        theirs = make_doc("AWP-OTHER", status="completed", document_type="lab_report", by="rules")
        issued = make_doc("AWP-T1", status="completed", document_type="lab_report", by="issued", created_by_type="H", source_hospital_id="7")
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
        self.assertFalse(classification_rules.is_confirmed(reload(theirs)))

    def test_an_empty_or_oversized_list_is_refused_as_a_whole(self, _r):
        self.assertEqual(self.submit().status_code, 400)
        doc = reviewable()
        self.assertEqual(self.submit(*[(doc.id, "lab_report")] * 101).status_code, 400)

    def test_the_answer_says_how_many_still_wait(self, _r):
        with override_settings(RECORDS_REVIEW_FROM=LONG_AGO):
            a = reviewable()
            reviewable()                       # a second one that stays waiting
            data = self.submit((a.id, "lab_report")).data["data"]
        self.assertEqual(data["counts"], {"awaiting_review": 1})
class LockTests(TestCase):
    databases = {"default"}

    def setUp(self):
        identity("AWP-T1")
        self.acct = create_account(awpid="AWP-T1", full_name="P", mobile="9333333333", password="x")

    def test_a_confirmed_document_cannot_be_changed_again(self):
        doc = reviewable("lab_report")
        records.correct_document(doc, "prescription")
        with self.assertRaises(classification_rules.DocumentLocked):
            records.correct_document(reload(doc), "imaging_report")
        self.assertEqual(reload(doc).doc_classification, "prescription")

    @RESOLVE_PORTAL
    def test_the_patient_gets_a_clear_locked_answer(self, _r):
        doc = reviewable("lab_report")
        records.correct_document(doc, "prescription")
        resp = call(PortalDocumentDetailView, "patch", data={"doc_type": "imaging_report"}, doc_id=doc.id)
        self.assertEqual((resp.status_code, resp.data["errors"]), (409, {"code": "locked"}))
        self.assertEqual(reload(doc).doc_classification, "prescription")

    def test_not_even_a_platform_admin_can_change_it(self):
        doc = reviewable("lab_report")
        records.correct_document(doc, "prescription")
        request = APIRequestFactory().patch("/x/", {"doc_type": "imaging_report"}, format="json")
        force_authenticate(request, user=MockUser({"user_id": 1, "role": "platform_admin", "is_platform": True}))
        with mock.patch("core.api.permissions.IsPlatformAdmin.has_permission", return_value=True):
            resp = DocumentCorrectView.as_view()(request, pk=doc.id)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(reload(doc).doc_classification, "prescription")
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
        records.correct_document(new, "lab_report")
        self.assertEqual(self.listing(review="pending"), [])
        self.assertEqual(self.listing(), [new.id])

    def test_documents_from_before_the_review_step_never_need_review(self, _r):
        legacy = self.old(reviewable("lab_report"))
        self.assertEqual(self.listing(review="pending"), [])
        self.assertEqual(self.listing(), [legacy.id])
        self.assertFalse(classification_rules.is_confirmed(legacy))              # they keep working as before, just not locked

    def test_hospital_issued_and_staff_documents_never_need_review(self, _r):
        issued = make_doc("AWP-T1", status="completed", document_type="prescription", by="issued", created_by_type="H", source_hospital_id="7")
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
        self.old(reviewable(NOT_CLASSIFIED, status="review_required"))
        reviewable("imaging_report")                                    # new and unconfirmed: waiting, not counted as a type
        reviewable(NOT_CLASSIFIED, status="review_required")
        make_doc("AWP-T1", status="queued")                              # still being read: not reviewable yet
        data = call(PortalDocumentCountsView, "get").data["data"]
        self.assertEqual(set(data["by_type"]), set(CHOOSABLE_TYPES))
        self.assertEqual((data["by_type"]["lab_report"], data["by_type"]["prescription"], data["by_type"]["imaging_report"]), (2, 1, 0))
        self.assertEqual((data["total"], data["unclassified"], data["awaiting_review"]), (4, 1, 2))

    def test_a_row_carries_the_suggestion_the_score_and_whether_it_is_locked(self, _r):
        doc = reviewable("lab_report")
        row = call(PortalDocumentListCreateView, "get", data={"review": "pending"}).data["results"][0]
        self.assertEqual((row["suggested_type"], row["score"], row["confirmed"]), ("lab_report", 20, False))
        self.assertNotIn("best_guess", row)
        records.correct_document(doc, "lab_report")
        row = call(PortalDocumentListCreateView, "get").data["results"][0]
        self.assertEqual((row["suggested_type"], row["confirmed"], row["doc_type"]), (None, True, "lab_report"))
class BatchProgressTests(TestCase):
    databases = {"default"}

    @RESOLVE_RECORDS
    def test_the_batch_reports_how_far_it_has_got(self, _r):
        batch = DocumentBatch.objects.create(patient=identity("AWP-T1"))
        for status in ("completed", "review_required", "failed", "extracting"):
            make_doc("AWP-T1", status=status, batch=batch)
        data = call(BatchDetailView, "get", batch_id=batch.id).data["data"]
        self.assertEqual((data["progress_percent"], data["total_files"]), (75, 4))
        self.assertEqual(data["counts"]["extracting"], 1)
        self.assertNotIn("second_best_score", str(data))


S = MedicalDocument.Status
RX = "Dr ABC Rx Paracetamol Syrup 5 ml TDS Diagnosis: Viral fever"
def row(doc):
    return MedicalDocument.objects.get(pk=doc.id)
def classification(doc):
    return DocumentClassification.objects.get(document_id=doc.id)
@mock.patch("core.storage.get_bytes", return_value=PDF)
class ExtractDocumentTests(TestCase):
    """Stage 1: file → content check → text, then hand off to classification."""
    databases = {"default"}

    @mock.patch("apps.documents.tasks.classify_document_task.apply_async")
    @mock.patch("apps.documents.lib_documents.extract_text", return_value=("hemoglobin glucose", "pdf_text"))
    def test_success_saves_the_text_and_type_and_queues_classification(self, _extract, delay, _get):
        doc = make_doc(status=S.QUEUED)
        extract_document_task(doc.id)
        doc = row(doc)
        self.assertEqual(doc.status, S.CLASSIFYING)
        text = DocumentExtraction.objects.get(document=doc)
        self.assertEqual((text.extracted_text, text.engine), ("hemoglobin glucose", "pdf_text"))
        delay.assert_called_once_with(args=[doc.id, "bulk"], queue="bulk")

    @mock.patch("apps.documents.tasks.classify_document_task.apply_async")
    @mock.patch("apps.documents.lib_documents.extract_text", return_value=("text", "ocr"))
    def test_the_file_is_read_through_the_file_field(self, _extract, _delay, get):
        doc = make_doc(status=S.QUEUED)
        extract_document_task(doc.id)
        get.assert_called_once_with("patients/AWP-T1/documents/1.pdf")

    @mock.patch("apps.documents.tasks.classify_document_task.apply_async")
    def test_a_file_that_is_not_a_pdf_or_image_fails_at_once_with_a_clear_reason(self, delay, get):
        get.return_value = b"just some text"
        doc = make_doc(status=S.QUEUED)
        extract_document_task(doc.id)                    # no exception: nothing to retry
        self.assertEqual(row(doc).status, S.FAILED)
        self.assertIn("not a valid", row(doc).error_message)
        delay.assert_not_called()

    @mock.patch("apps.documents.tasks.classify_document_task.apply_async")
    def test_an_empty_file_fails_with_a_clear_reason(self, delay, get):
        get.return_value = b""
        doc = make_doc(status=S.QUEUED)
        extract_document_task(doc.id)
        self.assertEqual((row(doc).status, row(doc).error_message), (S.FAILED, "The file is empty."))
        delay.assert_not_called()

    @mock.patch("apps.documents.tasks.classify_document_task.apply_async")
    def test_a_one_pixel_image_fails_with_a_clear_reason_and_is_never_read(self, delay, get):
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new("LA", (1, 1)).save(buf, "PNG")
        get.return_value = buf.getvalue()
        doc = make_doc(status=S.QUEUED)
        with mock.patch("apps.documents.lib_documents.extract_text") as extract:
            extract_document_task(doc.id)
        self.assertEqual(row(doc).status, S.FAILED)
        self.assertIn("1x1 pixels", row(doc).error_message)
        extract.assert_not_called()
        delay.assert_not_called()

    @mock.patch("apps.documents.tasks.classify_document_task.apply_async")
    def test_a_file_over_the_limit_fails(self, delay, _get):
        doc = make_doc(status=S.QUEUED)
        with mock.patch("apps.documents.lib_documents.MAX_FILE_BYTES", 10):
            extract_document_task(doc.id)
        self.assertEqual((row(doc).status, row(doc).error_message), (S.FAILED, "The file is over 250 MB."))
        delay.assert_not_called()

    @mock.patch("apps.documents.tasks.classify_document_task.apply_async")
    @mock.patch("apps.documents.lib_documents.extract_text", side_effect=RuntimeError("OCR crashed"))
    def test_an_unexpected_error_is_raised_so_celery_retries_and_the_document_stays_in_progress(self, _extract, delay, _get):
        doc = make_doc(status=S.QUEUED)
        with self.assertRaises(RuntimeError):
            extract_document_task(doc.id)
        self.assertEqual(row(doc).status, S.EXTRACTING)
        delay.assert_not_called()

    @mock.patch("apps.documents.tasks.classify_document_task.apply_async")
    @mock.patch("apps.documents.lib_documents.extract_text", side_effect=RuntimeError("OCR crashed"))
    def test_when_the_retries_are_used_up_the_document_is_failed_for_the_patient_to_retry(self, _extract, delay, _get):
        doc = make_doc(status=S.QUEUED)
        extract_document_task.apply(args=(doc.id,), retries=extract_document_task.max_retries)   # the last attempt
        self.assertEqual(row(doc).status, S.FAILED)
        self.assertIn("OCR crashed", row(doc).error_message)
        delay.assert_not_called()

    @mock.patch("apps.documents.tasks.classify_document_task.apply_async")
    @mock.patch("apps.documents.lib_documents.extract_text")
    def test_only_a_document_still_in_the_pipeline_is_touched(self, extract, delay, get):
        for status in (S.COMPLETED, S.FAILED, S.REVIEW_REQUIRED):
            doc = make_doc(status=status)
            extract_document_task(doc.id)
            self.assertEqual(row(doc).status, status)
        extract.assert_not_called()
        get.assert_not_called()
        delay.assert_not_called()

    @mock.patch("apps.documents.tasks.classify_document_task.apply_async")
    @mock.patch("apps.documents.lib_documents.extract_text")
    def test_a_retry_after_the_text_was_saved_only_repeats_the_hand_off(self, extract, delay, get):
        doc = make_doc(status=S.CLASSIFYING, text="already read")
        extract_document_task(doc.id)
        get.assert_not_called()
        extract.assert_not_called()
        delay.assert_called_once_with(args=[doc.id, "bulk"], queue="bulk")

    @mock.patch("apps.documents.tasks.classify_document_task.apply_async")
    @mock.patch("apps.documents.lib_documents.extract_text", return_value=("text", "ocr"))
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
        batch = DocumentBatch.objects.create(patient=identity())
        doc = make_doc(status=S.CLASSIFYING, text=RX, batch=batch)
        classify_document_task(doc.id)
        doc = row(doc)
        self.assertEqual((doc.status, doc.doc_classification, doc.error_message), (S.COMPLETED, "prescription", ""))
        c = classification(doc)
        self.assertEqual((c.status, c.document.doc_classification, c.rule_score, c.second_best_score),
                         ("rule_classified", "prescription", 21, 1))
        batch.refresh_from_db()
        self.assertEqual((batch_counts(batch)["processed_files"], batch_counts(batch)["failed_files"], batch_counts(batch)["status"]), (1, 0, "completed"))

    def test_text_the_rules_cannot_place_needs_review(self):
        batch = DocumentBatch.objects.create(patient=identity())
        doc = make_doc(status=S.CLASSIFYING, text="hello world", batch=batch)
        classify_document_task(doc.id)
        doc = row(doc)
        self.assertEqual((doc.status, doc.doc_classification), (S.REVIEW_REQUIRED, "not_classified"))
        self.assertEqual(classification(doc).status, "review_required")
        batch.refresh_from_db()
        self.assertEqual((batch_counts(batch)["processed_files"], batch_counts(batch)["status"]), (1, "completed"))     # finished, awaiting a person

    def test_a_document_with_no_text_needs_review(self):
        doc = make_doc(status=S.CLASSIFYING)
        classify_document_task(doc.id)
        self.assertEqual((row(doc).status, row(doc).doc_classification), (S.REVIEW_REQUIRED, "not_classified"))

    def test_a_persons_choice_is_not_overwritten_and_the_document_completes(self):
        doc = make_doc(status=S.CLASSIFYING, text=RX, document_type="lab_report", by="human")
        classify_document_task(doc.id)
        doc = row(doc)
        self.assertEqual((doc.status, doc.doc_classification), (S.COMPLETED, "lab_report"))
        self.assertEqual(classification(doc).status, "human_classified")

    def test_only_a_document_being_classified_is_touched(self):
        for status in (S.QUEUED, S.EXTRACTING, S.COMPLETED, S.FAILED, S.REVIEW_REQUIRED):
            doc = make_doc(status=status, text=RX)
            classify_document_task(doc.id)
            self.assertEqual(row(doc).status, status)
            self.assertFalse(DocumentClassification.objects.filter(document=doc).exists())

    @mock.patch("apps.documents.lib_documents.classify_document_by_rules", side_effect=RuntimeError("boom"))
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

    @mock.patch("apps.documents.lib_documents.extract_text", return_value=(RX, "ocr"))
    def test_a_queued_document_ends_completed_with_its_text_and_classification(self, _extract, _get):
        batch = DocumentBatch.objects.create(patient=identity())
        doc = make_doc(status=S.QUEUED, batch=batch)
        with mock.patch("apps.documents.tasks.classify_document_task.apply_async",
                        side_effect=lambda args, queue: classify_document_task(*args)):
            extract_document_task(doc.id)
        doc = row(doc)
        self.assertEqual((doc.status, doc.doc_classification, classification_rules.method_of(doc), classification_rules.score_of(doc)), (S.COMPLETED, "prescription", "rule", 21))
        self.assertEqual(classification_rules.text_of(doc), RX)
        batch.refresh_from_db()
        self.assertEqual((batch_counts(batch)["processed_files"], batch_counts(batch)["status"]), (1, "completed"))
class StartProcessingTests(TestCase):
    databases = {"default"}

    @mock.patch("apps.documents.tasks.extract_document_task.apply_async")
    def test_each_document_is_queued(self, delay):
        a, b = make_doc(), make_doc()
        records.start_processing([a.id, b.id])
        self.assertEqual([c.kwargs for c in delay.call_args_list],
                         [{"args": [a.id, "bulk"], "queue": "bulk"}, {"args": [b.id, "bulk"], "queue": "bulk"}])

    @mock.patch("apps.documents.tasks.extract_document_task.apply_async")
    def test_an_instant_document_is_queued_on_the_instant_queue(self, delay):
        a = make_doc()
        records.start_processing([a.id], records.INSTANT_QUEUE)
        delay.assert_called_once_with(args=[a.id, "instant"], queue="instant")

    @mock.patch("apps.documents.tasks.classify_document_task.apply_async")
    @mock.patch("apps.documents.lib_documents.extract_text", return_value=("text", "ocr"))
    @mock.patch("core.storage.get_bytes", return_value=PDF)
    def test_the_classify_step_stays_on_the_queue_of_its_extract_step(self, _get, _extract, classify):
        doc = make_doc(status=S.QUEUED)
        extract_document_task(doc.id, "instant")
        classify.assert_called_once_with(args=[doc.id, "instant"], queue="instant")

    @mock.patch("apps.documents.tasks.extract_document_task.apply_async", side_effect=ConnectionError("broker down"))
    def test_when_the_queue_is_unreachable_the_documents_fail_so_the_patient_can_retry(self, _delay):
        batch = DocumentBatch.objects.create(patient=identity())
        doc = make_doc(batch=batch)
        records.start_processing([doc.id])
        self.assertEqual(row(doc).status, S.FAILED)
        self.assertIn("Couldn't start processing", row(doc).error_message)
        batch.refresh_from_db()
        self.assertEqual((batch_counts(batch)["failed_files"], batch_counts(batch)["status"]), (1, "completed_with_errors"))
class CorrectionTests(TestCase):
    databases = {"default"}

    def test_a_person_files_a_document_that_needs_review(self):
        doc = make_doc(status=S.REVIEW_REQUIRED, by="rules")
        records.correct_document(doc, "lab_report")
        doc = row(doc)
        self.assertEqual((doc.status, doc.doc_classification, classification_rules.method_of(doc)), (S.COMPLETED, "lab_report", "staff"))
        c = classification(doc)
        self.assertEqual((c.human_classification, c.document.doc_classification, c.status), ("lab_report", "lab_report", "human_classified"))

    def test_a_person_can_change_the_type_the_rules_chose(self):
        doc = make_doc(status=S.COMPLETED, document_type="lab_report", by="rules")
        records.correct_document(doc, "prescription")
        self.assertEqual((row(doc).doc_classification, row(doc).doc_classification), ("prescription", "prescription"))

    def test_a_failed_file_becomes_a_normal_completed_one(self):
        doc = make_doc(status=S.FAILED, error_message="unreadable")
        records.correct_document(doc, "other")
        self.assertEqual((row(doc).status, row(doc).error_message, row(doc).doc_classification), (S.COMPLETED, "", "other"))

    def test_a_file_still_being_read_cannot_be_filed(self):
        for status in (S.QUEUED, S.EXTRACTING, S.CLASSIFYING):
            with self.assertRaises(ValueError):
                records.correct_document(make_doc(status=status), "lab_report")

    def test_only_a_real_type_can_be_chosen(self):
        doc = make_doc(status=S.COMPLETED)
        for bad in ("made_up", "not_classified", "LAB_REPORT"):
            with self.assertRaises(ValueError):
                records.correct_document(doc, bad)

    def test_only_a_failed_file_can_be_retried(self):
        doc = make_doc(status=S.FAILED, error_message="boom")
        records.retry_document(doc)
        self.assertEqual((row(doc).status, row(doc).error_message), (S.QUEUED, ""))
        for status in (S.QUEUED, S.COMPLETED, S.REVIEW_REQUIRED, S.CLASSIFYING):
            with self.assertRaises(ValueError):
                records.retry_document(make_doc(status=status))
class ReclassifyTests(TestCase):
    databases = {"default"}

    def test_the_rules_run_again_over_what_the_rules_classified(self):
        doc = make_doc(status=S.REVIEW_REQUIRED, by="rules", text=RX)
        counts = records.reclassify_existing()
        self.assertEqual(counts, {"checked": 1, "changed": 1, "classified": 1, "unclassified": 0})
        self.assertEqual((row(doc).status, row(doc).doc_classification), (S.COMPLETED, "prescription"))

    def test_a_document_the_rules_now_cannot_place_goes_back_to_review(self):
        doc = make_doc(status=S.COMPLETED, document_type="prescription", by="rules", text="hello world")
        records.reclassify_existing()
        self.assertEqual((row(doc).status, row(doc).doc_classification), (S.REVIEW_REQUIRED, "not_classified"))

    def test_a_persons_choice_and_a_hospital_document_are_never_touched(self):
        human = make_doc(status=S.COMPLETED, document_type="lab_report", by="human", text=RX)
        issued = make_doc(status=S.COMPLETED, document_type="lab_report", by="issued", text=RX, source_hospital_id="3")
        self.assertEqual(records.reclassify_existing()["checked"], 0)
        self.assertEqual((row(human).doc_classification, row(issued).doc_classification), ("lab_report", "lab_report"))

    def test_a_document_without_text_is_skipped(self):
        make_doc(status=S.REVIEW_REQUIRED, by="rules")
        self.assertEqual(records.reclassify_existing()["checked"], 0)
class BatchCounterTests(TestCase):
    databases = {"default"}

    def test_the_batch_counts_follow_its_documents(self):
        batch = DocumentBatch.objects.create(patient=identity())
        make_doc(batch=batch, status=S.COMPLETED, document_type="lab_report", by="rules")
        make_doc(batch=batch, status=S.REVIEW_REQUIRED, by="rules")
        make_doc(batch=batch, status=S.CLASSIFYING)
        make_doc(batch=batch, status=S.FAILED)
        self.assertEqual((batch_counts(batch)["processed_files"], batch_counts(batch)["failed_files"], batch_counts(batch)["status"]), (2, 1, "processing"))
        MedicalDocument.objects.filter(batch=batch, status=S.CLASSIFYING).update(status=S.COMPLETED)
        self.assertEqual((batch_counts(batch)["processed_files"], batch_counts(batch)["status"]), (3, "completed_with_errors"))


def pdf(name="report.pdf", size=None):
    body = PDF if size is None else b"%PDF" + b"x" * (size - 4)
    return SimpleUploadedFile(name, body, content_type="application/pdf")
@mock.patch("apps.documents.views.resolve_target_awpid_and_dob", return_value=("AWP-T1", None, None))
@mock.patch("apps.documents.views.start_processing")
@mock.patch("apps.documents.lib_documents.storage")            # the delete of an uploaded file
@mock.patch("core.storage.put_bytes", side_effect=lambda key, data, mime_type: key)      # the FileField's S3 write
class UploadViewTests(TestCase):
    databases = {"default"}

    def setUp(self):
        identity("AWP-T1")

    def post(self, files):
        request = APIRequestFactory().post("/api/v1/records/upload/", {"files": files}, format="multipart")
        force_authenticate(request, user=MockUser({"user_id": 1, "role": "patient", "awpid": "AWP-T1"}))
        return UploadView.as_view()(request)

    def test_every_upload_gets_a_batch_even_for_one_file(self, put, storage, start, _resolve):
        resp = self.post([pdf("a.pdf")])

        self.assertEqual(resp.status_code, 202)
        batch = DocumentBatch.objects.get()
        self.assertEqual((batch.patient.awpid, batch_counts(batch)["total_files"], resp.data["data"]["batch_id"]), ("AWP-T1", 1, batch.id))
        doc = MedicalDocument.objects.get()
        self.assertEqual((doc.status, doc.patient.awpid, doc.document_ref_name, doc.batch_id, doc.doc_classification),
                         ("queued", "AWP-T1", "a.pdf", batch.id, "not_classified"))
        self.assertRegex(doc.file_name.name, r"^patients/AWP-T1/documents/[0-9a-f]{32}\.pdf$")
        start.assert_called_once_with([doc.id], "instant")

    def test_the_file_goes_to_s3_through_the_file_field(self, put, storage, start, _resolve):
        from django.core.files.storage import default_storage
        self.post([pdf("a.pdf")])
        doc = MedicalDocument.objects.get()
        with default_storage.open(doc.file_name.name) as stored:           # the FileField wrote it to the default storage
            self.assertEqual(stored.read(), PDF)

    def test_several_files_share_one_batch_and_one_folder_and_are_all_queued(self, put, storage, start, _resolve):
        resp = self.post([pdf("a.pdf"), pdf("b.pdf"), pdf("c.pdf")])

        self.assertEqual(resp.status_code, 202)
        batch = DocumentBatch.objects.get()
        self.assertEqual(batch_counts(batch)["total_files"], 3)
        docs = MedicalDocument.objects.filter(batch=batch)
        self.assertEqual(docs.count(), 3)
        self.assertTrue(all(d.file_name.name.startswith("patients/AWP-T1/documents/") for d in docs))
        self.assertEqual(len(resp.data["data"]["documents"]), 3)
        start.assert_called_once_with([d.id for d in docs.order_by("id")], "bulk")

    def test_a_long_file_name_is_cut_to_fit(self, put, storage, start, _resolve):
        self.post([SimpleUploadedFile("x" * 150 + ".pdf", PDF, content_type="application/pdf")])
        self.assertEqual(len(MedicalDocument.objects.get().document_ref_name), 50)

    def test_the_content_is_not_checked_at_the_door(self, put, storage, start, _resolve):
        """A bad file is accepted and fails later in the extraction job, so it never blocks the others."""
        resp = self.post([pdf("ok.pdf"), SimpleUploadedFile("notes.pdf", b"hello", content_type="application/pdf")])
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(MedicalDocument.objects.count(), 2)

    def test_an_unknown_extension_is_stored_as_bin_and_never_trusted_as_a_content_type(self, put, storage, start, _resolve):
        self.post([SimpleUploadedFile("evil.html", b"<html>", content_type="text/html")])
        self.assertTrue(MedicalDocument.objects.get().file_name.name.endswith(".bin"))

    def test_one_oversize_file_rejects_everything_before_s3(self, put, storage, start, _resolve):
        with mock.patch("apps.documents.serializers.MAX_FILE_BYTES", 150):
            resp = self.post([pdf("ok.pdf"), pdf("big.pdf", size=200)])

        self.assertEqual(resp.status_code, 400)
        put.assert_not_called()
        start.assert_not_called()
        self.assertEqual(MedicalDocument.objects.count(), 0)

    def test_an_empty_file_rejects_everything_before_s3(self, put, storage, start, _resolve):
        resp = self.post([pdf("ok.pdf"), SimpleUploadedFile("empty.pdf", b"", content_type="application/pdf")])
        self.assertEqual(resp.status_code, 400)
        self.assertIn("empty", str(resp.data))
        put.assert_not_called()
        self.assertEqual(MedicalDocument.objects.count(), 0)

    def test_total_over_250mb_is_rejected(self, put, storage, start, _resolve):
        with mock.patch("apps.documents.serializers.MAX_TOTAL_BYTES", 150):
            resp = self.post([pdf("a.pdf"), pdf("b.pdf")])        # 2 × 109 bytes > 150
        self.assertEqual(resp.status_code, 400)
        put.assert_not_called()

    def test_more_than_50_files_is_rejected(self, put, storage, start, _resolve):
        with mock.patch("apps.documents.serializers.MAX_FILES", 2):
            resp = self.post([pdf("a.pdf"), pdf("b.pdf"), pdf("c.pdf")])
        self.assertEqual(resp.status_code, 400)
        put.assert_not_called()
        self.assertEqual(MedicalDocument.objects.count(), 0)

    def test_an_s3_failure_part_way_saves_nothing_and_deletes_what_was_sent(self, put, storage, start, _resolve):
        from django.core.files.storage import InMemoryStorage
        sent, real_save = [], InMemoryStorage._save

        def flaky(storage_self, name, content):
            sent.append(name)
            if len(sent) == 2:
                raise RuntimeError("S3 down")
            return real_save(storage_self, name, content)

        with mock.patch.object(InMemoryStorage, "_save", flaky):
            resp = self.post([pdf("a.pdf"), pdf("b.pdf")])

        self.assertEqual(resp.status_code, 503)
        self.assertEqual((MedicalDocument.objects.count(), DocumentBatch.objects.count()), (0, 0))
        deleted = [call.args[0] for call in storage.delete.call_args_list]
        self.assertEqual(len(deleted), 1)                    # the one that was sent is cleaned up
        self.assertTrue(deleted[0].startswith("patients/AWP-T1/documents/"))
        start.assert_not_called()

    def test_files_are_sent_to_s3_at_the_same_time(self, put, storage, start, _resolve):
        import threading
        import time
        from django.core.files.storage import InMemoryStorage
        active, peak, lock, real_save = 0, 0, threading.Lock(), InMemoryStorage._save

        def slow_save(storage_self, name, content):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return real_save(storage_self, name, content)

        with mock.patch.object(InMemoryStorage, "_save", slow_save):
            resp = self.post([pdf(f"{i}.pdf") for i in range(6)])
        self.assertEqual(resp.status_code, 202)
        self.assertGreater(peak, 1)
        self.assertEqual(MedicalDocument.objects.count(), 6)
@mock.patch("apps.documents.views.resolve_target_awpid_and_dob", return_value=("AWP-T1", None, None))
class BatchDetailViewTests(TestCase):
    """The batch first, then its documents."""
    databases = {"default"}

    def get(self, batch_id):
        request = APIRequestFactory().get(f"/api/v1/records/batches/{batch_id}/")
        force_authenticate(request, user=MockUser({"user_id": 1, "role": "patient", "awpid": "AWP-T1"}))
        return BatchDetailView.as_view()(request, batch_id=batch_id)

    def test_returns_the_batch_counts_and_each_document(self, _resolve):
        identity("AWP-T1")
        batch = DocumentBatch.objects.create(patient=identity("AWP-T1"))
        make_doc(batch=batch, status="completed", document_type="lab_report", by="rules", name="a.pdf")
        make_doc(batch=batch, status="queued", name="b.pdf")
        make_doc(batch=batch, status="review_required", by="rules", name="c.pdf")

        data = self.get(batch.id).data["data"]
        self.assertEqual((data["id"], data["total_files"], data["status"]), (batch.id, 3, "processing"))
        self.assertEqual({k: v for k, v in data["counts"].items() if v},
                         {"completed": 1, "queued": 1, "review_required": 1})
        self.assertEqual([(d["file_name"], d["status"], d["processing_status"], d["doc_type"]) for d in data["documents"]],
                         [("a.pdf", "completed", "completed", "lab_report"),
                          ("b.pdf", "queued", "queued", "not_classified"),
                          ("c.pdf", "review_required", "review_required", "not_classified")])

    def test_a_batch_is_complete_when_every_document_is_in_a_final_state(self, _resolve):
        identity("AWP-T1")
        batch = DocumentBatch.objects.create(patient=identity("AWP-T1"))
        make_doc(batch=batch, status="completed", document_type="imaging_report", by="rules")
        make_doc(batch=batch, status="review_required", by="rules")
        make_doc(batch=batch, status="failed")
        self.assertEqual((batch_counts(batch)["processed_files"], batch_counts(batch)["failed_files"], batch_counts(batch)["status"]), (2, 1, "completed_with_errors"))
        self.assertEqual(records.batch_summary(batch)["status"], "completed")

    def test_someone_elses_batch_is_not_found(self, _resolve):
        batch = DocumentBatch.objects.create(patient=identity("AWP-OTHER"))
        self.assertEqual(self.get(batch.id).status_code, 404)
@mock.patch("apps.documents.views.start_processing")
@mock.patch("apps.documents.lib_documents.storage")
@mock.patch("core.storage.put_bytes", side_effect=lambda key, data, mime_type: key)
class UploadForWhomTests(TestCase):
    """"Who is this for?" on the phone sends patient_awpid with the upload. The family link is checked for real here (the"""
    databases = {"default"}

    def setUp(self):
        from apps.patients.models import PatientRelationship
        self.acct = create_account(awpid="AWP-ME", full_name="Me", mobile="9333333331", password="x")
        identity("AWP-ME")
        identity("AWP-KID")
        identity("AWP-STRANGER")
        PatientRelationship.objects.using("default").create(guardian=identity("AWP-ME"), dependent=identity("AWP-KID"), relationship="child")

    def post(self, awpid=None):
        data = {"files": [pdf("a.pdf")], **({"patient_awpid": awpid} if awpid else {})}
        request = APIRequestFactory().post("/api/v1/records/upload/", data, format="multipart")
        force_authenticate(request, user=MockUser({"user_id": self.acct.id, "role": "patient", "awpid": "AWP-ME"}))
        return UploadView.as_view()(request)

    def test_with_no_one_chosen_the_upload_is_the_patients_own(self, put, storage, start):
        self.assertEqual(self.post().status_code, 202)
        self.assertEqual(MedicalDocument.objects.get().patient.awpid, "AWP-ME")

    def test_a_linked_family_member_gets_the_upload(self, put, storage, start):
        self.assertEqual(self.post("AWP-KID").status_code, 202)
        doc = MedicalDocument.objects.get()
        self.assertEqual(doc.patient.awpid, "AWP-KID")
        self.assertIn("AWP-KID", doc.file_name.name)

    def test_someone_not_linked_to_the_account_is_refused_and_nothing_is_saved(self, put, storage, start):
        resp = self.post("AWP-STRANGER")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(MedicalDocument.objects.count(), 0)
        put.assert_not_called()
        start.assert_not_called()


def _hospital(db_name, hospital_code, name):
    return Hospital.objects.using("default").create(name=name, hospital_code=hospital_code, db_name=db_name)
class ProvenanceFixtureMixin:
    def make_fixture(self):
        db = self.hospital_alias
        self.hospital = _hospital(db, "hospital-test", "Test Hospital")
        self.branch = Branch.objects.using(db).create(name="Main")
        self.doctor = StaffUser.objects.using(db).create(
            email="dr@example.test", role="doctor", phone="9000000010", branch=self.branch,
        )
        self.patient = HospitalPatient.objects.using(db).create(
            awpid="AW-PROV-1", uhid="UHID-P1", branch=self.branch, full_name="Prov Patient",
        )
        Patient.objects.using("default").get_or_create(awpid="AW-PROV-1", defaults={"full_name": "Prov Patient"})
def _fake_encounter():
    """Only what sync_encounter_to_hie reads: no vitals, no prescription."""
    class NoRx:
        def __getattr__(self, name):
            raise AttributeError(name)

    enc = NoRx()
    enc.id = "enc-1"
    enc.diagnoses = [{"code": "J06.9", "description": "Acute URI"}]
    enc.appointment = SimpleNamespace(vitals=None)
    return enc
@requires_hospital_db
class SyncToHieTests(ProvenanceFixtureMixin, HospitalDBTestCase):
    def test_uses_the_hospital_id_it_is_given(self):
        self.make_fixture()
        sync_encounter_to_hie(_fake_encounter(), self.hospital_alias, self.patient, hospital_id=self.hospital.id)
        self.assertEqual(ClinicalEvent.objects.using("default").get().source_hospital_id, self.hospital.id)

    def test_resolves_the_hospital_from_the_db_alias_when_not_given(self):
        self.make_fixture()
        sync_encounter_to_hie(_fake_encounter(), self.hospital_alias, self.patient)
        self.assertEqual(ClinicalEvent.objects.using("default").get().source_hospital_id, self.hospital.id)

    def test_two_hospitals_do_not_overwrite_each_others_rows(self):
        """With both stamped 0 the update_or_create key (awpid, hospital, ICD code) collapsed to one row."""
        self.make_fixture()
        ensure_hospital(11)
        ensure_hospital(22)
        sync_encounter_to_hie(_fake_encounter(), self.hospital_alias, self.patient, hospital_id=11)
        sync_encounter_to_hie(_fake_encounter(), self.hospital_alias, self.patient, hospital_id=22)
        rows = ClinicalEvent.objects.using("default").order_by("source_hospital_id")
        self.assertEqual([r.source_hospital_id for r in rows], [11, 22])
@requires_hospital_db
class AllergySignalTests(ProvenanceFixtureMixin, HospitalDBTestCase):
    def test_shared_allergy_carries_the_hospital_id(self):
        self.make_fixture()
        Allergy.objects.using(self.hospital_alias).create(patient=self.patient, substance="Penicillin")
        self.assertEqual(SharedAllergy.objects.using("default").get().source_hospital_id, self.hospital.id)
@requires_hospital_db
class LabHospitalIdTests(ProvenanceFixtureMixin, HospitalDBTestCase):
    def make_lab_request(self):
        db = self.hospital_alias
        test = LabTest.objects.using(db).create(name="CBC")
        doctor_uuid = uuid.uuid4()
        appt = Appointment.objects.using(db).create(
            patient_id=self.patient.uuid, patient_awpid=self.patient.awpid, doctor_user_id=doctor_uuid,
            doctor_name="Dr Test", scheduled_date=datetime.date.today(),
        )
        enc = OPDEncounter.objects.using(db).create(
            appointment=appt, patient_id=self.patient.uuid, doctor_user_id=doctor_uuid,
        )
        return LabRequest.objects.using(db).create(
            patient=self.patient, encounter=enc, test=test, requested_by=self.doctor, branch=self.branch,
        )

    def test_delivered_report_mirrors_carry_the_hospital_id(self):
        self.make_fixture()
        req = self.make_lab_request()
        with mock.patch("apps.lab.archive.store_lab_report_document") as archive:
            LabReport.objects.using(self.hospital_alias).create(
                request=req, patient=self.patient, report_number="LR-1",
                status="delivered", delivered_at=timezone.now(), result_summary="ok",
            )
        self.assertEqual(LabResult.objects.using("default").get().source_hospital_id, self.hospital.id)
        self.assertEqual(archive.call_args.args[2], self.hospital.id)   # the vault-mirror gets it too

    def test_attach_document_view_stamps_the_request_hospital(self):
        self.make_fixture()
        Patient.objects.using("default").get_or_create(awpid=self.patient.awpid, defaults={"full_name": "Prov"})
        req = self.make_lab_request()
        pdf = "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4\n%test\n").decode()
        with mock.patch("core.storage.upload_data_uri", return_value="patient-documents/x.pdf"):
            resp = self.call_view(
                LabRequestAttachDocumentView.as_view(), "post", "/api/v1/lab/requests/1/attach-document/",
                user_id=self.doctor.id, role="lab_tech", data={"file_data": pdf, "title": "Outside CBC"},
                hospital_id=self.hospital.id, features=("feat_lab",), view_kwargs={"pk": req.pk},
            )
        self.assertLess(resp.status_code, 300, resp.data)
        doc = MedicalDocument.objects.using("default").get(source_type="lab_request")
        self.assertEqual(doc.source_hospital_id, self.hospital.id)


FORM = {"systolic_bp": 110, "diastolic_bp": 70, "pulse_rate": 90, "temperature": Decimal("98.6"),
        "height_cm": Decimal("85"), "weight_kg": Decimal("12"), "head_circumference_cm": Decimal("47"), "nurse_notes": "calm"}
class VisitVitalsTests(TestCase):
    databases = {"default"}

    def setUp(self):
        ensure_hospital(1)
        ensure_hospital(2)
        self.patient = Patient.objects.using("default").create(awpid="AW-V1", full_name="V One")
        self.visit = uuid.uuid4()

    def save(self, data=FORM, *, minor, visit=None):
        return vitals.save_visit(self.patient, visit or self.visit, 1, None, dict(data), is_minor=minor)

    def test_an_adult_visit_is_one_vitals_row_with_height_and_weight(self):
        merged = self.save(minor=False)
        row = Vitals.objects.get()
        self.assertEqual((row.systolic_bp, row.height_cm, row.weight_kg, bmi(row)), (110, Decimal("85.0"), Decimal("12.0"), Decimal("16.6")))
        self.assertFalse(GrowthMeasurement.objects.exists())
        self.assertIsNone(merged.head_circumference_cm)             # an adult's head size is not kept

    def test_a_child_visit_writes_a_row_in_each_table_and_reads_back_as_one(self):
        merged = self.save(minor=True)
        self.assertEqual((Vitals.objects.get().systolic_bp, Vitals.objects.get().height_cm), (110, None))
        growth = GrowthMeasurement.objects.get()
        self.assertEqual((growth.height_cm, growth.weight_kg, growth.head_circumference_cm, growth.measured_on),
                         (Decimal("85.0"), Decimal("12.000"), Decimal("47.0"), dt.date.today()))
        self.assertEqual((merged.systolic_bp, merged.height_cm, merged.weight_kg, merged.head_circumference_cm, merged.nurse_notes),
                         (110, Decimal("85.0"), Decimal("12.000"), Decimal("47.0"), "calm"))

    def test_saving_a_visit_again_updates_it_and_clearing_growth_removes_the_row(self):
        self.save(minor=True)
        self.save({"pulse_rate": 100, "height_cm": None, "weight_kg": None, "head_circumference_cm": None}, minor=True)
        self.assertEqual((Vitals.objects.count(), Vitals.objects.get().pulse_rate, GrowthMeasurement.objects.count()), (1, 100, 0))

    def test_a_visit_with_no_growth_fields_creates_no_growth_row(self):
        self.save({"pulse_rate": 80}, minor=True)
        self.assertFalse(GrowthMeasurement.objects.exists())

    def test_visits_and_their_vitals_are_looked_up_together(self):
        other = uuid.uuid4()
        self.save(minor=True)
        self.save({"pulse_rate": 70}, minor=False, visit=other)
        found = vitals.visits_vitals([self.visit, other, uuid.uuid4()])
        self.assertEqual(set(found), {self.visit, other})
        self.assertEqual(vitals.recorded([self.visit, uuid.uuid4()]), {self.visit})
        self.assertIsNone(vitals.visit_vitals(uuid.uuid4()))

    def test_history_readings_use_the_names_the_history_screens_read(self):
        self.save(minor=True)
        (reading,) = vitals.history_readings("AW-V1")
        self.assertEqual((reading["bp_systolic"], reading["bp_diastolic"], reading["weight_kg"], reading["head_circumference_cm"], reading["source"]),
                         (110, 70, Decimal("12.000"), Decimal("47.0"), "clinic"))
        self.assertNotIn("source_hospital_id", reading)

    def test_growth_points_are_one_per_day_and_say_whose_they_are(self):
        GrowthMeasurement.objects.create(patient=self.patient, measured_on=dt.date(2026, 1, 1), weight_kg=Decimal("10"), source_hospital_id=1)
        GrowthMeasurement.objects.create(patient=self.patient, measured_on=dt.date(2026, 2, 1), weight_kg=Decimal("11"), source_hospital_id=2)
        GrowthMeasurement.objects.create(patient=self.patient, measured_on=dt.date(2026, 3, 1), weight_kg=Decimal("12"), source_hospital_id=1, is_rejected=True)
        GrowthMeasurement.objects.create(patient=self.patient, measured_on=dt.date(2026, 4, 1), source_hospital_id=1)       # nothing measured
        mine = vitals.growth_points("AW-V1", hospital_id=1, include_other=False)
        self.assertEqual([(p["date"], p["source"]) for p in mine], [("2026-01-01", "this_hospital")])
        both = vitals.growth_points("AW-V1", hospital_id=1)
        self.assertEqual([p["source"] for p in both], ["this_hospital", "other_hospital"])
        self.assertEqual([p["source"] for p in vitals.growth_points("AW-V1")], ["clinic", "clinic"])

    def test_an_adults_height_and_weight_also_reach_the_growth_chart(self):
        self.save({"height_cm": Decimal("170"), "weight_kg": Decimal("70")}, minor=False)
        (point,) = vitals.growth_points("AW-V1", hospital_id=1)
        self.assertEqual((point["height_cm"], point["weight_kg"], point["bmi"]), (170.0, 70.0, 24.2))


V = ImmunizationRecord
def value_at_z(measurement, sex, age_months, z):
    """The measurement a child would have to show to sit exactly at z (the formula run backwards)."""
    L, M, S = growth_reference._lms(measurement, sex, age_months)
    return M * (1 + z * L * S) ** (1 / L)
class PercentileTests(SimpleTestCase):
    def test_the_published_median_is_the_50th_percentile(self):
        # WHO median weight for a girl at 12 months is 8.9481 kg (the M column of the table)
        result = growth_reference.get_percentile("weight", "F", 12, 8.9481)
        self.assertEqual((result["z_score"], result["percentile"]), (0.0, 50.0))

    def test_every_checkpoint_median_scores_50(self):
        for measurement, by_sex in growth_reference.REFERENCE_TABLES.items():
            for sex, rows in by_sex.items():
                for age, _L, M, _S in rows:
                    self.assertEqual(growth_reference.get_percentile(measurement, sex, age, M)["percentile"], 50.0, (measurement, sex, age))

    def test_the_3rd_and_97th_percentile_values_score_3_and_97(self):
        # z = -1.881 and +1.881 are the lines WHO draws as the 3rd and 97th percentile curves
        for measurement in growth_reference.MEASUREMENTS:
            for sex in ("M", "F"):
                for age in (0, 6, 18, 36, 60):
                    low = growth_reference.get_percentile(measurement, sex, age, value_at_z(measurement, sex, age, -1.881))["percentile"]
                    high = growth_reference.get_percentile(measurement, sex, age, value_at_z(measurement, sex, age, 1.881))["percentile"]
                    self.assertAlmostEqual(low, 3.0, delta=0.1, msg=(measurement, sex, age))
                    self.assertAlmostEqual(high, 97.0, delta=0.1, msg=(measurement, sex, age))

    def test_a_heavier_child_scores_higher(self):
        scores = [growth_reference.get_percentile("weight", "M", 24, kg)["percentile"] for kg in (9, 10, 11, 12.1515, 13, 14, 16)]
        self.assertEqual(scores, sorted(scores))
        self.assertEqual(scores[3], 50.0)                      # 12.1515 kg is the boys' median at 24 months

    def test_between_two_checkpoints_the_reference_is_interpolated(self):
        low, high = growth_reference._lms("weight", "F", 3), growth_reference._lms("weight", "F", 6)
        middle = growth_reference._lms("weight", "F", 4.5)
        for a, b, mid in zip(low, high, middle):
            self.assertAlmostEqual(mid, (a + b) / 2, places=9)

    def test_out_of_range_inputs_give_no_percentile(self):
        self.assertIsNone(growth_reference.get_percentile("weight", "F", -1, 5))        # not born yet
        self.assertIsNone(growth_reference.get_percentile("weight", "F", 61, 20))       # WHO tables stop at 60 months
        self.assertIsNone(growth_reference.get_percentile("weight", "O", 12, 9))        # no table for another sex
        self.assertIsNone(growth_reference.get_percentile("weight", "F", 12, None))     # nothing measured
        self.assertIsNone(growth_reference.get_percentile("bmi", "F", 12, 9))           # not a measurement WHO covers here

    def test_a_wildly_wrong_reading_is_capped_at_5_standard_deviations(self):
        self.assertEqual(growth_reference.get_percentile("weight", "F", 12, 500)["z_score"], 5)
        self.assertEqual(growth_reference.get_percentile("weight", "F", 12, 0.5)["z_score"], -5)

    def test_the_tables_are_complete_and_in_order(self):
        for measurement in growth_reference.MEASUREMENTS:
            for sex in ("M", "F"):
                rows = growth_reference.REFERENCE_TABLES[measurement][sex]
                ages = [r[0] for r in rows]
                self.assertEqual((ages[0], ages[-1]), (0, 60), (measurement, sex))
                self.assertEqual(ages, sorted(set(ages)), (measurement, sex))
                self.assertEqual([r[2] for r in rows], sorted(r[2] for r in rows), (measurement, sex))   # the median grows with age
class AddPercentilesTests(SimpleTestCase):
    dob = dt.date(2024, 1, 15)

    def point(self, taken, source="this_hospital", weight=12.0):
        return {"date": taken, "weight_kg": weight, "height_cm": None, "head_circumference_cm": None, "source": source}

    def test_age_in_months_is_counted_from_the_date_of_birth(self):
        series = [self.point("2025-01-15"), self.point("2026-01-14")]            # 12 and 24 months
        self.assertTrue(growth_reference.add_percentiles(series, "F", self.dob))
        self.assertEqual(series[0]["percentiles"]["weight"], growth_reference.get_percentile("weight", "F", 12, 12.0))
        self.assertEqual(series[1]["percentiles"]["weight"], growth_reference.get_percentile("weight", "F", 24, 12.0))

    def test_readings_after_the_age_of_5_get_none(self):
        series = [self.point("2029-03-01")]                                      # 61 months
        self.assertFalse(growth_reference.add_percentiles(series, "F", self.dob))
        self.assertNotIn("percentiles", series[0])

    def test_only_the_wanted_source_is_scored(self):
        series = [self.point("2025-01-15"), self.point("2025-01-15", source="other_hospital")]
        growth_reference.add_percentiles(series, "M", self.dob, only_source="this_hospital")
        self.assertIn("percentiles", series[0])
        self.assertNotIn("percentiles", series[1])

    def test_no_percentiles_without_a_known_sex_or_birth_date(self):
        self.assertFalse(growth_reference.add_percentiles([self.point("2025-01-15")], "O", self.dob))
        self.assertFalse(growth_reference.add_percentiles([self.point("2025-01-15")], "F", None))
class TimingTests(SimpleTestCase):
    """roadmap.timing_for(age_days, min_age_days, max_age_days): 14 days of lead, 90 days of grace when there is no maximum."""

    def test_the_window_opens_14_days_early(self):
        self.assertEqual(roadmap.timing_for(41, 60, None), "upcoming")           # 60 - 14 = 46 is the first due day
        self.assertEqual(roadmap.timing_for(45, 60, None), "upcoming")
        self.assertEqual(roadmap.timing_for(46, 60, None), "due_now")

    def test_with_no_maximum_it_is_due_for_90_days(self):
        self.assertEqual(roadmap.timing_for(149, 60, None), "due_now")
        self.assertEqual(roadmap.timing_for(150, 60, None), "past_window")       # 60 + 90

    def test_with_a_maximum_the_window_closes_there(self):
        self.assertEqual(roadmap.timing_for(119, 60, 120), "due_now")
        self.assertEqual(roadmap.timing_for(120, 60, 120), "past_window")

    def test_no_birth_date_or_no_minimum_gives_no_timing(self):
        self.assertIsNone(roadmap.timing_for(None, 60, None))
        self.assertIsNone(roadmap.timing_for(100, None, None))
class RoadmapContentTests(TestCase):
    """build_roadmap / summarize_roadmap against the atomwalk database."""
    databases = {"default"}
    rules = [
        {"vaccine_name": "BCG", "scheduled_label": "Birth", "min_age_days": 0, "max_age_days": 30},
        {"vaccine_name": "OPV 1", "scheduled_label": "6 weeks", "min_age_days": 42, "max_age_days": None},
        {"vaccine_name": "MMR", "scheduled_label": "9 months", "min_age_days": 270, "max_age_days": None},
    ]

    def setUp(self):
        ensure_hospital(1)
        ensure_hospital(2)
        self.dob = dt.date.today() - timedelta(days=60)           # a 2-month-old

    def record(self, name="BCG", label="Birth", **fields):
        kid = Patient.objects.using("default").get_or_create(awpid="AW-K", defaults={"full_name": "Kid"})[0]
        base = dict(patient=kid, vaccine_name=name, scheduled_label=label, source=V.SOURCE_CLINIC,
                    verification_status=V.STATUS_VERIFIED, source_hospital_id=1, administered_date=dt.date.today())
        return V.objects.using("default").create(**{**base, **fields})

    def roadmap(self, **kw):
        return build_roadmap("AW-K", self.dob, self.rules, viewer_hospital_id=1, **kw)

    def test_each_slot_is_matched_to_its_own_record_once(self):
        first = self.record()
        self.record()                                             # a second BCG fits no free slot
        rows = self.roadmap()
        self.assertEqual([r["status"] for r in rows[:3]], ["completed", "unknown", "unknown"])
        self.assertEqual(rows[0]["record_id"], first.id)
        self.assertEqual([r["extra"] for r in rows], [False, False, False, True])

    def test_matching_ignores_case_and_spaces_in_the_name(self):
        self.record(name="  bcg ")
        self.assertEqual(self.roadmap()[0]["status"], "completed")

    def test_without_consent_other_hospitals_records_are_hidden_except_pending_reviews(self):
        self.record(source_hospital_id=2)                                                    # verified elsewhere: hidden
        self.record(name="OPV 1", label="6 weeks", source_hospital_id=2,
                    verification_status=V.STATUS_PENDING, source=V.SOURCE_SELF_REPORTED)   # awaiting review: shown
        self.record(name="MMR", label="9 months", source_hospital_id=None)                   # never tied to a hospital: shown
        by_name = {r["vaccine_name"]: r["status"] for r in self.roadmap(hie_consent=False)}
        self.assertEqual(by_name, {"BCG": "unknown", "OPV 1": "pending_review", "MMR": "completed"})

    def test_with_consent_everything_is_shown(self):
        self.record(source_hospital_id=2)
        self.assertEqual(self.roadmap(hie_consent=True)[0]["status"], "completed")

    def test_removing_a_schedule_rule_never_removes_a_childs_record(self):
        schedule = Schedule.objects.using("default").create(kind="vaccination", name="s")
        rule = ScheduleRule.objects.using("default").create(schedule=schedule, item="BCG", scheduled_label="Birth", min_age_days=0)
        self.record()
        rule.delete()
        self.assertEqual(V.objects.using("default").count(), 1)
        rows = build_roadmap("AW-K", self.dob, ScheduleRule.objects.using("default").filter(schedule=schedule))
        self.assertEqual([(r["vaccine_name"], r["extra"]) for r in rows], [("BCG", True)])    # still shown, as an extra record

    def test_the_counts_above_the_roadmap(self):
        self.record()                                                                         # BCG completed
        self.record(name="OPV 1", label="6 weeks", verification_status=V.STATUS_PENDING,
                    source=V.SOURCE_SELF_REPORTED)                                            # pending review (not at a clinic)
        summary = summarize_roadmap(self.roadmap())
        # 2-month-old: MMR (270 days) is not due yet; OPV 1 has a record
        self.assertEqual((summary["completed_count"], summary["total_count"]), (1, 3))
        self.assertEqual(summary["stats"], {"completed": 1, "upcoming": 1, "needs_review": 1, "outside": 1})
        self.assertIsNone(summary["next_recommended"])

    def test_the_next_recommended_dose_is_the_first_unknown_one_that_is_due(self):
        summary = summarize_roadmap(self.roadmap())
        # a 60-day-old with no records: BCG window closed at day 30, OPV 1 (day 42) is due, MMR is upcoming
        self.assertEqual(summary["next_recommended"]["vaccine_name"], "OPV 1")
        self.assertEqual(summary["stats"], {"completed": 0, "upcoming": 1, "needs_review": 2, "outside": 0})


V = ImmunizationRecord
class PortalPediatricTests(TestCase):
    databases = {"default"}

    def setUp(self):
        ensure_hospital(1)
        self.mom = create_account(
            awpid="AW-MOM", full_name="Mom", mobile="9111111111", password="x", date_of_birth=dt.date(1990, 1, 1))
        self.kid = Patient.objects.using("default").create(
            awpid="AW-KID", full_name="Kid", gender="F", date_of_birth=dt.date.today() - timedelta(days=730), is_dependent=True)
        PatientRelationship.objects.using("default").create(guardian=self.mom, dependent=self.kid, relationship="child")

    def call(self, view, method="get", data=None, query="", **kwargs):
        request = getattr(APIRequestFactory(), method)(f"/x/{query}", data, format="json")
        force_authenticate(request, user=MockUser({"user_id": self.mom.id, "role": "patient", "awpid": "AW-MOM"}))
        return view.as_view()(request, **kwargs)

    def vaccination(self, awpid="AW-KID", **fields):
        person = Patient.objects.using("default").get_or_create(awpid=awpid, defaults={"full_name": awpid})[0]
        base = dict(patient=person, vaccine_name="BCG", scheduled_label="Birth", source=V.SOURCE_CLINIC,
                    verification_status=V.STATUS_VERIFIED, source_hospital_id=1)
        return V.objects.using("default").create(**{**base, **fields})

    # ── growth ────────────────────────────────────────────────────────────────
    def test_growth_shows_a_family_members_readings_with_percentiles(self):
        GrowthMeasurement.objects.using("default").create(
            patient=self.kid, measured_on=dt.date.today(), weight_kg=Decimal("12"), height_cm=Decimal("85"), source_hospital_id=1)
        Vitals.objects.using("default").create(patient=self.kid, spo2=98, source_hospital_id=1)    # not a growth measurement: left out
        data = self.call(views.PortalGrowthView, query="?patient_awpid=AW-KID").data["data"]
        self.assertTrue(data["is_minor"])
        self.assertEqual(len(data["series"]), 1)                       # a reading with no growth measurement is left out
        self.assertEqual(data["latest"], data["series"][0])
        self.assertIn("weight", data["series"][0]["percentiles"])
        self.assertTrue(data["percentile_available"])

    def test_growth_for_someone_not_linked_to_the_account_is_refused(self):
        Patient.objects.using("default").create(awpid="AW-STRANGER", full_name="Stranger")
        self.assertEqual(self.call(views.PortalGrowthView, query="?patient_awpid=AW-STRANGER").status_code, 403)

    def test_an_adult_gets_no_percentiles(self):
        Vitals.objects.using("default").create(patient=self.mom, weight_kg=Decimal("60"), source_hospital_id=1)
        data = self.call(views.PortalGrowthView).data["data"]
        self.assertFalse(data["is_minor"])
        self.assertFalse(data["percentile_available"])

    # ── roadmaps ──────────────────────────────────────────────────────────────
    def test_the_vaccination_roadmap_counts_completed_doses(self):
        self.vaccination()
        data = self.call(views.PortalVaccinationListView, query="?patient_awpid=AW-KID").data["data"]
        self.assertEqual(next(r for r in data["roadmap"] if r["vaccine_name"] == "BCG")["status"], "completed")
        self.assertEqual(data["completed_count"], 1)
        self.assertGreater(data["total_count"], 1)
        self.assertNotIn("next_due", data)

    def test_the_milestone_roadmap_shows_an_assessment(self):
        slot = ScheduleRule.objects.using("default").filter(schedule__kind="milestone").first()          # a slot of the seeded default schedule
        MilestoneRecord.objects.using("default").create(
            patient=self.kid, domain=slot.domain, milestone=slot.item, scheduled_label=slot.scheduled_label,
            status="achieved", achieved_date=dt.date.today(), assessed_date=dt.date.today())
        data = self.call(views.PortalMilestoneListView, query="?patient_awpid=AW-KID").data["data"]
        self.assertEqual(sum(1 for r in data["roadmap"] if r["status"] == "achieved"), 1)
        self.assertEqual(data["achieved_count"], 1)

    # ── uploads ───────────────────────────────────────────────────────────────
    def upload(self, **body):
        return self.call(views.PortalVaccinationUploadView, "post", {"patient_awpid": "AW-KID", **body})

    def test_an_upload_needs_a_name_and_a_plausible_date(self):
        self.assertEqual(self.upload(administered_date="2025-03-04").status_code, 400)
        self.assertEqual(self.upload(vaccine_name="Polio").status_code, 400)
        for bad in ("04/03/2025", "82026-10-02", "1850-01-01", (dt.date.today() + timedelta(days=2)).isoformat()):
            self.assertEqual(self.upload(vaccine_name="Polio", administered_date=bad).status_code, 400, bad)
        self.assertEqual(V.objects.using("default").count(), 0)

    def test_an_oversized_or_invalid_certificate_is_refused(self):
        too_big = "x" * (views._MAX_CERTIFICATE_CHARS + 1)
        self.assertEqual(self.upload(vaccine_name="Polio", administered_date="2025-03-04", file_data=too_big).status_code, 400)
        self.assertEqual(self.upload(vaccine_name="Polio", administered_date="2025-03-04", file_data="nope").status_code, 400)
        self.assertEqual(V.objects.using("default").count(), 0)

    # ── certificate file ──────────────────────────────────────────────────────
    # ── family ────────────────────────────────────────────────────────────────
    def test_family_members_are_listed_added_edited_and_unlinked(self):
        listed = self.call(views.PortalFamilyListCreateView).data["data"]["results"]
        self.assertEqual([m["awpid"] for m in listed], ["AW-KID"])

        added = self.call(views.PortalFamilyListCreateView, "post",
                          {"full_name": "Baby Two", "date_of_birth": "2025-06-01", "gender": "M", "relationship": "child"})
        self.assertEqual(added.status_code, 200, added.data)
        self.assertEqual(added.data["message"], "Family member added.")
        awpid = added.data["data"]["awpid"]
        self.assertTrue(PatientRelationship.objects.using("default").filter(guardian__awpid="AW-MOM", dependent__awpid=awpid).exists())

        again = self.call(views.PortalFamilyListCreateView, "post", {"full_name": "Baby Two", "date_of_birth": "2025-06-01"})
        self.assertIn("Reconnected", again.data["message"])                 # same name and birth date: same person, not a duplicate

        edited = self.call(views.PortalFamilyDetailView, "patch", {"full_name": "Baby Too"}, awpid=awpid)
        self.assertEqual(edited.status_code, 200, edited.data)
        self.assertEqual(Patient.objects.using("default").get(awpid=awpid).full_name, "Baby Too")

        self.assertEqual(self.call(views.PortalFamilyDetailView, "delete", awpid=awpid).status_code, 200)
        self.assertFalse(PatientRelationship.objects.using("default").filter(dependent__awpid=awpid).exists())
        self.assertTrue(Patient.objects.using("default").filter(awpid=awpid).exists())    # the person's record stays

    def test_a_family_member_needs_a_name_and_only_the_guardian_can_edit(self):
        self.assertEqual(self.call(views.PortalFamilyListCreateView, "post", {"date_of_birth": "2025-06-01"}).status_code, 400)
        other = Patient.objects.using("default").create(awpid="AW-OTHER", full_name="Other")
        self.assertEqual(self.call(views.PortalFamilyDetailView, "patch", {"full_name": "X"}, awpid=other.awpid).status_code, 400)


V = ImmunizationRecord
@requires_hospital_db
class PediatricStaffTests(HospitalDBTestCase):
    def setUp(self):
        super().setUp()
        from apps.opd.models import Appointment
        from apps.hospital_setup.models import Branch
        from apps.opd.models import HospitalPatient
        from apps.hospital_master.models import Hospital

        db = self.hospital_alias
        self.hospital = Hospital.objects.using("default").create(name="Peds H", hospital_code="peds-h", db_name=db)
        self.branch = Branch.objects.using(db).create(name="Main")
        self.child = HospitalPatient.objects.using(db).create(
            awpid="AW-KID-1", uhid="UHID-K1", branch=self.branch, full_name="Kid One", gender="F",
            date_of_birth=dt.date.today() - timedelta(days=730), is_dependent=True,
        )
        ensure_hospital(self.hospital.id + 1)
        ensure_hospital(self.hospital.id + 50)
        self.shared = Patient.objects.using("default").create(awpid="AW-KID-1", full_name="Kid One", gender="F", is_dependent=True)
        self.appt = Appointment.objects.using(db).create(
            patient_id=self.child.uuid, patient_awpid=self.child.awpid, doctor_user_id=uuid.UUID(int=5),
            doctor_name="Dr X", branch_id=self.branch.id, scheduled_date=dt.date.today(),
        )

    # ── helpers ───────────────────────────────────────────────────────────────
    def call(self, view, method, path="/x/", role="doctor", data=None, pk=None, **kw):
        return self.call_view(view.as_view(), method, path, user_id=7, role=role, data=data,
                              hospital_id=self.hospital.id, view_kwargs={"pk": pk or self.child.pk}, **kw)

    def vax(self, awpid=None, **fields):
        person = Patient.objects.using("default").get_or_create(awpid=awpid, defaults={"full_name": awpid})[0] if awpid else self.shared
        base = dict(patient=person, vaccine_name="BCG", scheduled_label="Birth", source=V.SOURCE_CLINIC,
                    verification_status=V.STATUS_VERIFIED, source_hospital_id=self.hospital.id)
        return V.objects.using("default").create(**{**base, **fields})

    def add_vitals(self, **fields):
        from apps.opd.vitals_service import record_vitals
        return record_vitals(self.appt, self.hospital_alias, self.hospital.id, None, fields)[0]

    def test_only_a_doctor_or_nurse_can_record_vitals(self):
        from apps.opd.views import VitalsView
        for role, expected in (("front_desk", 403), ("pharmacist", 403), ("lab_tech", 403)):
            resp = self.call(VitalsView, "post", role=role, data={"weight_kg": "12"}, pk=self.appt.pk)
            self.assertEqual(resp.status_code, expected, role)
        resp = self.call(VitalsView, "post", role="nurse", data={"weight_kg": "12", "height_cm": "85"}, pk=self.appt.pk)
        self.assertLess(resp.status_code, 300, getattr(resp, "data", None))

    # ── vaccinations: roadmap and logging ─────────────────────────────────────
    def test_the_roadmap_lists_the_schedule_and_marks_a_recorded_dose_completed(self):
        self.vax()
        roadmap = self.call(vax_views.PatientVaccinationListCreateView, "get").data["data"]["roadmap"]
        bcg = next(r for r in roadmap if r["vaccine_name"] == "BCG")
        self.assertEqual(bcg["status"], "completed")
        self.assertTrue(any(r["status"] == "unknown" for r in roadmap))

    def test_a_bad_certificate_is_refused_and_nothing_is_saved(self):
        resp = self.call(vax_views.PatientVaccinationListCreateView, "post",
                         data={"vaccine_name": "BCG", "administered_date": "2026-01-01", "file_data": "not-a-data-uri"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(V.objects.using("default").count(), 0)

    # ── vaccinations: review ──────────────────────────────────────────────────
    # ── vaccinations: order, decline, administer ──────────────────────────────
    # ── birth history ─────────────────────────────────────────────────────────
    def test_birth_history_is_created_once_edited_and_copied_to_the_atomwalk(self):
        view = ped_views.BirthHistoryView
        self.assertIsNone(self.call(view, "get").data["data"])
        body = {"gestational_age_weeks": 38, "birth_weight_kg": "3.1", "delivery_mode": "normal"}
        self.assertEqual(self.call(view, "post", role="nurse", data=body).status_code, 403)
        self.assertEqual(self.call(view, "post", role="front_desk", data=body).status_code, 201)
        self.assertEqual(self.call(view, "post", data=body).status_code, 400)        # already exists
        self.assertEqual(self.call(view, "patch", data={"nicu_days": 9}).status_code, 200)
        shared = BirthHistory.objects.using("default").get(patient__awpid=self.child.awpid)
        self.assertEqual((shared.gestational_age_weeks, shared.nicu_days, shared.source_hospital_id), (38, 9, self.hospital.id))
        self.assertEqual(self.call(view, "get").data["data"]["gestational_age_weeks"], 38)

    def test_birth_history_changes_are_written_to_the_audit_log(self):
        from apps.hospital_setup.models import AuditLog
        view = ped_views.BirthHistoryView
        self.call(view, "post", data={"gestational_age_weeks": 38, "delivery_mode": "normal"})
        self.call(view, "patch", data={"gestational_age_weeks": 36, "notes": "late preterm"})
        rows = list(AuditLog.objects.using(self.hospital_alias).filter(resource_type="BirthHistory").order_by("id"))
        self.assertEqual([r.action for r in rows], ["birth_history.create", "birth_history.update"])
        self.assertEqual(rows[1].metadata["changed"]["gestational_age_weeks"], ["38", "36"])
        self.assertEqual(rows[1].patient_id, self.child.uuid)

    def test_the_audit_log_notes_when_another_hospitals_birth_history_is_replaced(self):
        from apps.hospital_setup.models import AuditLog
        BirthHistory.objects.using("default").create(patient=self.shared, gestational_age_weeks=40, source_hospital_id=self.hospital.id + 50)
        self.call(ped_views.BirthHistoryView, "patch", data={"gestational_age_weeks": 38})
        row = AuditLog.objects.using(self.hospital_alias).get(action="birth_history.update")
        self.assertEqual(row.metadata["replaced_other_hospitals_copy"], self.hospital.id + 50)

    def test_editing_a_missing_birth_history_is_not_found(self):
        self.assertEqual(self.call(ped_views.BirthHistoryView, "patch", data={"notes": "x"}).status_code, 404)

    # ── milestones ────────────────────────────────────────────────────────────
    def test_recording_a_milestone_validates_and_stamps_dates_by_status(self):
        view = ped_views.PatientMilestoneListCreateView
        self.assertEqual(self.call(view, "post", data={"domain": "nonsense", "milestone": "x"}).status_code, 400)
        self.assertEqual(self.call(view, "post", data={"domain": "gross_motor"}).status_code, 400)
        self.assertEqual(self.call(view, "post", data={"domain": "gross_motor", "milestone": "x", "status": "weird"}).status_code, 400)
        achieved = self.call(view, "post", role="nurse", data={"domain": "gross_motor", "milestone": "Sits", "scheduled_label": "6 months"})
        self.assertEqual(achieved.status_code, 201)
        self.assertEqual(achieved.data["data"]["achieved_date"], str(dt.date.today()))
        concern = self.call(view, "post", data={"domain": "language", "milestone": "Babbles", "status": "concern", "achieved_date": "2026-01-01"})
        self.assertIsNone(concern.data["data"]["achieved_date"])                     # only "achieved" keeps a date
        self.assertEqual(MilestoneRecord.objects.using("default").count(), 2)

    def test_milestone_dates_must_be_real_and_not_in_the_future(self):
        view = ped_views.PatientMilestoneListCreateView
        base = {"domain": "language", "milestone": "Babbles"}
        future = (dt.date.today() + timedelta(days=3)).isoformat()
        for field, bad in (("assessed_date", "garbage"), ("achieved_date", "garbage"), ("assessed_date", future), ("achieved_date", future)):
            self.assertEqual(self.call(view, "post", data={**base, field: bad}).status_code, 400, (field, bad))
        self.assertEqual(MilestoneRecord.objects.using("default").count(), 0)

    def test_the_milestone_roadmap_lists_the_schedule(self):
        data = self.call(ped_views.PatientMilestoneListCreateView, "get").data["data"]
        self.assertTrue(data["roadmap"])
        self.assertFalse(data["consent_given"])


class ShapeTests(SimpleTestCase):
    def test_vaccination_rule(self):
        rule = SimpleNamespace(id=1, item="BCG", dose_number=1, scheduled_label="At birth", min_age_days=0,
                               max_age_days=30, mandatory=True, sort_order=1)
        self.assertEqual(vaccination_rule_dict(rule), {
            "id": 1, "vaccine_name": "BCG", "dose_number": 1, "scheduled_label": "At birth",
            "min_age_days": 0, "max_age_days": 30, "mandatory": True, "sort_order": 1})

    def test_milestone_rule(self):
        rule = SimpleNamespace(id=2, domain="motor", item="Sits", scheduled_label="6 months", min_age_days=150,
                               max_age_days=210, mandatory=False, sort_order=3)
        self.assertEqual(set(milestone_rule_dict(rule)), {"id", "domain", "milestone", "scheduled_label",
                                                         "min_age_days", "max_age_days", "mandatory", "sort_order"})

    def test_schedule_marks_the_hospitals_active_one_and_counts_rules(self):
        s = SimpleNamespace(id=5, name="Std", description="d", is_template=False, active=True, owner_hospital_id=9,
                            s_rules=SimpleNamespace(count=lambda: 12))
        self.assertTrue(schedule_dict(s, active_id=5)["is_active_for_this_hospital"])
        self.assertFalse(schedule_dict(s, active_id=6)["is_active_for_this_hospital"])
        self.assertFalse(schedule_dict(s)["is_active_for_this_hospital"])
        self.assertEqual(schedule_dict(s)["rule_count"], 12)
        self.assertEqual(schedule_dict(s, rule_count=3)["rule_count"], 3)

    def test_template(self):
        when = dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc)
        s = SimpleNamespace(id=1, name="T", description="", active=True, created_at=when, updated_at=when,
                            s_rules=SimpleNamespace(count=lambda: 4))
        out = template_dict(s, hospitals_using=2)
        self.assertEqual((out["rule_count"], out["hospitals_using"], out["created_at"]), (4, 2, when.isoformat()))
class PlatformTemplateListTests(TestCase):
    """The platform-admin template lists (atomwalk DB only) keep working on the shared helpers."""
    databases = {"default"}

    def get(self, view):
        request = APIRequestFactory().get("/x/")
        force_authenticate(request, user=MockUser({"user_id": 1, "role": "platform_admin", "is_platform": True}))
        return view.as_view()(request)

    def test_vaccination_templates(self):
        from apps.documents.views import VaccinationTemplateListCreateView
        Schedule.objects.using("default").create(kind="vaccination", name="India UIP", is_template=True)
        resp = self.get(VaccinationTemplateListCreateView)
        self.assertEqual(resp.status_code, 200)
        names = [t["name"] for t in resp.data["data"]]
        self.assertIn("India UIP", names)
        row = next(t for t in resp.data["data"] if t["name"] == "India UIP")
        self.assertEqual((row["rule_count"], row["hospitals_using"]), (0, 0))

    def test_milestone_templates(self):
        from apps.documents.views import MilestoneTemplateListCreateView
        Schedule.objects.using("default").create(kind="milestone", name="WHO milestones", is_template=True)
        resp = self.get(MilestoneTemplateListCreateView)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("WHO milestones", [t["name"] for t in resp.data["data"]])


# per kind: (kind, view-name stem, the rule key holding the name, the kind-specific rule key + value)
KINDS = {
    "vaccination": dict(stem="Vaccination", name_key="vaccine_name",
                        extra={"dose_number": 2}),
    "milestone": dict(stem="Milestone", name_key="milestone",
                      extra={"domain": "gross_motor"}),
}
def rule(kind, name, **kw):
    spec = KINDS[kind]
    return {spec["name_key"]: name, "scheduled_label": "6 months", "min_age_days": 180, **spec["extra"], **kw}
class ScheduleEndpointTests(TestCase):
    databases = {"default"}

    def setUp(self):
        self.hospital = Hospital.objects.using("default").create(name="T", hospital_code="t", db_name="x")
        HospitalParameters.objects.using("default").create(hospital=self.hospital, fee_ownership="hospital")

    def call(self, view, method, data=None, role="hospital_admin", pk=None):
        request = getattr(APIRequestFactory(), method)("/x/", data, format="json")
        request.hospital_id = self.hospital.id
        force_authenticate(request, user=MockUser({"user_id": 1, "role": role, "is_platform": role == "platform_admin",
                                                   "hospital_id": self.hospital.id}))
        return view.as_view()(request, **({"pk": pk} if pk else {}))

    def view(self, module, kind, suffix):
        return getattr(module, f"{KINDS[kind]['stem']}{suffix}")

    def platform(self, kind, method, data=None, pk=None, detail=False):
        suffix = "TemplateDetailView" if detail else "TemplateListCreateView"
        return self.call(self.view(platform_urls, kind, suffix), method, data, "platform_admin", pk)

    def as_staff(self, kind, method, data=None, pk=None, suffix="ScheduleListCreateView"):
        return self.call(self.view(org_urls, kind, suffix), method, data, "hospital_admin", pk)

    def make_template(self, kind, rules=None):
        resp = self.platform(kind, "post", {"name": f"{kind} std", "rules": rules or [rule(kind, "A"), rule(kind, "B")]})
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.data["data"]["id"]

    # ── platform admin: templates ─────────────────────────────────────────────
    def test_a_template_is_created_with_its_rules_and_can_be_read_back(self):
        for kind in KINDS:
            with self.subTest(kind):
                pk = self.make_template(kind)
                data = self.platform(kind, "get", pk=pk, detail=True).data["data"]
                self.assertEqual([r[KINDS[kind]["name_key"]] for r in data["rules"]], ["A", "B"])
                self.assertEqual(Schedule.objects.get(pk=pk).kind, kind)
                listed = self.platform(kind, "get").data["data"]
                self.assertEqual([t["id"] for t in listed if t["id"] == pk], [pk])

    def test_each_kind_only_lists_its_own_templates(self):
        v, m = self.make_template("vaccination"), self.make_template("milestone")
        vaccination_ids = {t["id"] for t in self.platform("vaccination", "get").data["data"]}
        milestone_ids = {t["id"] for t in self.platform("milestone", "get").data["data"]}
        self.assertTrue(v in vaccination_ids and m not in vaccination_ids)
        self.assertTrue(m in milestone_ids and v not in milestone_ids)

    def test_a_template_needs_a_name_and_invalid_rules_are_skipped(self):
        for kind in KINDS:
            with self.subTest(kind):
                self.assertEqual(self.platform(kind, "post", {"name": " "}).status_code, 400)
                bad = [rule(kind, "ok"), {"scheduled_label": "x", "min_age_days": 1}, rule(kind, "no-age", min_age_days=None)]
                pk = self.make_template(kind, bad)
                self.assertEqual(len(self.platform(kind, "get", pk=pk, detail=True).data["data"]["rules"]), 1)

    def test_a_milestone_rule_with_an_unknown_domain_is_skipped(self):
        pk = self.make_template("milestone", [rule("milestone", "ok"), rule("milestone", "bad", domain="nonsense")])
        self.assertEqual(len(self.platform("milestone", "get", pk=pk, detail=True).data["data"]["rules"]), 1)

    def test_patching_a_template_updates_deletes_and_adds_rules(self):
        for kind in KINDS:
            with self.subTest(kind):
                key = KINDS[kind]["name_key"]
                pk = self.make_template(kind)
                first, second = self.platform(kind, "get", pk=pk, detail=True).data["data"]["rules"]
                resp = self.platform(kind, "patch", {"name": "Renamed", "active": False, "rules": [
                    {"id": first["id"], key: "A2", "min_age_days": 10},
                    {"id": second["id"], "_delete": True},
                    rule(kind, "C"),
                ]}, pk=pk, detail=True)
                self.assertEqual(resp.status_code, 200, resp.data)
                data = resp.data["data"]
                self.assertEqual((data["name"], data["active"]), ("Renamed", False))
                self.assertEqual([(r[key], r["min_age_days"]) for r in data["rules"]], [("A2", 10), ("C", 180)])

    def test_a_template_in_use_cannot_be_deleted_but_an_unused_one_can(self):
        for kind in KINDS:
            with self.subTest(kind):
                in_use = roadmap.default_schedule(kind).pk              # every hospital without a schedule of its own uses it
                self.assertEqual(self.platform(kind, "delete", pk=in_use, detail=True).status_code, 400)
                pk = self.make_template(kind)
                self.assertEqual(self.platform(kind, "delete", pk=pk, detail=True).status_code, 200)
                self.assertFalse(Schedule.objects.filter(pk=pk).exists())

    # ── hospital admin: schedules ─────────────────────────────────────────────
    def test_a_hospital_clones_a_template_and_it_becomes_active(self):
        for kind in KINDS:
            with self.subTest(kind):
                key = KINDS[kind]["name_key"]
                template = self.make_template(kind)
                resp = self.as_staff(kind, "post", {"template_id": template})
                self.assertEqual(resp.status_code, 201, resp.data)
                clone_id = resp.data["data"]["id"]
                clone = Schedule.objects.get(pk=clone_id)
                self.assertEqual((clone.kind, clone.owner_hospital_id, clone.is_template), (kind, self.hospital.id, False))
                self.assertEqual(roadmap.active_schedule(kind, self.hospital.id).pk, clone_id)
                detail = self.as_staff(kind, "get", pk=clone_id, suffix="ScheduleDetailView").data["data"]
                self.assertEqual([r[key] for r in detail["rules"]], ["A", "B"])
                self.assertEqual(detail["rules"][0][next(iter(KINDS[kind]["extra"]))], next(iter(KINDS[kind]["extra"].values())))

    def test_cloning_needs_a_real_template(self):
        for kind in KINDS:
            with self.subTest(kind):
                self.assertEqual(self.as_staff(kind, "post", {}).status_code, 400)
                self.assertEqual(self.as_staff(kind, "post", {"template_id": 999999}).status_code, 404)

    def test_the_hospital_list_shows_its_own_schedules_and_the_templates(self):
        for kind in KINDS:
            with self.subTest(kind):
                template = self.make_template(kind)
                clone = self.as_staff(kind, "post", {"template_id": template}).data["data"]["id"]
                data = self.as_staff(kind, "get").data["data"]
                self.assertEqual([s["id"] for s in data["own_schedules"]], [clone])
                self.assertIn(template, [s["id"] for s in data["templates"]])   # next to the seeded default template
                self.assertEqual(data["active_schedule_id"], clone)

    def test_a_hospital_edits_only_its_own_schedule_never_a_template(self):
        for kind in KINDS:
            with self.subTest(kind):
                template = self.make_template(kind)
                self.assertEqual(self.as_staff(kind, "patch", {"name": "x"}, pk=template, suffix="ScheduleDetailView").status_code, 404)
                clone = self.as_staff(kind, "post", {"template_id": template}).data["data"]["id"]
                resp = self.as_staff(kind, "patch", {"name": "Mine", "rules": [rule(kind, "Z")]}, pk=clone, suffix="ScheduleDetailView")
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.data["data"]["name"], "Mine")
                self.assertEqual(len(resp.data["data"]["rules"]), 3)

    def test_a_hospital_can_activate_a_template_directly_but_not_another_hospitals_schedule(self):
        for kind in KINDS:
            with self.subTest(kind):
                template = self.make_template(kind)
                resp = self.as_staff(kind, "post", pk=template, suffix="ScheduleActivateView")
                self.assertEqual(resp.status_code, 200, resp.data)
                active = roadmap.active_schedule(kind, self.hospital.id)
                self.assertEqual((active.owner_hospital_id, active.name, active.pk != template),
                                 (self.hospital.id, Schedule.objects.get(pk=template).name, True))
                other = Schedule.objects.create(kind=kind, name="theirs", owner_hospital=ensure_hospital(self.hospital.id + 1000))
                self.assertEqual(self.as_staff(kind, "post", pk=other.id, suffix="ScheduleActivateView").status_code, 400)
                self.assertEqual(self.as_staff(kind, "get", pk=other.id, suffix="ScheduleDetailView").status_code, 404)

    def test_an_id_of_the_other_kind_is_not_found(self):
        milestone = self.make_template("milestone")
        self.assertEqual(self.platform("vaccination", "get", pk=milestone, detail=True).status_code, 404)
        self.assertEqual(self.as_staff("vaccination", "post", pk=milestone, suffix="ScheduleActivateView").status_code, 404)

    # ── rule numbers ──────────────────────────────────────────────────────────
    def test_rule_numbers_must_be_whole_numbers_and_the_maximum_cannot_be_below_the_minimum(self):
        for kind in KINDS:
            with self.subTest(kind):
                for bad in ({"min_age_days": "abc"}, {"min_age_days": -5}, {"min_age_days": 1.5},
                            {"min_age_days": 100, "max_age_days": 10}, {"sort_order": -1}):
                    resp = self.platform(kind, "post", {"name": f"T-{kind}", "rules": [rule(kind, "A", **bad)]})
                    self.assertEqual(resp.status_code, 400, bad)
                self.assertFalse(Schedule.objects.filter(name=f"T-{kind}").exists())          # nothing is created when a rule is wrong
                ok = self.platform(kind, "post", {"name": f"T-{kind}", "rules": [rule(kind, "A", min_age_days="180", max_age_days=365)]})
                self.assertEqual(ok.status_code, 201, ok.data)

    def test_a_bad_rule_in_an_edit_changes_nothing_and_clearing_the_maximum_is_allowed(self):
        for kind in KINDS:
            with self.subTest(kind):
                key = KINDS[kind]["name_key"]
                pk = self.make_template(kind, [rule(kind, "A", min_age_days=100, max_age_days=200)])
                first = self.platform(kind, "get", pk=pk, detail=True).data["data"]["rules"][0]
                bad = self.platform(kind, "patch", {"name": "Renamed", "rules": [
                    {"id": first["id"], key: "A2"}, {"id": first["id"], "max_age_days": 50}]}, pk=pk, detail=True)
                self.assertEqual(bad.status_code, 400)
                data = self.platform(kind, "get", pk=pk, detail=True).data["data"]
                self.assertEqual((data["name"], data["rules"][0][key]), (f"{kind} std", "A"))                 # untouched
                self.assertEqual(self.platform(kind, "patch", {"rules": [{"id": first["id"], "min_age_days": 300}]}, pk=pk, detail=True).status_code, 400)
                cleared = self.platform(kind, "patch", {"rules": [{"id": first["id"], "max_age_days": None}]}, pk=pk, detail=True)
                self.assertEqual(cleared.status_code, 200)
                self.assertIsNone(cleared.data["data"]["rules"][0]["max_age_days"])
