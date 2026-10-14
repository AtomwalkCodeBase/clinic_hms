"""Timeline insights: the text of a document → the words it mentions with their dates (extract.py), and the endpoint that
looks them up in vocabulary.csv, merges repeats and filters."""
import datetime
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.hospital_patients.models import HospitalPatient
from apps.atomwalk.models import DocumentExtraction
from apps.records.tests.helpers import make_doc
from apps.records.tests.test_review import RESOLVE_RECORDS, call
from apps.records.timeline_insights import extract
from apps.records.views import StaffTimelineView, TimelineView
from core.authentication import MockUser

VISIT = """Date: 14/03/2026
DOB: 02/05/1990
Chief complaints: fever x 2 days. No cough.
Past history: known case of DM2 since 5 yrs. Father has hypertension.
Rx: Tab Metformin 500 mg BD, Tab Dolo 650 mg SOS
Lab done on 10 Mar 2026: anemia
"""


def entries(text, fixed_date=None):
    return extract.build_insights(text, fixed_date)["entries"]


def find(items, word):
    return next(e for e in items if e["word"] == word)


class ExtractTests(SimpleTestCase):
    def test_every_word_gets_the_date_written_in_the_document(self):
        items = entries(VISIT)
        self.assertEqual("2026-03-14", find(items, "fever")["date"])
        self.assertNotIn("1990-05-02", {e["date"] for e in items})           # a date of birth is not an event

    def test_a_date_on_the_same_line_wins_over_the_document_date(self):
        self.assertEqual("2026-03-10", find(entries(VISIT), "anemia")["date"])

    def test_a_patient_upload_with_no_date_is_undated_not_placed_on_the_upload_day(self):
        self.assertIsNone(find(entries("Patient has fever."), "fever")["date"])

    def test_a_misread_year_is_not_a_date(self):
        self.assertIsNone(find(entries("Date: 21 Sep 2614" + chr(10) + "Fever."), "fever")["date"])

    def test_a_hospital_document_gives_every_word_its_own_date(self):
        items = entries(VISIT, datetime.date(2025, 5, 1))
        self.assertEqual({"2025-05-01"}, {e["date"] for e in items})

    def test_the_word_is_stored_as_written_and_the_vocabulary_says_what_it_is(self):
        self.assertIn("dolo", {e["word"] for e in entries(VISIT)})
        self.assertEqual(("paracetamol", "medication", "unknown"), extract._vocabulary()["dolo"])
        self.assertEqual(("type 2 diabetes", "condition", "chronic"), extract._vocabulary()["dm2"])

    def test_a_medication_keeps_its_dose_and_frequency_and_the_next_drug_does_not_take_them(self):
        items = entries(VISIT)
        self.assertEqual(("500 mg BD", "650 mg SOS"), (find(items, "metformin")["dose"], find(items, "dolo")["dose"]))
        self.assertIsNone(find(items, "fever")["dose"])

    def test_negated_family_and_history_are_flagged(self):
        items = entries(VISIT)
        self.assertTrue(find(items, "cough")["negated"])
        self.assertTrue(find(items, "hypertension")["family"])
        self.assertEqual("history", find(items, "dm2")["when"])
        self.assertEqual("current", find(items, "fever")["when"])

    def test_a_suspected_condition_is_flagged(self):
        self.assertTrue(find(entries("Date: 10/01/2025" + chr(10) + "Asthma is suspected but not confirmed."), "asthma")["uncertain"])

    def test_a_resolved_finding_is_marked_resolved(self):
        items = entries("Date: 08/11/2023" + chr(10) + "Fever and cough resolved.")
        self.assertEqual({"resolved"}, {e["when"] for e in items})

    def test_a_disease_name_on_a_vaccine_line_is_not_a_diagnosis(self):
        self.assertEqual([], entries("Date: 26/02/2022" + chr(10) + "Hepatitis B - birth dose - given on 16-Jan-2022"))

    def test_the_word_birth_does_not_hide_the_date_on_its_line(self):
        fever = find(entries("Date: 26/02/2022" + chr(10) + "Fever noted at the birth check on 16-Jan-2022"), "fever")
        self.assertEqual("2022-01-16", fever["date"])

    def test_a_product_name_is_not_a_symptom(self):
        words = [e["word"] for e in entries("Date: 14/03/2026" + chr(10) + "Cough Syrup (200ml)" + chr(10) + "Patient has cough.")]
        self.assertEqual(["cough"], words)


