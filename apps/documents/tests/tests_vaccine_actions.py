from apps.documents import views as vax_views
from apps.documents.models import ImmunizationRecord as V
from core.tests.testing import HospitalDBTestCase, ensure_hospital, make_branch, make_patient


class StaffVaccineActionTests(HospitalDBTestCase):
    def setUp(self):
        super().setUp()
        ensure_hospital(1)
        branch, _place = make_branch(self.hospital_alias)
        self.patient = make_patient(self.hospital_alias, "AWP-V9", uhid="U-9", branch=branch, full_name="V9")

    def act(self, view, role, **data):
        return self.call_view(view.as_view(), "post", "/x", user_id=7, role=role, hospital_id=1, data=data, view_kwargs={"pk": self.patient.pk})

    def test_a_doctor_can_order_a_vaccine(self):
        resp = self.act(vax_views.PatientVaccinationOrderView, "doctor", vaccine_name="MMR", reason="due now")
        self.assertEqual(resp.status_code, 201)
        record = V.objects.using("default").get()
        self.assertEqual((record.verification_status, record.remarks), (V.STATUS_ORDERED, "due now"))

    def test_a_nurse_can_mark_a_dose_given(self):
        resp = self.act(vax_views.PatientVaccinationAdministerView, "nurse", vaccine_name="BCG", dose_number=1)
        self.assertEqual(resp.status_code, 200)
        record = V.objects.using("default").get()
        self.assertEqual((record.verification_status, record.source), (V.STATUS_VERIFIED, V.SOURCE_CLINIC))
        self.assertIsNotNone(record.administered_date)

    def test_an_ordered_dose_can_then_be_given(self):
        self.act(vax_views.PatientVaccinationOrderView, "doctor", vaccine_name="MMR", reason="due")
        record = V.objects.using("default").get()
        self.act(vax_views.PatientVaccinationAdministerView, "nurse", record_id=record.id)
        record.refresh_from_db()
        self.assertEqual(record.verification_status, V.STATUS_VERIFIED)

    def test_a_doctor_can_mark_a_slot_not_required(self):
        resp = self.act(vax_views.PatientVaccinationDeclineView, "doctor", vaccine_name="Hepatitis B", reason="given elsewhere")
        self.assertEqual(resp.status_code, 200)
        record = V.objects.using("default").get()
        self.assertEqual((record.verification_status, record.remarks), (V.STATUS_DECLINED, "given elsewhere"))

    def test_a_certificate_sent_with_a_dose_is_refused_not_dropped(self):
        resp = self.act(vax_views.PatientVaccinationAdministerView, "nurse", vaccine_name="BCG", file_data="data:application/pdf;base64,AAAA")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(V.objects.using("default").count(), 0)
