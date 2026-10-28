"""apps/documents/tests/tests_clinical.py — lab trends, medicine history, data gaps and plain-language results."""
from datetime import date, timedelta
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.documents import integration as ig, lib_clinical, views_timeline as views
from apps.documents.models import DocumentExtraction, LabResult, MedicalDocument
from apps.documents.tests.tests_timeline import child, document, with_config
from core.api.authentication import MockUser


def lab(kid, analyte, value, on, severity="NORMAL", direction=""):
    return LabResult.objects.create(patient=kid, analyte=analyte, value=value, collected_on=on, severity=severity, direction=direction)


@with_config
class LabTrendTests(TestCase):
    databases = {"default"}

    def setUp(self):
        self.kid = child(years=10)
        lab(self.kid, "HEMOGLOBIN_G_DL", 12.4, date.today() - timedelta(days=400))
        lab(self.kid, "HEMOGLOBIN_G_DL", 9.8, date.today() - timedelta(days=30), "ABNORMAL", "LOW")
        lab(self.kid, "CRP_MG_L", 3, date.today() - timedelta(days=30))

    def test_abnormal_results_come_first_with_their_range_and_direction_of_change(self):
        trends = lib_clinical.lab_trends(self.kid)
        self.assertEqual([t["analyte"] for t in trends], ["HEMOGLOBIN_G_DL", "CRP_MG_L"])
        hb = trends[0]
        self.assertEqual((hb["label"], hb["unit"], hb["trend"], hb["latest_severity"]), ("Haemoglobin", "g/dL", "down", "ABNORMAL"))
        self.assertEqual(len(hb["points"]), 2)
        self.assertTrue(hb["points"][-1]["reference"])                      # the range for this age is shown


@with_config
class GapsAndMedicinesTests(TestCase):
    databases = {"default"}

    def setUp(self):
        self.kid = child(years=3)

    def test_a_failed_report_and_missing_measurements_are_listed_as_gaps(self):
        doc = document(self.kid)
        DocumentExtraction.objects.filter(document=doc).update(status=DocumentExtraction.Status.FAILED)
        gaps = lib_clinical.data_gaps(self.kid)
        texts = " | ".join(i["text"] for i in gaps["items"])
        self.assertIn("could not be read", texts)
        self.assertIn("No weight or height has been recorded", texts)
        self.assertEqual(gaps["reports"]["FAILED"], 1)
        self.assertEqual(gaps["items"][0]["documents"][0]["document_id"], doc.pk)


@with_config
class AccessTests(TestCase):
    databases = {"default"}

    def test_the_clinical_summary_is_for_doctors_only(self):
        kid = child()

        def get(view, role):
            request = APIRequestFactory().get("/x/")
            force_authenticate(request, user=MockUser({"user_id": 1, "role": role, "awpid": "AW-KID" if role == "patient" else None, "hospital_id": None if role == "patient" else 1}))
            with mock.patch.object(ig, "can_view_patient", return_value=True):
                return view.as_view()(request, awpid=kid.awpid).status_code
        self.assertEqual(get(views.PatientClinicalSummaryView, "patient"), 403)
        self.assertEqual(get(views.PatientClinicalSummaryView, "doctor"), 200)


@with_config
class OneResultListedOnceTests(TestCase):
    databases = {"default"}

    def test_the_test_done_most_recently_is_listed_first_even_if_an_older_one_was_abnormal(self):
        kid = child(years=10)
        lab(kid, "BILIRUBIN_TOTAL_MG_DL", 14.9, date.today() - timedelta(days=3000), "ABNORMAL", "HIGH")
        lab(kid, "CRP_MG_L", 3, date.today() - timedelta(days=10))
        lab(kid, "HEMOGLOBIN_G_DL", 9.0, date.today() - timedelta(days=400), "ABNORMAL", "LOW")
        self.assertEqual([t["analyte"] for t in lib_clinical.lab_trends(kid)], ["CRP_MG_L", "HEMOGLOBIN_G_DL", "BILIRUBIN_TOTAL_MG_DL"])

    def test_a_result_quoted_by_two_reports_is_listed_once(self):
        kid = child(years=10)
        on = date.today() - timedelta(days=40)
        lab(kid, "PLATELETS_PER_UL", 38000, on, "ABNORMAL", "LOW")
        lab(kid, "PLATELETS_PER_UL", 38000, on, "ABNORMAL", "LOW")           # the same value again, from another report
        lab(kid, "PLATELETS_PER_UL", 54000, on - timedelta(days=2), "ABNORMAL", "LOW")
        trend = lib_clinical.lab_trends(kid)[0]
        self.assertEqual([p["value"] for p in trend["points"]], [54000, 38000])


@with_config
class GrowthReferenceNoteTests(TestCase):
    databases = {"default"}

    def test_the_note_names_only_the_reference_tables_that_are_loaded(self):
        kid = child(years=3)
        request = APIRequestFactory().get("/x/", {"indicator": "weight_kg"})
        force_authenticate(request, user=MockUser({"user_id": 1, "role": "doctor", "hospital_id": 1}))
        with mock.patch.object(ig, "can_view_patient", return_value=True):
            with mock.patch.object(views, "get_table", return_value=None):
                self.assertEqual(views.PatientGrowthView.as_view()(request, awpid=kid.awpid).data["reference_note"], "WHO 2006 (0-5 y)")
            with mock.patch.object(views, "get_table", return_value=object()):
                self.assertIn("5-18 y", views.PatientGrowthView.as_view()(request, awpid=kid.awpid).data["reference_note"])