@override_settings(RECORDS_REVIEW_FROM="2000-01-01T00:00:00+00:00")
class TimelineEndpointTests(TestCase):
    databases = {"default"}

    def setUp(self):
        self.jan = self.confirmed("Date: 10/01/2026" + chr(10) + "Diabetes. Fever.")
        self.jun = self.confirmed("Date: 20/06/2026" + chr(10) + "Diabetes. Cough. No headache.")

    def confirmed(self, text, **fields):
        doc = make_doc("AWP-T1", status="completed", document_type="lab_report", by="human", text=text, **fields)
        extract.run_insights(doc.id)
        return doc

    def get(self, **params):
        with RESOLVE_RECORDS:
            return call(TimelineView, "get", data=params)

    def body(self, **params):
        return self.get(**params).data["data"]

    def days(self, **params):
        return self.body(**params)["days"]

    def names(self, **params):
        return [e["name"] for d in self.days(**params) for e in d["entries"]]

    def test_findings_are_grouped_by_date_newest_first(self):
        self.assertEqual(["2026-06-20", "2026-01-10"], [d["date"] for d in self.days()])

    def test_the_date_range_and_the_name_filter_narrow_it_down(self):
        self.assertEqual(["2026-06-20"], [d["date"] for d in self.days(**{"from": "2026-03-01"})])
        self.assertEqual(["2026-01-10"], [d["date"] for d in self.days(to="2026-03-01")])
        self.assertEqual(["diabetes mellitus"] * 2, self.names(name="diabet"))

    def test_acute_or_chronic_comes_from_the_vocabulary(self):
        self.assertEqual(["diabetes mellitus"] * 2, self.names(nature="chronic"))
        self.assertEqual({"fever", "cough"}, set(self.names(kind="symptom")))
        self.assertEqual({"acute"}, {e["nature"] for d in self.days(kind="symptom") for e in d["entries"]})

    def test_a_negated_mention_is_hidden_unless_asked_for(self):
        self.assertNotIn("headache", self.names())
        self.assertIn("headache", self.names(include_hidden="1"))

    def test_an_upload_the_patient_has_not_confirmed_is_not_on_the_timeline(self):
        doc = make_doc("AWP-T1", status="completed", document_type="lab_report", by="rules", text="Date: 01/02/2026" + chr(10) + "Malaria.")
        extract.run_insights(doc.id)
        self.assertNotIn("malaria", self.names())

    def test_each_finding_lists_the_reports_it_comes_from(self):
        source = self.days()[0]["entries"][0]["sources"][0]
        self.assertEqual(("lab_report", self.jun.id), (source["document_type"], source["document_id"]))

    def test_a_source_says_which_hospital_issued_it_and_a_patient_upload_has_none(self):
        self.assertEqual("", self.days()[0]["entries"][0]["sources"][0]["hospital"])

    def test_the_same_finding_in_two_reports_on_one_day_shows_once_with_both_sources(self):
        self.confirmed("Date: 20/06/2026" + chr(10) + "Diabetes.")
        entry = next(e for d in self.days() for e in d["entries"] if d["date"] == "2026-06-20" and e["name"] == "diabetes mellitus")
        self.assertEqual(2, len(entry["sources"]))
        self.assertEqual(2, self.names().count("diabetes mellitus"))          # one on 20 June, one on 10 January

    def test_a_condition_that_resolved_is_marked_resolved_and_never_chronic(self):
        self.confirmed("Date: 20/05/2024" + chr(10) + "ANEMIA FOLLOW-UP" + chr(10) + "Iron deficiency anemia resolved.")
        entry = self.days(name="anemia")[0]["entries"][0]
        self.assertEqual(("resolved", "unknown"), (entry["when"], entry["nature"]))

    def test_a_suspected_condition_is_hidden_unless_asked_for(self):
        self.confirmed("Date: 10/02/2026" + chr(10) + "Asthma is suspected but not confirmed.")
        self.assertEqual([], self.days(name="asthma"))
        self.assertEqual("unknown", self.days(name="asthma", include_hidden="1")[0]["entries"][0]["nature"])

    def test_a_finding_with_no_date_is_listed_apart(self):
        self.confirmed("Patient has fever.")
        self.assertEqual(["fever"], [e["name"] for e in self.body()["undated"]])
        self.assertEqual([], self.body(**{"from": "2020-01-01"})["undated"])

    def test_a_hospital_document_is_read_from_its_file_and_dated_by_the_hospital(self):
        doc = make_doc("AWP-T1", status="completed", document_type="prescription", by="issued", uploaded_by="staff",
                       source_hospital_id="3", document_date=datetime.date(2025, 5, 1))
        with mock.patch.object(extract, "_read_file", return_value=b"%PDF"), \
                mock.patch.object(extract, "extract_text", return_value=("Date: 01/01/2020" + chr(10) + "Fever, cough.", "pdf_text")):
            extract.run_insights(doc.id)
        self.assertTrue(DocumentExtraction.objects.filter(document=doc).exists())
        self.assertIn("2025-05-01", [d["date"] for d in self.days(name="fever")])

    def test_a_word_no_longer_in_the_vocabulary_is_skipped(self):
        with mock.patch.object(extract, "_vocabulary", return_value={}):
            self.assertEqual({"days": [], "undated": []}, extract.build_timeline("AWP-T1"))

    def test_the_patient_does_not_get_the_medications(self):
        self.confirmed("Date: 10/03/2026" + chr(10) + "Tab Metformin 500 mg BD.")
        self.assertNotIn("metformin", self.names())

    def test_a_doctor_gets_the_medications_with_their_dose(self):
        self.confirmed("Date: 10/03/2026" + chr(10) + "Tab Metformin 500 mg BD.")
        days = extract.build_timeline("AWP-T1", audience="staff")["days"]
        metformin = next(e for d in days for e in d["entries"] if e["name"] == "metformin")
        self.assertEqual(("medication", "500 mg BD"), (metformin["kind"], metformin["dose"]))

    def test_without_the_patients_consent_a_doctor_gets_only_this_hospitals_documents(self):
        make_doc("AWP-T1", status="completed", document_type="prescription", by="issued", uploaded_by="staff", source_hospital_id="3",
                 document_date=datetime.date(2025, 5, 1), text="Tab Metformin 500 mg BD.")
        extract.run_all(redo=True)
        names = lambda **kw: {e["name"] for d in extract.build_timeline("AWP-T1", audience="staff", **kw)["days"] for e in d["entries"]}
        self.assertIn("diabetes mellitus", names())                          # the patient's own uploads, with consent
        self.assertEqual({"metformin"}, names(hospital_id=3))                  # only what hospital 3 issued
        self.assertEqual(set(), names(hospital_id=4))

    def staff_get(self, role="doctor", consent=True):
        """The doctor's endpoint for a patient of hospital 3 (the hospital lookup is faked: there is no hospital database here)."""
        request = APIRequestFactory().get("/x/", {"include_hidden": "1"})
        request.hospital_db, request.hospital_id = "default", 3
        force_authenticate(request, user=MockUser({"user_id": 2, "role": role}))
        patient = SimpleNamespace(pk=1, awpid="AWP-T1", hie_consent_given=consent)
        with mock.patch.object(HospitalPatient, "objects") as objects, mock.patch("core.audit.log_action") as audit:
            objects.using.return_value.filter.return_value.first.return_value = patient
            return StaffTimelineView.as_view()(request, pk=1), audit

    def test_the_doctors_endpoint_returns_the_medications_and_says_whether_the_patient_consented(self):
        self.confirmed("Date: 10/03/2026" + chr(10) + "Tab Metformin 500 mg BD.")
        response, audit = self.staff_get(consent=True)
        data = response.data["data"]
        self.assertEqual((200, True), (response.status_code, data["consent_given"]))
        self.assertIn("metformin", [e["name"] for d in data["days"] for e in d["entries"]])
        audit.assert_called_once()

    def test_without_consent_the_doctors_endpoint_hides_other_sources_and_says_so(self):
        self.confirmed("Date: 10/03/2026" + chr(10) + "Tab Metformin 500 mg BD.")
        data = self.staff_get(consent=False)[0].data["data"]
        self.assertEqual((False, []), (data["consent_given"], data["days"]))      # none of these documents came from hospital 3

    def test_only_a_doctor_or_nurse_may_use_the_doctors_endpoint(self):
        self.assertEqual(403, self.staff_get(role="patient")[0].status_code)

    def test_a_bad_date_is_refused(self):
        self.assertEqual(400, self.get(**{"from": "yesterday"}).status_code)
