"""Vaccination / milestone schedule JSON shapes (shared by the org and platform_admin views)."""

from datetime import datetime, timezone
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.registry.models import MilestoneSchedule, VaccinationSchedule
from apps.registry.schedule_dicts import milestone_rule_dict, schedule_dict, template_dict, vaccination_rule_dict
from core.authentication import MockUser


class ShapeTests(SimpleTestCase):
    def test_vaccination_rule(self):
        rule = SimpleNamespace(id=1, vaccine_name="BCG", dose_number=1, scheduled_label="At birth", min_age_days=0,
                               max_age_days=30, mandatory=True, sort_order=1)
        self.assertEqual(vaccination_rule_dict(rule), {
            "id": 1, "vaccine_name": "BCG", "dose_number": 1, "scheduled_label": "At birth",
            "min_age_days": 0, "max_age_days": 30, "mandatory": True, "sort_order": 1})

    def test_milestone_rule(self):
        rule = SimpleNamespace(id=2, domain="motor", milestone="Sits", scheduled_label="6 months", min_age_days=150,
                               max_age_days=210, mandatory=False, sort_order=3)
        self.assertEqual(set(milestone_rule_dict(rule)), {"id", "domain", "milestone", "scheduled_label",
                                                         "min_age_days", "max_age_days", "mandatory", "sort_order"})

    def test_schedule_marks_the_hospitals_active_one_and_counts_rules(self):
        s = SimpleNamespace(id=5, name="Std", description="d", is_template=False, active=True, owner_tenant_id=9,
                            rules=SimpleNamespace(count=lambda: 12))
        self.assertTrue(schedule_dict(s, active_id=5)["is_active_for_this_hospital"])
        self.assertFalse(schedule_dict(s, active_id=6)["is_active_for_this_hospital"])
        self.assertFalse(schedule_dict(s)["is_active_for_this_hospital"])
        self.assertEqual(schedule_dict(s)["rule_count"], 12)
        self.assertEqual(schedule_dict(s, rule_count=3)["rule_count"], 3)

    def test_template(self):
        when = datetime(2026, 1, 2, tzinfo=timezone.utc)
        s = SimpleNamespace(id=1, name="T", description="", active=True, created_at=when, updated_at=when,
                            rules=SimpleNamespace(count=lambda: 4))
        out = template_dict(s, tenants_using=2)
        self.assertEqual((out["rule_count"], out["tenants_using"], out["created_at"]), (4, 2, when.isoformat()))


class PlatformTemplateListTests(TestCase):
    """The platform-admin template lists (registry DB only) keep working on the shared helpers."""
    databases = {"default"}

    def get(self, view):
        request = APIRequestFactory().get("/x/")
        force_authenticate(request, user=MockUser({"user_id": 1, "role": "platform_admin", "is_platform": True}))
        return view.as_view()(request)

    def test_vaccination_templates(self):
        from apps.platform_admin.vaccination_template_views import VaccinationTemplateListCreateView
        VaccinationSchedule.objects.using("default").create(name="India UIP", is_template=True)
        resp = self.get(VaccinationTemplateListCreateView)
        self.assertEqual(resp.status_code, 200)
        names = [t["name"] for t in resp.data["data"]]
        self.assertIn("India UIP", names)
        row = next(t for t in resp.data["data"] if t["name"] == "India UIP")
        self.assertEqual((row["rule_count"], row["tenants_using"]), (0, 0))

    def test_milestone_templates(self):
        from apps.platform_admin.milestone_template_views import MilestoneTemplateListCreateView
        MilestoneSchedule.objects.using("default").create(name="WHO milestones", is_template=True)
        resp = self.get(MilestoneTemplateListCreateView)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("WHO milestones", [t["name"] for t in resp.data["data"]])
