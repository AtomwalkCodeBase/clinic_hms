from apps.org.views import TenantSettingsView
from apps.tenants.models import Tenant
from core.testing import TenantDBTestCase, requires_tenant_db


@requires_tenant_db
class TenantSettingsAccessTests(TenantDBTestCase):
    def get(self, role):
        tenant = Tenant.objects.using("default").create(name="T", subdomain="t", db_name="x", fee_ownership="hospital")
        return self.call_view(TenantSettingsView.as_view(), "get", "/api/v1/org/settings/",
                              user_id=1, role=role, tenant_id=tenant.id)

    def test_doctor_reads_only_fee_ownership(self):
        resp = self.get("doctor")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"], {"fee_ownership": "hospital"})

    def test_admin_reads_full_config(self):
        resp = self.get("hospital_admin")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("default_tax_rate", resp.data["data"])

    def test_doctor_cannot_patch(self):
        resp = self.call_view(TenantSettingsView.as_view(), "patch", "/api/v1/org/settings/",
                              user_id=1, role="doctor", data={"fee_ownership": "doctor"})
        self.assertEqual(resp.status_code, 403)
