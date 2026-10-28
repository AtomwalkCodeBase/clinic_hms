"""Reading what the OCR gives back when it ran words together ("Hexaximdose2", "ImmunisationVisit-10Weeks"), and My Documents paging
that must hold every document exactly once. The rules themselves are in lib_documents (documents) and services/immunization (vaccines)."""
import datetime
from unittest import mock

from django.test import SimpleTestCase, TestCase

from apps.documents import lib_documents as rules
from apps.documents.services import text_clean
from apps.documents.services.immunization import resolve_vaccines
from apps.documents.tests.tests_doctor_and_days import RESOLVE_PORTAL, at, call, uploaded
from apps.patients.views import PortalDocumentListCreateView, _my_documents_qs


# ── the text helpers ──────────────────────────────────────────────────────────────────────────────────────────

class TextCleanTests(SimpleTestCase):
    def test_a_capital_after_a_lower_case_letter_is_a_cut_word(self):
        self.assertIn("immunisation visit-10weeks", text_clean.views("ImmunisationVisit-10Weeks"))

    def test_a_letter_right_after_a_sign_starts_a_new_word(self):
        self.assertIn("patient: aarav rao sex: male", text_clean.views("Patient:AaravRaoSex:Male"))

    def test_a_digit_next_to_a_letter_is_never_cut(self):
        for token in ("PCV13", "B12", "500mg", "Covid19", "hba1c"):
            self.assertEqual(text_clean.views(token), [token.lower()] * 3)

    def test_a_name_with_a_capital_inside_is_still_found_as_it_was_written(self):
        self.assertEqual(text_clean.views("HbA1c")[0], "hba1c")        # the cut view says "hb a1c", the first view keeps the name whole

    def test_a_word_stuck_to_capitals_is_cut_either_way(self):
        both = text_clean.views("OPVdose3 DOBMale")
        self.assertTrue(any("opv dose3" in v for v in both))
        self.assertTrue(any("dob male" in v for v in both))

    def test_the_first_view_is_the_text_as_it_was(self):
        self.assertEqual(text_clean.views("Rx Tab PCM")[0], "rx tab pcm")
        self.assertEqual(text_clean.views(None), ["", "", ""])

    def test_a_long_keyword_is_found_with_its_neighbours_glued_on(self):
        text = "Vaccinesgiventoday: Hexaximdose2"
        words, squashed = text_clean.tokens(text), text_clean.squash(text)
        self.assertTrue(text_clean.glued_in("hexaxim", words, squashed))
        self.assertTrue(text_clean.glued_in("vaccine", words, squashed))

    def test_a_short_keyword_is_never_found_inside_a_longer_word(self):
        text = "summary opvx rxy tablet hibiscus pentagon"
        for short in ("mmr", "opv", "rx", "tab", "hib", "tcv", "penta"):
            self.assertFalse(text_clean.glued_in(short, text_clean.tokens(text), text_clean.squash(text)), short)

    def test_an_ordinary_word_that_holds_a_keyword_is_not_glue(self):
        text = "Appointment slip, a misdiagnosis, the dispensary"
        for word in ("ointment", "diagnosis", "dispense"):
            self.assertFalse(text_clean.glued_in(word, text_clean.tokens(text), text_clean.squash(text)), word)

    def test_a_phrase_with_a_one_letter_word_is_never_squashed(self):
        text = "Hepatitis antigen test"
        self.assertFalse(text_clean.glued_in("hepatitis a", text_clean.tokens(text), text_clean.squash(text)))


# ── the document rules on text the OCR ran together ───────────────────────────────────────────────────────

GLUED_VISIT = ("Rao Child Clinic Dr.A.Rao,Paediatrician ImmunisationVisit-10Weeks Patient:AaravRaoSex:Male DOB:18Sep2023 "
               "Weight4.6kg Vaccinesgiventoday:Hexaximdose2,Rotavirusdose2,PCVdose2,OPVdose2")


