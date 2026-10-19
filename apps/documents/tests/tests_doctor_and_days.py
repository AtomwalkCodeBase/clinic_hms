"""What the mobile app needs from My Documents: the doctor's name (read from the text, typed by the patient, carried by the
row), the `deletable` flag, the By-date view (GET /portal/documents/days/) and the `uploaded_on` filter that opens a day."""
import datetime
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.documents import lib_documents as records
from apps.documents.lib_documents import clean_doctor_name, find_doctor_name
from apps.documents.models import MedicalDocument
from apps.documents.tasks import extract_document_task
from apps.documents.tests.tests import PDF, identity, make_doc
from apps.patients.views import (
    PortalDocumentDaysView,
    PortalDocumentDetailView,
    PortalDocumentListCreateView,
)
from core.api.authentication import MockUser

S = MedicalDocument.Status
UTC = datetime.timezone.utc
RESOLVE_PORTAL = mock.patch("apps.patients.views.resolve_target_awpid_and_dob", return_value=("AWP-T1", None, None))


def call(view, method="get", data=None, **kwargs):
    factory = APIRequestFactory()
    request = factory.get("/x/", data or {}) if method == "get" else getattr(factory, method)("/x/", data or {}, format="json")
    force_authenticate(request, user=MockUser({"user_id": 1, "role": "patient", "awpid": "AWP-T1"}))
    return view.as_view()(request, **kwargs)


def row(doc):
    return MedicalDocument.objects.get(pk=doc.pk)


def at(y, m, d, hh=12, mm=0):
    return datetime.datetime(y, m, d, hh, mm, tzinfo=UTC)


def uploaded(when, document_type="lab_report", **fields):
    """A finished, confirmed document whose upload moment (UTC) is `when`."""
    doc = make_doc("AWP-T1", status="completed", document_type=document_type, by="human", **fields)
    MedicalDocument.objects.filter(pk=doc.pk).update(created_at=when)
    return doc


def hospital_issued(document_type="prescription", **fields):
    return make_doc("AWP-T1", status="completed", document_type=document_type, by="issued",
                    created_by_type="H", source_hospital_id=7, **fields)


# ── reading and cleaning the name ─────────────────────────────────────────────────────────────────────────────

class FindDoctorNameTests(SimpleTestCase):
    def test_a_plain_name_after_dr(self):
        self.assertEqual(find_doctor_name("Consultant: Dr. Anand Sharma, MBBS, MD"), "Anand Sharma")

    def test_the_prefix_is_not_part_of_the_answer(self):
        self.assertEqual(find_doctor_name("Prescribed by Dr Meera Nair"), "Meera Nair")
        self.assertEqual(find_doctor_name("DR. RAVI SINGH"), "Ravi Singh")

    def test_stops_at_a_qualification_or_a_field_label(self):
        self.assertEqual(find_doctor_name("Dr. Sudha Mehta MBBS"), "Sudha Mehta")
        self.assertEqual(find_doctor_name("Dr. Alka Gowda UHID: 123"), "Alka Gowda")
        self.assertEqual(find_doctor_name("Referred By: Dr. Vijay Jain Modality: CT"), "Vijay Jain")

    def test_a_name_with_an_apostrophe_or_a_hyphen(self):
        self.assertEqual(find_doctor_name("Dr. Rajiv D'Souza"), "Rajiv D'Souza")
        self.assertEqual(find_doctor_name("Dr. Anand-Kumar Rao"), "Anand-Kumar Rao")

    def test_only_the_line_after_dr_is_read(self):
        self.assertEqual(find_doctor_name("Dr.\nSharma"), "")

    def test_glued_or_broken_names_are_refused(self):
        for text in ("Dr. MukeshPanda", "Dr. ArvindKaur UHID", "Dr. Reddy's Laboratories", "Dr. R2D2 Singh"):
            self.assertEqual(find_doctor_name(text), "", text)

    def test_falls_through_to_a_later_good_name(self):
        self.assertEqual(find_doctor_name("Dr. MukeshPanda\nSigned: Dr. Girish Verma"), "Girish Verma")

    def test_nothing_to_find(self):
        for text in ("", None, "No doctor here", "Dr.", "Dr. 12345"):
            self.assertEqual(find_doctor_name(text), "", text)


