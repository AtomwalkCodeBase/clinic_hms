"""The generic OptionList views moved to billing.option_list_views; every consumer must still list."""

from core.testing import TenantDBTestCase, requires_tenant_db

from apps.billing.views import ServiceCategoryListCreateView
from apps.ipd.views import AdmissionTypeListCreateView
from apps.opd.views import AppointmentTypeListCreateView


@requires_tenant_db
class OptionListViewTests(TenantDBTestCase):
    def get(self, view, role="front_desk"):
        return self.call_view(view.as_view(), "get", "/x/", user_id=1, role=role)

    def test_list_endpoints_built_on_the_shared_views_still_work(self):
        for view in (ServiceCategoryListCreateView, AdmissionTypeListCreateView, AppointmentTypeListCreateView):
            with self.subTest(view=view.__name__):
                resp = self.get(view)
                self.assertEqual(resp.status_code, 200)
                self.assertTrue(resp.data["success"])

    def test_adding_an_entry_needs_a_hospital_admin(self):
        resp = self.call_view(ServiceCategoryListCreateView.as_view(), "post", "/x/", user_id=1,
                              role="front_desk", data={"name": "Dental"})
        self.assertEqual(resp.status_code, 403)
        resp = self.call_view(ServiceCategoryListCreateView.as_view(), "post", "/x/", user_id=1,
                              role="hospital_admin", data={"name": "Dental"})
        self.assertEqual(resp.status_code, 201, resp.data)
        again = self.call_view(ServiceCategoryListCreateView.as_view(), "post", "/x/", user_id=1,
                               role="hospital_admin", data={"name": "Dental"})
        self.assertEqual(again.status_code, 400)
