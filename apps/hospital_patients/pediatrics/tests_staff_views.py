"""
The staff-side pediatric endpoints: growth, vaccinations (list / log / verify / order / decline / administer),
birth history and milestones. These need a hospital database: run with --settings=atomwalk.settings.test.
"""
import datetime as dt
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest import mock


from apps.hospital_patients.pediatrics import growth_vaccination_views as vax_views
from apps.hospital_patients.pediatrics import pediatric_views as ped_views
from apps.atomwalk.models import BirthHistory, GrowthMeasurement, ImmunizationRecord, MilestoneRecord, Patient
from core.testing import HospitalDBTestCase, requires_hospital_db

V = ImmunizationRecord


@requires_hospital_db
class PediatricStaffTests(HospitalDBTestCase):
    def setUp(self):
        super().setUp()
        from apps.opd.models import Appointment
        from apps.org.models import Branch
        from apps.hospital_patients.models import HospitalPatient
        from apps.hospitals.models import Hospital

        db = self.hospital_alias
        self.hospital = Hospital.objects.using("default").create(name="Peds H", subdomain="peds-h", db_name=db)
        self.branch = Branch.objects.using(db).create(name="Main")
        self.child = HospitalPatient.objects.using(db).create(
            awpid="AW-KID-1", uhid="UHID-K1", branch=self.branch, full_name="Kid One", gender="F",
            date_of_birth=dt.date.today() - timedelta(days=730), is_dependent=True,
        )
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

    # ── growth ────────────────────────────────────────────────────────────────
    def test_growth_shows_this_hospitals_readings_with_percentiles_for_a_young_child(self):
        self.add_vitals(height_cm=Decimal("85"), weight_kg=Decimal("12"))
        data = self.call(vax_views.PatientGrowthView, "get").data["data"]
        self.assertTrue(data["is_minor"])
        point = data["series"][0]
        self.assertEqual((point["source"], point["height_cm"], point["weight_kg"]), ("this_hospital", 85.0, 12.0))
        self.assertIn("weight", point["percentiles"])
        self.assertTrue(data["percentile_available"])

    def test_growth_hides_other_hospitals_readings_until_the_patient_consents(self):
        GrowthMeasurement.objects.using("default").create(
            patient=self.shared, measured_on=dt.date.today() - timedelta(days=30), weight_kg=Decimal("11"),
            source_hospital_id=self.hospital.id + 1)
        self.assertEqual(self.call(vax_views.PatientGrowthView, "get").data["data"]["series"], [])
        type(self.child).objects.using(self.hospital_alias).filter(pk=self.child.pk).update(hie_consent_given=True)
        series = self.call(vax_views.PatientGrowthView, "get").data["data"]["series"]
        self.assertEqual([p["source"] for p in series], ["other_hospital"])
        self.assertNotIn("percentiles", series[0])

    def test_growth_for_an_adult_has_no_percentiles(self):
        type(self.child).objects.using(self.hospital_alias).filter(pk=self.child.pk).update(
            date_of_birth=dt.date.today() - timedelta(days=365 * 40))
        self.add_vitals(height_cm=Decimal("170"), weight_kg=Decimal("70"))
        data = self.call(vax_views.PatientGrowthView, "get").data["data"]
        self.assertFalse(data["is_minor"])
        self.assertFalse(data["percentile_available"])

    def test_growth_for_an_unknown_patient_is_not_found(self):
        self.assertEqual(self.call(vax_views.PatientGrowthView, "get", pk=999999).status_code, 404)

    # ── vaccinations: roadmap and logging ─────────────────────────────────────
    def test_the_roadmap_lists_the_schedule_and_marks_a_recorded_dose_completed(self):
        self.vax()
        roadmap = self.call(vax_views.PatientVaccinationListCreateView, "get").data["data"]["roadmap"]
        bcg = next(r for r in roadmap if r["vaccine_name"] == "BCG")
        self.assertEqual(bcg["status"], "completed")
        self.assertTrue(any(r["status"] == "unknown" for r in roadmap))

    def test_only_a_doctor_or_nurse_can_log_a_dose_but_any_staff_can_read_the_roadmap(self):
        view = vax_views.PatientVaccinationListCreateView
        body = {"vaccine_name": "BCG", "administered_date": "2026-01-01"}
        for role in ("front_desk", "pharmacist", "lab_tech"):
            self.assertEqual(self.call(view, "post", role=role, data=body).status_code, 403, role)
            self.assertEqual(self.call(view, "get", role=role).status_code, 200, role)
        self.assertEqual(self.call(view, "post", role="nurse", data=body).status_code, 201)

    def test_logging_a_vaccination_needs_a_name_and_date_and_is_verified_on_the_spot(self):
        view = vax_views.PatientVaccinationListCreateView
        self.assertEqual(self.call(view, "post", data={"administered_date": "2026-01-01"}).status_code, 400)
        self.assertEqual(self.call(view, "post", data={"vaccine_name": "BCG"}).status_code, 400)
        resp = self.call(view, "post", data={"vaccine_name": " BCG ", "administered_date": "2026-01-01", "scheduled_label": "Birth"})
        self.assertEqual(resp.status_code, 201)
        record = V.objects.using("default").get(pk=resp.data["data"]["id"])
        self.assertEqual((record.vaccine_name, record.source, record.verification_status, record.source_hospital_id),
                         ("BCG", V.SOURCE_CLINIC, V.STATUS_VERIFIED, self.hospital.id))
        self.assertFalse(resp.data["data"]["has_certificate"])

    def test_bad_or_future_dates_are_refused_not_crashed_on(self):
        log, order = vax_views.PatientVaccinationListCreateView, vax_views.PatientVaccinationOrderView
        for bad in ("82026-10-02", "yesterday", "02/03/2026", "1850-01-01", (dt.date.today() + timedelta(days=2)).isoformat()):
            resp = self.call(log, "post", data={"vaccine_name": "BCG", "administered_date": bad})
            self.assertEqual(resp.status_code, 400, bad)
        self.assertEqual(V.objects.using("default").count(), 0)
        self.assertEqual(self.call(order, "post", data={"vaccine_name": "Flu", "reason": "r", "due_date": "garbage"}).status_code, 400)
        later = (dt.date.today() + timedelta(days=60)).isoformat()
        self.assertEqual(self.call(order, "post", data={"vaccine_name": "Flu", "reason": "r", "due_date": later}).status_code, 201)   # a target date may be ahead
        admin = vax_views.PatientVaccinationAdministerView
        self.assertEqual(self.call(admin, "post", data={"vaccine_name": "MMR", "administered_date": "nonsense"}).status_code, 400)

    def test_the_same_dose_cannot_be_recorded_twice(self):
        log, admin = vax_views.PatientVaccinationListCreateView, vax_views.PatientVaccinationAdministerView
        body = {"vaccine_name": "MMR", "administered_date": "2026-01-01", "dose_number": 1}
        self.assertEqual(self.call(log, "post", data=body).status_code, 201)
        self.assertEqual(self.call(log, "post", data={**body, "vaccine_name": " mmr "}).status_code, 409)       # same dose, different spelling
        self.assertEqual(self.call(admin, "post", data=body).status_code, 409)
        self.assertEqual(self.call(log, "post", data={**body, "dose_number": 2}).status_code, 201)            # the next dose is fine
        self.assertEqual(self.call(log, "post", data={**body, "administered_date": "2026-02-01"}).status_code, 201)
        self.assertEqual(V.objects.using("default").count(), 3)

    def test_a_certificate_is_validated_and_stored_with_the_record(self):
        with mock.patch.object(vax_views.blob_storage, "upload_data_uri", return_value="vaccination-certs/k.png") as up, \
                mock.patch.object(vax_views, "validate_data_uri", return_value="image/png"):
            resp = self.call(vax_views.PatientVaccinationListCreateView, "post",
                             data={"vaccine_name": "BCG", "administered_date": "2026-01-01", "file_data": "data:image/png;base64,AAAA"})
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.data["data"]["has_certificate"])
        self.assertEqual(V.objects.using("default").get().file_data, "vaccination-certs/k.png")
        up.assert_called_once()

    def test_a_bad_certificate_is_refused_and_nothing_is_saved(self):
        resp = self.call(vax_views.PatientVaccinationListCreateView, "post",
                         data={"vaccine_name": "BCG", "administered_date": "2026-01-01", "file_data": "not-a-data-uri"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(V.objects.using("default").count(), 0)

    # ── vaccinations: review ──────────────────────────────────────────────────
    def test_staff_verify_or_reject_a_parents_upload(self):
        pending = self.vax(source=V.SOURCE_SELF_REPORTED, verification_status=V.STATUS_PENDING, source_hospital_id=None)
        view = vax_views.PatientVaccinationVerifyView
        self.assertEqual(self.call(view, "patch", data={"action": "maybe"}, pk=pending.pk).status_code, 400)
        self.assertEqual(self.call(view, "patch", role="nurse", data={"action": "reject", "review_notes": " blurry "}, pk=pending.pk).status_code, 200)
        pending.refresh_from_db()
        self.assertEqual((pending.verification_status, pending.review_notes, pending.source_hospital_id),
                         (V.STATUS_REJECTED, "blurry", self.hospital.id))
        self.call(view, "patch", data={"action": "verify"}, pk=pending.pk)
        pending.refresh_from_db()
        self.assertEqual(pending.verification_status, V.STATUS_VERIFIED)
        self.assertEqual(self.call(view, "patch", data={"action": "verify"}, pk=999999).status_code, 404)

    # ── vaccinations: order, decline, administer ──────────────────────────────
    def test_only_a_doctor_can_order_a_vaccine_and_it_needs_a_reason(self):
        view = vax_views.PatientVaccinationOrderView
        self.assertEqual(self.call(view, "post", role="nurse", data={"vaccine_name": "Flu", "reason": "x"}).status_code, 403)
        self.assertEqual(self.call(view, "post", data={"reason": "x"}).status_code, 400)
        self.assertEqual(self.call(view, "post", data={"vaccine_name": "Flu"}).status_code, 400)
        resp = self.call(view, "post", data={"vaccine_name": "Flu", "reason": "asthma", "due_date": "2026-12-01", "dose_number": 1})
        self.assertEqual(resp.status_code, 201)
        record = V.objects.using("default").get()
        self.assertEqual((record.source, record.verification_status, record.administered_date, record.reason),
                         (V.SOURCE_DOCTOR_ORDERED, V.STATUS_ORDERED, None, "asthma"))

    def test_a_doctor_declines_a_slot_with_no_record_by_creating_one(self):
        view = vax_views.PatientVaccinationDeclineView
        self.assertEqual(self.call(view, "post", role="nurse", data={"vaccine_name": "BCG"}).status_code, 403)
        self.assertEqual(self.call(view, "post", data={}).status_code, 400)
        resp = self.call(view, "post", data={"vaccine_name": "BCG", "scheduled_label": "Birth", "reason": "had it abroad"})
        self.assertEqual(resp.status_code, 200)
        record = V.objects.using("default").get()
        self.assertEqual((record.verification_status, record.reason, record.review_notes, record.source_hospital_id),
                         (V.STATUS_DECLINED, "had it abroad", "had it abroad", self.hospital.id))

    def test_declining_an_existing_record_updates_it_but_only_for_this_patient(self):
        ordered = self.vax(source=V.SOURCE_DOCTOR_ORDERED, verification_status=V.STATUS_ORDERED, reason="old reason")
        view = vax_views.PatientVaccinationDeclineView
        self.call(view, "post", data={"record_id": ordered.id})
        ordered.refresh_from_db()
        self.assertEqual((ordered.verification_status, ordered.reason), (V.STATUS_DECLINED, "old reason"))
        stranger = self.vax(awpid="AW-OTHER")
        self.assertEqual(self.call(view, "post", data={"record_id": stranger.id}).status_code, 404)

    def test_administering_closes_a_doctors_order_in_place(self):
        ordered = self.vax(vaccine_name="Flu", source=V.SOURCE_DOCTOR_ORDERED, verification_status=V.STATUS_ORDERED, source_hospital_id=None)
        resp = self.call(vax_views.PatientVaccinationAdministerView, "post", role="nurse",
                         data={"record_id": ordered.id, "dose_number": 2})
        self.assertEqual(resp.status_code, 200)
        ordered.refresh_from_db()
        self.assertEqual((ordered.source, ordered.verification_status, ordered.dose_number, ordered.source_hospital_id),
                         (V.SOURCE_CLINIC, V.STATUS_VERIFIED, 2, self.hospital.id))
        self.assertEqual(ordered.administered_date, dt.date.today())
        self.assertEqual(V.objects.using("default").count(), 1)

    def test_administering_without_a_record_creates_one_and_needs_a_name(self):
        view = vax_views.PatientVaccinationAdministerView
        self.assertEqual(self.call(view, "post", data={}).status_code, 400)
        resp = self.call(view, "post", data={"vaccine_name": "MMR", "administered_date": "2026-02-02", "dose_number": 1})
        self.assertEqual(resp.status_code, 200)
        record = V.objects.using("default").get()
        self.assertEqual((record.vaccine_name, str(record.administered_date), record.verification_status),
                         ("MMR", "2026-02-02", V.STATUS_VERIFIED))
        self.assertEqual(self.call(view, "post", data={"record_id": 999999}).status_code, 404)

    def test_a_new_certificate_replaces_the_old_file_when_administering(self):
        ordered = self.vax(source=V.SOURCE_DOCTOR_ORDERED, verification_status=V.STATUS_ORDERED, file_data="old/key.png")
        with mock.patch.object(vax_views.blob_storage, "upload_data_uri", return_value="new/key.png"), \
                mock.patch.object(vax_views, "validate_data_uri", return_value="image/png"), \
                mock.patch.object(vax_views.blob_storage, "delete") as delete:
            self.call(vax_views.PatientVaccinationAdministerView, "post",
                      data={"record_id": ordered.id, "file_data": "data:image/png;base64,AAAA"})
        ordered.refresh_from_db()
        self.assertEqual(ordered.file_data, "new/key.png")
        delete.assert_called_once_with("old/key.png")

    # ── birth history ─────────────────────────────────────────────────────────
    def test_birth_history_is_created_once_edited_and_copied_to_the_atomwalk(self):
        view = ped_views.BirthHistoryView
        self.assertIsNone(self.call(view, "get").data["data"])
        body = {"gestational_age_weeks": 38, "birth_weight_kg": "3.1", "delivery_mode": "normal"}
        self.assertEqual(self.call(view, "post", role="nurse", data=body).status_code, 403)
        self.assertEqual(self.call(view, "post", role="front_desk", data=body).status_code, 201)
        self.assertEqual(self.call(view, "post", data=body).status_code, 400)        # already exists
        self.assertEqual(self.call(view, "patch", data={"apgar_score_5min": 9}).status_code, 200)
        shared = BirthHistory.objects.using("default").get(patient__awpid=self.child.awpid)
        self.assertEqual((shared.gestational_age_weeks, shared.apgar_score_5min, shared.source_hospital_id), (38, 9, self.hospital.id))
        self.assertEqual(self.call(view, "get").data["data"]["gestational_age_weeks"], 38)

    def test_birth_history_changes_are_written_to_the_audit_log(self):
        from apps.org.models import AuditLog
        view = ped_views.BirthHistoryView
        self.call(view, "post", data={"gestational_age_weeks": 38, "delivery_mode": "normal"})
        self.call(view, "patch", data={"gestational_age_weeks": 36, "notes": "late preterm"})
        rows = list(AuditLog.objects.using(self.hospital_alias).filter(resource_type="BirthHistory").order_by("id"))
        self.assertEqual([r.action for r in rows], ["birth_history.create", "birth_history.update"])
        self.assertEqual(rows[1].metadata["changed"]["gestational_age_weeks"], ["38", "36"])
        self.assertEqual(rows[1].patient_id, self.child.uuid)

    def test_the_audit_log_notes_when_another_hospitals_birth_history_is_replaced(self):
        from apps.org.models import AuditLog
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