class CleanDoctorNameTests(SimpleTestCase):
    def test_letters_and_spaces_pass(self):
        self.assertEqual(clean_doctor_name("  Anita   Rao "), "Anita Rao")

    def test_a_typed_prefix_is_dropped(self):
        self.assertEqual(clean_doctor_name("Dr. Anita Rao"), "Anita Rao")
        self.assertEqual(clean_doctor_name("dr anita rao"), "anita rao")

    def test_empty_clears(self):
        self.assertEqual(clean_doctor_name(""), "")
        self.assertEqual(clean_doctor_name("   "), "")

    def test_digits_and_symbols_are_refused(self):
        for bad in ("Anita4", "Anita@Rao", "Dr. 5", "<b>Rao</b>", "Anita_Rao"):
            self.assertIsNone(clean_doctor_name(bad), bad)

    def test_too_long_is_refused(self):
        self.assertIsNone(clean_doctor_name("A" * 61))
        self.assertEqual(clean_doctor_name("A" * 60), "A" * 60)

    def test_real_names_pass(self):
        for ok in ("D'Souza", "Anand-Kumar", "A. K. Rao"):
            self.assertEqual(clean_doctor_name(ok), ok)


# ── the name is read when a document is processed ─────────────────────────────────────────────────────────────

@mock.patch("core.storage.get_bytes", return_value=PDF)
class ReadingTheNameTests(TestCase):
    databases = {"default"}

    @mock.patch("apps.documents.tasks.classify_document_task.apply_async")
    @mock.patch("apps.documents.lib_documents.extract_text", return_value=("Prescribed by Dr. Anita Rao MBBS\nTab Paracetamol", "ocr"))
    def test_the_doctor_named_in_the_text_is_saved(self, _extract, _delay, _get):
        doc = make_doc(status=S.QUEUED)
        extract_document_task(doc.id)
        self.assertEqual(row(doc).doctor_name, "Anita Rao")

    @mock.patch("apps.documents.tasks.classify_document_task.apply_async")
    @mock.patch("apps.documents.lib_documents.extract_text", return_value=("Dr. Anita Rao", "ocr"))
    def test_a_name_the_patient_already_set_is_kept(self, _extract, _delay, _get):
        doc = make_doc(status=S.QUEUED)
        MedicalDocument.objects.filter(pk=doc.id).update(doctor_name="Sunil Kumar")
        extract_document_task(doc.id)
        self.assertEqual(row(doc).doctor_name, "Sunil Kumar")

    @mock.patch("apps.documents.tasks.classify_document_task.apply_async")
    @mock.patch("apps.documents.lib_documents.extract_text", return_value=("hemoglobin glucose", "ocr"))
    def test_no_doctor_in_the_text_leaves_the_name_empty(self, _extract, _delay, _get):
        doc = make_doc(status=S.QUEUED)
        extract_document_task(doc.id)
        self.assertEqual(row(doc).doctor_name, "")

    @mock.patch("apps.documents.tasks.classify_document_task.apply_async")
    @mock.patch("apps.documents.lib_documents.extract_text", return_value=("Dr. Anita Rao", "ocr"))
    def test_a_hospital_issued_file_is_not_given_a_name_from_its_text(self, _extract, _delay, _get):
        doc = make_doc(status=S.QUEUED, created_by_type="H", source_hospital_id=7)
        extract_document_task(doc.id)
        self.assertEqual(row(doc).doctor_name, "")


# ── the patient types it, and the row carries it ──────────────────────────────────────────────────────────────