class GluedTextRuleTests(SimpleTestCase):
    def kind(self, text):
        return rules.classify_document_by_rules(text)["document_type"]

    def test_a_vaccination_visit_the_ocr_ran_together_is_still_a_vaccination_record(self):
        self.assertEqual(self.kind(GLUED_VISIT), "vaccination_record")

    def test_a_bill_whose_heading_is_one_word_is_still_a_bill(self):
        self.assertEqual(self.kind("LIFELINESUPERSPECIALITYHOSPITAL PATIENTBILLCUMRECEIPT Billno 1042 Totalamount 3514 Rupeesthreethousandonly"), "medical_bill")

    def test_the_heading_wins_over_a_body_that_talks_about_something_else(self):
        text = "Atomwalk Hospital Discharge Summary Date of admission 18 Sep 2023 Date of discharge 24 Sep 2023 Vaccines given at birth: BCG, OPV, Hepatitis B"
        self.assertEqual(self.kind(text), "discharge_summary")

    def test_a_heading_phrase_far_down_the_page_is_not_a_heading(self):
        filler = "lorem ipsum dolor sit amet " * 30
        top = rules.calculate_document_scores("discharge summary " + filler)["discharge_summary"]["matched_rules"]
        deep = rules.calculate_document_scores(filler + "discharge summary")["discharge_summary"]["matched_rules"]
        self.assertIn("heading", [m["level"] for m in top])
        self.assertNotIn("heading", [m["level"] for m in deep])

    def test_an_appointment_slip_is_not_a_prescription(self):
        scores = rules.calculate_document_scores("Unity Hospital APPOINTMENT SLIP Dr. Rao Doctor Appointment on 12 Nov")
        self.assertEqual([m["keyword"] for m in scores["prescription"]["matched_rules"]], ["doctor", "dr"])

    def test_a_bill_needs_something_of_health_care_on_it(self):
        shop = "Bright Electronics Tax Invoice GSTIN 29ABCDE Bill No 77 Total Amount 4999 Net Payable 4999 290, MG Road, Kochi Thank you for your business"
        self.assertEqual(self.kind(shop), "not_classified")
        self.assertEqual(self.kind(shop + " Pharmacy"), "medical_bill")
        self.assertEqual(self.kind("City Hospital Patient Bill Invoice Bill No 12 Total Amount 3500 Net Payable 3500 GSTIN 29ABCDE"), "medical_bill")

    def test_an_accession_number_alone_does_not_make_a_lab_report_an_imaging_report(self):
        lab = "ANUVIDA HEALTH LABS Laboratory Patient ID HN710678 AccessionNo:XR425268 Sample type Serum Sample collected NABL accredited Result Method"
        self.assertEqual(self.kind(lab), "lab_report")
        self.assertEqual(self.kind("Radiology Report Accession No: XR1 Findings: normal study Impression: no fracture. X-ray chest PA view"), "imaging_report")

    def test_a_discharge_summary_written_as_summary_of_hospital_stay(self):
        self.assertEqual(self.kind("SURYA HOSPITAL Summary of Hospital Stay Date of admission 2 Nov Date of discharge 9 Nov Tab Paracetamol 500 mg syp"), "discharge_summary")

    def test_a_short_keyword_is_still_a_word_of_its_own(self):
        for text in ("summary of xerox copies", "hibiscus tea and pentagon", "abnormality opvx"):
            scores = rules.calculate_document_scores(text)
            self.assertEqual(scores["prescription"]["score"], 0, text)
            self.assertEqual(scores["vaccination_record"]["score"], 0, text)

    def test_nothing_changes_for_text_that_was_already_clean(self):
        for text, expected in (("Tab Metformin 500 mg twice daily after food Rx", "prescription"), ("Hemoglobin 13.6 g/dL WBC 7800 Platelets 250000 Reference Range", "lab_report"),
                               ("hello world", "not_classified")):
            self.assertEqual(self.kind(text), expected)


# ── vaccine names ─────────────────────────────────────────────────────────────────────────────────────────

class GluedVaccineNameTests(SimpleTestCase):
    def test_a_name_the_ocr_ran_into_its_neighbours_is_recognised(self):
        parts = ["DTwP/DTaP", "Hepatitis B", "Hib", "IPV"]
        self.assertEqual(resolve_vaccines("Hexaximdose2"), parts)
        self.assertEqual(resolve_vaccines("Hexaxim dose 2"), parts)
        self.assertEqual(resolve_vaccines("DTPbooster 1"), ["DTwP/DTaP"])
        self.assertEqual(resolve_vaccines("Rotavirusdose2"), ["Rotavirus"])
        self.assertEqual(resolve_vaccines("OPVdose3"), ["OPV"])
        self.assertEqual(resolve_vaccines("MMRdose1"), ["MMR"])
        self.assertEqual(resolve_vaccines("Influenzavaccine"), ["Influenza"])

    def test_names_that_were_already_found_still_are(self):
        self.assertEqual(resolve_vaccines("Pentavalent-2"), ["DTwP/DTaP", "Hepatitis B", "Hib"])
        self.assertEqual(resolve_vaccines("PCV13 dose 3"), ["Pneumococcal (PCV)"])
        self.assertEqual(resolve_vaccines("Hepatitis A dose 1"), ["Hepatitis A"])
        self.assertEqual(resolve_vaccines("polio drops"), ["OPV"])

    def test_words_that_only_look_like_a_vaccine_are_not(self):
        for text in ("Hepatitis antigen test", "pentagon", "summary", "hibiscus tea", "Zzzz made up vaccine", "", None):
            self.assertEqual(resolve_vaccines(text), [], text)


# ── My Documents paging ───────────────────────────────────────────────────────────────────────────────────

class PagingTests(TestCase):
    databases = {"default"}

    def test_the_list_is_ordered_by_upload_time_then_id(self):
        qs, _ = _my_documents_qs("AWP-T1", "all")
        self.assertEqual(tuple(qs.query.order_by), ("-created_at", "-pk"))

    def test_files_uploaded_together_are_paged_without_repeats_or_gaps(self):
        same = at(2026, 10, 27)
        docs = [uploaded(same) for _ in range(20)]
        seen = []
        with RESOLVE_PORTAL:
            for page in (1, 2, 3):
                response = call(PortalDocumentListCreateView, data={"page": page, "page_size": 7})
                self.assertEqual(response.status_code, 200)
                seen += [r["medical_document_id"] for r in response.data["results"]]
        self.assertEqual(seen, sorted((d.pk for d in docs), reverse=True))

    def test_newest_upload_comes_first_across_different_times(self):
        old = uploaded(at(2026, 10, 1))
        new_a, new_b = uploaded(at(2026, 10, 27)), uploaded(at(2026, 10, 27))
        with RESOLVE_PORTAL:
            ids = [r["medical_document_id"] for r in call(PortalDocumentListCreateView, data={"page_size": 10}).data["results"]]
        self.assertEqual(ids, [new_b.pk, new_a.pk, old.pk])
