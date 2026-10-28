from apps.hospital_setup.staff_views import HospitalSettingsView
from apps.hospital_master.models import Hospital, HospitalParameters
from core.tests.testing import HospitalDBTestCase, requires_hospital_db


@requires_hospital_db
class HospitalSettingsAccessTests(HospitalDBTestCase):
    def get(self, role):
        hospital = Hospital.objects.using("default").create(name="T", hospital_code="t", db_name="x")
        HospitalParameters.objects.using("default").create(hospital=hospital, fee_ownership="hospital")
        return self.call_view(HospitalSettingsView.as_view(), "get", "/api/v1/org/settings/",
                              user_id=1, role=role, hospital_id=hospital.pk)

    def test_doctor_reads_only_fee_ownership(self):
        resp = self.get("doctor")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"], {"fee_ownership": "hospital"})

    def test_admin_reads_full_config(self):
        resp = self.get("hospital_admin")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("default_tax_rate", resp.data["data"])

    def test_doctor_cannot_patch(self):
        resp = self.call_view(HospitalSettingsView.as_view(), "patch", "/api/v1/org/settings/",
                              user_id=1, role="doctor", data={"fee_ownership": "doctor"})
        self.assertEqual(resp.status_code, 403)