@RESOLVE_PORTAL
class DoctorNameEndpointTests(TestCase):
    databases = {"default"}

    def setUp(self):
        identity("AWP-T1")

    def patch(self, doc, **body):
        return call(PortalDocumentDetailView, "patch", body, doc_id=doc.id)

    def mine(self):
        return make_doc("AWP-T1", status="completed", document_type="lab_report", by="human")

    def test_the_patient_can_set_and_clear_the_doctor_name(self, _r):
        doc = self.mine()
        resp = self.patch(doc, doctor_name="  Anita   Rao ")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(row(doc).doctor_name, "Anita Rao")
        self.assertEqual(resp.data["data"]["doctor_name"], "Anita Rao")
        self.assertEqual(self.patch(doc, doctor_name="").status_code, 200)
        self.assertEqual(row(doc).doctor_name, "")

    def test_a_typed_dr_prefix_is_not_stored(self, _r):
        doc = self.mine()
        self.patch(doc, doctor_name="Dr. Anita Rao")
        self.assertEqual(row(doc).doctor_name, "Anita Rao")

    def test_a_doctor_name_with_digits_or_symbols_is_refused(self, _r):
        doc = self.mine()
        for bad in ("Anita4", "Anita@Rao", "x" * 61):
            resp = self.patch(doc, doctor_name=bad)
            self.assertEqual(resp.status_code, 400, bad)
            self.assertEqual(resp.data["errors"], {"code": "invalid_doctor_name"})
        self.assertEqual(row(doc).doctor_name, "")

    def test_the_doctor_name_of_a_hospital_document_cannot_be_changed(self, _r):
        doc = hospital_issued()
        self.assertEqual(self.patch(doc, doctor_name="Anita Rao").status_code, 400)
        self.assertEqual(row(doc).doctor_name, "")

    def test_someone_elses_document_cannot_be_given_a_doctor(self, _r):
        other = make_doc("AWP-OTHER", status="completed", document_type="lab_report", by="human")
        with mock.patch("apps.patients.views.resolve_target_awpid_and_dob", return_value=("AWP-T1", None, None)):
            self.assertEqual(self.patch(other, doctor_name="Anita Rao").status_code, 404)
        self.assertEqual(row(other).doctor_name, "")

    def test_the_list_and_the_detail_carry_the_doctor_name(self, _r):
        doc = self.mine()
        self.patch(doc, doctor_name="Anita Rao")
        first = call(PortalDocumentListCreateView).data["results"][0]
        self.assertEqual(first["doctor_name"], "Anita Rao")
        detail = call(PortalDocumentDetailView, doc_id=doc.id).data["data"]
        self.assertEqual(detail["doctor_name"], "Anita Rao")

    def test_a_document_with_no_name_says_so_with_an_empty_string(self, _r):
        self.mine()
        self.assertEqual(call(PortalDocumentListCreateView).data["results"][0]["doctor_name"], "")


# ── deletable ─────────────────────────────────────────────────────────────────────────────────────────────────

@RESOLVE_PORTAL
class DeletableTests(TestCase):
    databases = {"default"}

    def setUp(self):
        identity("AWP-T1")

    def listed(self):
        return {r["id"]: r["deletable"] for r in call(PortalDocumentListCreateView, data={"review": "all"}).data["results"]}

    def test_a_failed_upload_can_be_deleted(self, _r):
        doc = make_doc("AWP-T1", status="failed")
        self.assertTrue(self.listed()[doc.id])
        self.assertTrue(call(PortalDocumentDetailView, doc_id=doc.id).data["data"]["deletable"])

    def test_a_confirmed_upload_cannot_be_deleted(self, _r):
        doc = make_doc("AWP-T1", status="completed", document_type="lab_report", by="human")
        self.assertFalse(self.listed()[doc.id])

    def test_a_hospital_issued_document_is_never_deletable(self, _r):
        doc = hospital_issued()
        failed = make_doc("AWP-T1", status="failed", created_by_type="H", source_hospital_id=7)
        listed = self.listed()
        self.assertFalse(listed[doc.id])
        self.assertFalse(listed[failed.id])

    def test_a_file_still_being_read_is_not_deletable(self, _r):
        doc = make_doc("AWP-T1", status="queued")
        self.assertFalse(self.listed()[doc.id])

    @override_settings(RECORDS_REVIEW_FROM="2000-01-01T00:00:00+00:00")
    def test_a_read_upload_waiting_for_confirmation_is_deletable(self, _r):
        waiting = make_doc("AWP-T1", status="completed", document_type="lab_report", by="rules")
        self.assertTrue(self.listed()[waiting.id])

    @override_settings(RECORDS_REVIEW_FROM="2000-01-01T00:00:00+00:00")
    def test_the_flag_always_agrees_with_the_rule_the_delete_call_uses(self, _r):
        docs = [
            make_doc("AWP-T1", status="failed"),
            make_doc("AWP-T1", status="queued"),
            make_doc("AWP-T1", status="completed", document_type="lab_report", by="rules"),
            make_doc("AWP-T1", status="completed", document_type="lab_report", by="human"),
            hospital_issued(),
        ]
        listed = self.listed()
        for doc in docs:
            self.assertEqual(listed[doc.id], records.is_patient_upload(doc) and records.can_discard(doc), doc.id)


# ── the By-date view and the uploaded_on filter ───────────────────────────────────────────────────────────────

