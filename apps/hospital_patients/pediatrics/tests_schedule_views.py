"""
The schedule endpoints, hospital-admin and platform-admin, for BOTH kinds (vaccination and milestone): the two kinds
must behave the same way, so every test runs once per kind.
"""
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.org import urls as org_urls
from apps.platform_admin import urls as platform_urls
from apps.atomwalk.models import Schedule
from apps.hospitals.models import Hospital
from core.authentication import MockUser
from core.testing import ensure_hospital

# per kind: (kind, view-name stem, hospital column, the rule key holding the name, the kind-specific rule key + value)
KINDS = {
    "vaccination": dict(stem="Vaccination", column="active_vaccination_schedule_id", name_key="vaccine_name",
                        extra={"dose_number": 2}),
    "milestone": dict(stem="Milestone", column="active_milestone_schedule_id", name_key="milestone",
                      extra={"domain": "gross_motor"}),
}


def rule(kind, name, **kw):
    spec = KINDS[kind]
    return {spec["name_key"]: name, "scheduled_label": "6 months", "min_age_days": 180, **spec["extra"], **kw}


class ScheduleEndpointTests(TestCase):
    databases = {"default"}

    def setUp(self):
        self.hospital = Hospital.objects.using("default").create(name="T", subdomain="t", db_name="x", fee_ownership="hospital")

    def call(self, view, method, data=None, role="hospital_admin", pk=None):
        request = getattr(APIRequestFactory(), method)("/x/", data, format="json")
        request.hospital_id = self.hospital.id
        force_authenticate(request, user=MockUser({"user_id": 1, "role": role, "is_platform": role == "platform_admin",
                                                   "hospital_id": self.hospital.id}))
        return view.as_view()(request, **({"pk": pk} if pk else {}))

    def view(self, module, kind, suffix):
        return getattr(module, f"{KINDS[kind]['stem']}{suffix}")

    def platform(self, kind, method, data=None, pk=None, detail=False):
        suffix = "TemplateDetailView" if detail else "TemplateListCreateView"
        return self.call(self.view(platform_urls, kind, suffix), method, data, "platform_admin", pk)

    def as_staff(self, kind, method, data=None, pk=None, suffix="ScheduleListCreateView"):
        return self.call(self.view(org_urls, kind, suffix), method, data, "hospital_admin", pk)

    def make_template(self, kind, rules=None):
        resp = self.platform(kind, "post", {"name": f"{kind} std", "rules": rules or [rule(kind, "A"), rule(kind, "B")]})
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.data["data"]["id"]

    # ── platform admin: templates ─────────────────────────────────────────────
    def test_a_template_is_created_with_its_rules_and_can_be_read_back(self):
        for kind in KINDS:
            with self.subTest(kind):
                pk = self.make_template(kind)
                data = self.platform(kind, "get", pk=pk, detail=True).data["data"]
                self.assertEqual([r[KINDS[kind]["name_key"]] for r in data["rules"]], ["A", "B"])
                self.assertEqual(Schedule.objects.get(pk=pk).kind, kind)
                listed = self.platform(kind, "get").data["data"]
                self.assertEqual([t["id"] for t in listed if t["id"] == pk], [pk])

    def test_each_kind_only_lists_its_own_templates(self):
        v, m = self.make_template("vaccination"), self.make_template("milestone")
        vaccination_ids = {t["id"] for t in self.platform("vaccination", "get").data["data"]}
        milestone_ids = {t["id"] for t in self.platform("milestone", "get").data["data"]}
        self.assertTrue(v in vaccination_ids and m not in vaccination_ids)
        self.assertTrue(m in milestone_ids and v not in milestone_ids)

    def test_a_template_needs_a_name_and_invalid_rules_are_skipped(self):
        for kind in KINDS:
            with self.subTest(kind):
                self.assertEqual(self.platform(kind, "post", {"name": " "}).status_code, 400)
                bad = [rule(kind, "ok"), {"scheduled_label": "x", "min_age_days": 1}, rule(kind, "no-age", min_age_days=None)]
                pk = self.make_template(kind, bad)
                self.assertEqual(len(self.platform(kind, "get", pk=pk, detail=True).data["data"]["rules"]), 1)

    def test_a_milestone_rule_with_an_unknown_domain_is_skipped(self):
        pk = self.make_template("milestone", [rule("milestone", "ok"), rule("milestone", "bad", domain="nonsense")])
        self.assertEqual(len(self.platform("milestone", "get", pk=pk, detail=True).data["data"]["rules"]), 1)

    def test_patching_a_template_updates_deletes_and_adds_rules(self):
        for kind in KINDS:
            with self.subTest(kind):
                key = KINDS[kind]["name_key"]
                pk = self.make_template(kind)
                first, second = self.platform(kind, "get", pk=pk, detail=True).data["data"]["rules"]
                resp = self.platform(kind, "patch", {"name": "Renamed", "active": False, "rules": [
                    {"id": first["id"], key: "A2", "min_age_days": 10},
                    {"id": second["id"], "_delete": True},
                    rule(kind, "C"),
                ]}, pk=pk, detail=True)
                self.assertEqual(resp.status_code, 200, resp.data)
                data = resp.data["data"]
                self.assertEqual((data["name"], data["active"]), ("Renamed", False))
                self.assertEqual([(r[key], r["min_age_days"]) for r in data["rules"]], [("A2", 10), ("C", 180)])

    def test_a_template_in_use_cannot_be_deleted_but_an_unused_one_can(self):
        for kind in KINDS:
            with self.subTest(kind):
                pk = self.make_template(kind)
                Hospital.objects.using("default").filter(pk=self.hospital.pk).update(**{KINDS[kind]["column"]: pk})
                self.assertEqual(self.platform(kind, "delete", pk=pk, detail=True).status_code, 400)
                Hospital.objects.using("default").filter(pk=self.hospital.pk).update(**{KINDS[kind]["column"]: None})
                self.assertEqual(self.platform(kind, "delete", pk=pk, detail=True).status_code, 200)
                self.assertFalse(Schedule.objects.filter(pk=pk).exists())

    # ── hospital admin: schedules ─────────────────────────────────────────────
    def test_a_hospital_clones_a_template_and_it_becomes_active(self):
        for kind in KINDS:
            with self.subTest(kind):
                key = KINDS[kind]["name_key"]
                template = self.make_template(kind)
                resp = self.as_staff(kind, "post", {"template_id": template})
                self.assertEqual(resp.status_code, 201, resp.data)
                clone_id = resp.data["data"]["id"]
                clone = Schedule.objects.get(pk=clone_id)
                self.assertEqual((clone.kind, clone.owner_hospital_id, clone.is_template), (kind, self.hospital.id, False))
                self.assertEqual(getattr(Hospital.objects.using("default").get(pk=self.hospital.pk), KINDS[kind]["column"]), clone_id)
                detail = self.as_staff(kind, "get", pk=clone_id, suffix="ScheduleDetailView").data["data"]
                self.assertEqual([r[key] for r in detail["rules"]], ["A", "B"])
                self.assertEqual(detail["rules"][0][next(iter(KINDS[kind]["extra"]))], next(iter(KINDS[kind]["extra"].values())))

    def test_cloning_needs_a_real_template(self):
        for kind in KINDS:
            with self.subTest(kind):
                self.assertEqual(self.as_staff(kind, "post", {}).status_code, 400)
                self.assertEqual(self.as_staff(kind, "post", {"template_id": 999999}).status_code, 404)

    def test_the_hospital_list_shows_its_own_schedules_and_the_templates(self):
        for kind in KINDS:
            with self.subTest(kind):
                template = self.make_template(kind)
                clone = self.as_staff(kind, "post", {"template_id": template}).data["data"]["id"]
                data = self.as_staff(kind, "get").data["data"]
                self.assertEqual([s["id"] for s in data["own_schedules"]], [clone])
                self.assertIn(template, [s["id"] for s in data["templates"]])   # next to the seeded default template
                self.assertEqual(data["active_schedule_id"], clone)

    def test_a_hospital_edits_only_its_own_schedule_never_a_template(self):
        for kind in KINDS:
            with self.subTest(kind):
                template = self.make_template(kind)
                self.assertEqual(self.as_staff(kind, "patch", {"name": "x"}, pk=template, suffix="ScheduleDetailView").status_code, 404)
                clone = self.as_staff(kind, "post", {"template_id": template}).data["data"]["id"]
                resp = self.as_staff(kind, "patch", {"name": "Mine", "rules": [rule(kind, "Z")]}, pk=clone, suffix="ScheduleDetailView")
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.data["data"]["name"], "Mine")
                self.assertEqual(len(resp.data["data"]["rules"]), 3)

    def test_a_hospital_can_activate_a_template_directly_but_not_another_hospitals_schedule(self):
        for kind in KINDS:
            with self.subTest(kind):
                template = self.make_template(kind)
                resp = self.as_staff(kind, "post", pk=template, suffix="ScheduleActivateView")
                self.assertEqual(resp.status_code, 200, resp.data)
                self.assertEqual(getattr(Hospital.objects.using("default").get(pk=self.hospital.pk), KINDS[kind]["column"]), template)
                other = Schedule.objects.create(kind=kind, name="theirs", owner_hospital=ensure_hospital(self.hospital.id + 1000))
                self.assertEqual(self.as_staff(kind, "post", pk=other.id, suffix="ScheduleActivateView").status_code, 400)
                self.assertEqual(self.as_staff(kind, "get", pk=other.id, suffix="ScheduleDetailView").status_code, 404)

    def test_an_id_of_the_other_kind_is_not_found(self):
        milestone = self.make_template("milestone")
        self.assertEqual(self.platform("vaccination", "get", pk=milestone, detail=True).status_code, 404)
        self.assertEqual(self.as_staff("vaccination", "post", pk=milestone, suffix="ScheduleActivateView").status_code, 404)

    # ── rule numbers ──────────────────────────────────────────────────────────
    def test_rule_numbers_must_be_whole_numbers_and_the_maximum_cannot_be_below_the_minimum(self):
        for kind in KINDS:
            with self.subTest(kind):
                for bad in ({"min_age_days": "abc"}, {"min_age_days": -5}, {"min_age_days": 1.5},
                            {"min_age_days": 100, "max_age_days": 10}, {"sort_order": -1}):
                    resp = self.platform(kind, "post", {"name": f"T-{kind}", "rules": [rule(kind, "A", **bad)]})
                    self.assertEqual(resp.status_code, 400, bad)
                self.assertFalse(Schedule.objects.filter(name=f"T-{kind}").exists())          # nothing is created when a rule is wrong
                ok = self.platform(kind, "post", {"name": f"T-{kind}", "rules": [rule(kind, "A", min_age_days="180", max_age_days=365)]})
                self.assertEqual(ok.status_code, 201, ok.data)

    def test_a_bad_rule_in_an_edit_changes_nothing_and_clearing_the_maximum_is_allowed(self):
        for kind in KINDS:
            with self.subTest(kind):
                key = KINDS[kind]["name_key"]
                pk = self.make_template(kind, [rule(kind, "A", min_age_days=100, max_age_days=200)])
                first = self.platform(kind, "get", pk=pk, detail=True).data["data"]["rules"][0]
                bad = self.platform(kind, "patch", {"name": "Renamed", "rules": [
                    {"id": first["id"], key: "A2"}, {"id": first["id"], "max_age_days": 50}]}, pk=pk, detail=True)
                self.assertEqual(bad.status_code, 400)
                data = self.platform(kind, "get", pk=pk, detail=True).data["data"]
                self.assertEqual((data["name"], data["rules"][0][key]), (f"{kind} std", "A"))                 # untouched
                self.assertEqual(self.platform(kind, "patch", {"rules": [{"id": first["id"], "min_age_days": 300}]}, pk=pk, detail=True).status_code, 400)
                cleared = self.platform(kind, "patch", {"rules": [{"id": first["id"], "max_age_days": None}]}, pk=pk, detail=True)
                self.assertEqual(cleared.status_code, 200)
                self.assertIsNone(cleared.data["data"]["rules"][0]["max_age_days"])
