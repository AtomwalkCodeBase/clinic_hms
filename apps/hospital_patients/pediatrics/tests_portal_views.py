"""
The patient portal's pediatric endpoints: growth, vaccinations (list / upload / certificate), milestones and family.
They only touch the atomwalk database, so these run under a plain `manage.py test`.
"""
import datetime as dt
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.hospital_patients.pediatrics import portal_views as views
from core.testing import ensure_hospital
from apps.atomwalk.models import (
    MilestoneScheduleRule, PatientAccount, Patient, PatientRelationship, MilestoneRecord,
    ImmunizationRecord, GrowthMeasurement, Vitals)
from core.authentication import MockUser

V = ImmunizationRecord


class PortalPediatricTests(TestCase):
    databases = {"default"}

    def setUp(self):
        ensure_hospital(1)
        self.mom = PatientAccount.objects.using("default").create(
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
        slot = MilestoneScheduleRule.objects.using("default").first()          # a slot of the seeded default schedule
        MilestoneRecord.objects.using("default").create(
            patient=self.kid, domain=slot.domain, milestone=slot.milestone, scheduled_label=slot.scheduled_label,
            status="achieved", achieved_date=dt.date.today(), assessed_date=dt.date.today())
        data = self.call(views.PortalMilestoneListView, query="?patient_awpid=AW-KID").data["data"]
        self.assertEqual(sum(1 for r in data["roadmap"] if r["status"] == "achieved"), 1)
        self.assertEqual(data["achieved_count"], 1)

    # ── uploads ───────────────────────────────────────────────────────────────
    def upload(self, **body):
        return self.call(views.PortalVaccinationUploadView, "post", {"patient_awpid": "AW-KID", **body})

    def test_a_parent_upload_waits_for_review(self):
        resp = self.upload(vaccine_name=" Polio ", administered_date="2025-03-04", scheduled_label="6 weeks")
        self.assertEqual(resp.status_code, 200)
        record = V.objects.using("default").get()
        self.assertEqual((record.patient.awpid, record.vaccine_name, record.source, record.verification_status, record.recorded_by),
                         ("AW-KID", "Polio", V.SOURCE_SELF_REPORTED, V.STATUS_PENDING, "patient"))

    def test_an_upload_needs_a_name_and_a_plausible_date(self):
        self.assertEqual(self.upload(administered_date="2025-03-04").status_code, 400)
        self.assertEqual(self.upload(vaccine_name="Polio").status_code, 400)
        for bad in ("04/03/2025", "82026-10-02", "1850-01-01", (dt.date.today() + timedelta(days=2)).isoformat()):
            self.assertEqual(self.upload(vaccine_name="Polio", administered_date=bad).status_code, 400, bad)
        self.assertEqual(V.objects.using("default").count(), 0)

    def test_a_certificate_is_stored_and_named_after_the_vaccine(self):
        with mock.patch.object(views, "validate_data_uri", return_value="image/png"), \
                mock.patch.object(views.blob_storage, "upload_data_uri", return_value="vaccination-certs/a.png"), \
                mock.patch.object(views.blob_storage, "display_file_name", return_value="Polio - Kid.png"):
            resp = self.upload(vaccine_name="Polio", administered_date="2025-03-04", file_data="data:image/png;base64,AAAA")
        self.assertEqual(resp.status_code, 200)
        record = V.objects.using("default").get()
        self.assertEqual((record.file_data, record.file_name, record.mime_type), ("vaccination-certs/a.png", "Polio - Kid.png", "image/png"))

    def test_an_oversized_or_invalid_certificate_is_refused(self):
        too_big = "x" * (views._MAX_CERTIFICATE_CHARS + 1)
        self.assertEqual(self.upload(vaccine_name="Polio", administered_date="2025-03-04", file_data=too_big).status_code, 400)
        self.assertEqual(self.upload(vaccine_name="Polio", administered_date="2025-03-04", file_data="nope").status_code, 400)
        self.assertEqual(V.objects.using("default").count(), 0)

    # ── certificate file ──────────────────────────────────────────────────────
    def test_a_certificate_can_be_opened_by_the_account_or_its_family_only(self):
        mine = self.vaccination(awpid="AW-MOM", file_data="k/mine.png", file_name="mine.png", mime_type="image/png")
        kids = self.vaccination(file_data="k/kid.png", file_name="kid.png", mime_type="image/png")
        theirs = self.vaccination(awpid="AW-STRANGER", file_data="k/x.png")
        with mock.patch.object(views.blob_storage, "signed_url", side_effect=lambda key: f"https://signed/{key}"):
            self.assertEqual(self.call(views.PortalVaccinationFileView, record_id=mine.id).data["data"]["file_data"], "https://signed/k/mine.png")
            self.assertEqual(self.call(views.PortalVaccinationFileView, record_id=kids.id).status_code, 200)
            self.assertEqual(self.call(views.PortalVaccinationFileView, record_id=theirs.id).status_code, 403)
        self.assertEqual(self.call(views.PortalVaccinationFileView, record_id=999999).status_code, 404)
        no_file = self.vaccination(vaccine_name="MMR")
        self.assertEqual(self.call(views.PortalVaccinationFileView, record_id=no_file.id).status_code, 404)

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