@RESOLVE_PORTAL
class DaysTests(TestCase):
    databases = {"default"}

    def setUp(self):
        identity("AWP-T1")

    def days(self, **params):
        return call(PortalDocumentDaysView, data=params).data["data"]

    def test_files_are_grouped_by_upload_day_newest_first(self, _r):
        uploaded(at(2026, 5, 12))
        uploaded(at(2026, 5, 12, 13))
        uploaded(at(2026, 5, 3))
        data = self.days()
        self.assertEqual([(d["date"], d["total"]) for d in data["days"]], [("2026-05-12", 2), ("2026-05-03", 1)])

    def test_the_day_is_the_india_calendar_day_not_utc(self, _r):
        uploaded(at(2026, 5, 11, 18, 20))      # 23:50 on 11 May in India
        uploaded(at(2026, 5, 11, 18, 40))      # 00:10 on 12 May in India
        data = self.days()
        self.assertEqual([(d["date"], d["total"]) for d in data["days"]], [("2026-05-12", 1), ("2026-05-11", 1)])

    def test_yours_and_hospital_are_counted_apart_with_the_types(self, _r):
        uploaded(at(2026, 5, 12), "lab_report")
        uploaded(at(2026, 5, 12), "lab_report")
        uploaded(at(2026, 5, 12), "prescription", created_by_type="H", source_hospital_id=7)
        (day,) = self.days()["days"]
        self.assertEqual((day["total"], day["yours"], day["hospital"]), (3, 2, 1))
        self.assertEqual(day["by_type"], {"lab_report": 2, "prescription": 1})

    def test_years_are_listed_and_the_newest_is_the_default(self, _r):
        uploaded(at(2025, 11, 2))
        uploaded(at(2026, 1, 9))
        uploaded(at(2026, 2, 9))
        data = self.days()
        self.assertEqual(data["years"], [{"year": 2026, "count": 2}, {"year": 2025, "count": 1}])
        self.assertEqual((data["year"], len(data["days"])), (2026, 2))
        older = self.days(year=2025)
        self.assertEqual((older["year"], [d["date"] for d in older["days"]]), (2025, ["2025-11-02"]))

    def test_nothing_uploaded_gives_empty_lists(self, _r):
        self.assertEqual(self.days(), {"year": None, "years": [], "days": []})

    def test_another_patients_files_are_never_counted(self, _r):
        uploaded(at(2026, 5, 12))
        other = make_doc("AWP-OTHER", status="completed", document_type="lab_report", by="human")
        MedicalDocument.objects.filter(pk=other.pk).update(created_at=at(2026, 5, 12))
        self.assertEqual(self.days()["days"][0]["total"], 1)

    def test_a_bad_year_is_refused(self, _r):
        self.assertEqual(call(PortalDocumentDaysView, data={"year": "abc"}).status_code, 400)

    @override_settings(RECORDS_REVIEW_FROM="2000-01-01T00:00:00+00:00")
    def test_uploads_waiting_for_review_are_not_in_a_day(self, _r):
        waiting = make_doc("AWP-T1", status="completed", document_type="lab_report", by="rules")
        MedicalDocument.objects.filter(pk=waiting.pk).update(created_at=at(2026, 5, 12))
        uploaded(at(2026, 5, 12))
        (day,) = self.days()["days"]
        self.assertEqual(day["total"], 1)

    def test_the_day_count_equals_the_length_of_the_days_list(self, _r):
        for _ in range(3):
            uploaded(at(2026, 5, 12))
        uploaded(at(2026, 5, 11, 18, 40))       # 12 May in India too
        uploaded(at(2026, 5, 13))
        (day,) = [d for d in self.days()["days"] if d["date"] == "2026-05-12"]
        listed = call(PortalDocumentListCreateView, data={"uploaded_on": "2026-05-12"}).data["results"]
        self.assertEqual((day["total"], len(listed)), (4, 4))


@RESOLVE_PORTAL
class UploadedOnTests(TestCase):
    databases = {"default"}

    def setUp(self):
        identity("AWP-T1")

    def listing(self, **params):
        response = call(PortalDocumentListCreateView, data=params)
        return response, [r["id"] for r in response.data.get("results", [])]

    def test_only_that_days_files_come_back(self, _r):
        a = uploaded(at(2026, 5, 12))
        uploaded(at(2026, 5, 13))
        _resp, ids = self.listing(uploaded_on="2026-05-12")
        self.assertEqual(ids, [a.id])

    def test_it_combines_with_the_type_filter(self, _r):
        a = uploaded(at(2026, 5, 12), "lab_report")
        uploaded(at(2026, 5, 12), "prescription")
        _resp, ids = self.listing(uploaded_on="2026-05-12", doc_type="lab_report")
        self.assertEqual(ids, [a.id])

    def test_a_bad_date_is_refused(self, _r):
        response, _ids = self.listing(uploaded_on="12-05-2026")
        self.assertEqual(response.status_code, 400)
