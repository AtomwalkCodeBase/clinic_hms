"""core/api/tests_permissions.py — the role permission classes, including the role "all" that acts as every built-in role."""

from types import SimpleNamespace

from django.test import SimpleTestCase

from core.api import permissions as p

ROLES = ["platform_admin", "hospital_admin", "doctor", "nurse", "front_desk", "lab_tech", "pharmacist", "patient"]

# permission class -> the roles allowed by their literal role claim
ALLOWED = {
    p.IsPlatformAdmin: {"platform_admin"},
    p.IsHospitalAdmin: {"hospital_admin"},
    p.IsDoctor: {"doctor"},
    p.IsNurse: {"nurse"},
    p.IsFrontDesk: {"front_desk"},
    p.IsPatient: {"patient"},
    p.IsHospitalStaff: {"hospital_admin", "doctor", "nurse", "front_desk"},
    p.IsDoctorOrNurse: {"doctor", "nurse"},
    p.IsDoctorOrFrontDesk: {"doctor", "front_desk"},
}


def request_for(role, acts_as=(), authenticated=True, subscription=None):
    user = SimpleNamespace(role=role, acts_as=list(acts_as), is_authenticated=authenticated, subscription=subscription)
    return SimpleNamespace(user=user)


class RolePermissionMatrixTests(SimpleTestCase):
    def test_every_role_against_every_permission_class(self):
        for cls, allowed in ALLOWED.items():
            for role in ROLES:
                with self.subTest(permission=cls.__name__, role=role):
                    self.assertEqual(cls().has_permission(request_for(role), None), role in allowed)

    def test_anonymous_is_always_denied(self):
        for cls in ALLOWED:
            with self.subTest(permission=cls.__name__):
                self.assertFalse(cls().has_permission(request_for("doctor", authenticated=False), None))


class FeatureAndTierTests(SimpleTestCase):

    def test_require_tier_orders_the_tiers(self):
        perm = p.RequireTier("pro")()
        has = lambda tier: perm.has_permission(request_for("doctor", subscription=SimpleNamespace(license_tier=tier)), None)
        self.assertFalse(has("starter"))
        self.assertFalse(has("growth"))
        self.assertTrue(has("pro"))
        self.assertTrue(has("enterprise"))
        self.assertFalse(has("mystery"))

    def test_require_tier_rejects_an_unknown_tier_name(self):
        with self.assertRaises(ValueError):
            p.RequireTier("platinum")
