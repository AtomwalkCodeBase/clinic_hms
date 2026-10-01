"""core/tests_permissions.py — the role permission classes, including hospital-defined roles that act as built-ins."""

from types import SimpleNamespace

from django.test import SimpleTestCase

from core import permissions as p

ROLES = ["platform_admin", "hospital_admin", "doctor", "nurse", "front_desk", "lab_tech", "pharmacist", "patient"]

# permission class -> the roles allowed by their literal role claim
ALLOWED = {
    p.IsPlatformAdmin: {"platform_admin"},
    p.IsHospitalAdmin: {"hospital_admin"},
    p.IsDoctor: {"doctor"},
    p.IsNurse: {"nurse"},
    p.IsFrontDesk: {"front_desk"},
    p.IsLabTech: {"lab_tech"},
    p.IsPharmacist: {"pharmacist"},
    p.IsPatient: {"patient"},
    p.IsHospitalStaff: {"hospital_admin", "doctor", "nurse", "front_desk", "lab_tech", "pharmacist"},
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

    def test_a_custom_role_acts_as_only_the_roles_it_lists(self):
        req = request_for("custom", acts_as=["doctor", "front_desk"])
        self.assertTrue(p.IsDoctor().has_permission(req, None))
        self.assertTrue(p.IsFrontDesk().has_permission(req, None))
        self.assertTrue(p.IsDoctorOrNurse().has_permission(req, None))
        self.assertTrue(p.IsDoctorOrFrontDesk().has_permission(req, None))
        self.assertFalse(p.IsNurse().has_permission(req, None))
        self.assertFalse(p.IsPharmacist().has_permission(req, None))
        self.assertFalse(p.IsHospitalAdmin().has_permission(req, None))

    def test_a_custom_role_is_hospital_staff_but_never_platform_admin_or_patient(self):
        req = request_for("custom", acts_as=["hospital_admin", "doctor"])
        self.assertTrue(p.IsHospitalStaff().has_permission(req, None))
        self.assertFalse(p.IsPlatformAdmin().has_permission(req, None))
        self.assertFalse(p.IsPatient().has_permission(req, None))

    def test_a_custom_role_with_no_acts_as_gets_no_specific_role(self):
        req = request_for("custom", acts_as=[])
        self.assertTrue(p.IsHospitalStaff().has_permission(req, None))
        for cls in (p.IsDoctor, p.IsNurse, p.IsFrontDesk, p.IsLabTech, p.IsPharmacist, p.IsHospitalAdmin):
            self.assertFalse(cls().has_permission(req, None), cls.__name__)


class FeatureAndTierTests(SimpleTestCase):
    def test_require_feature_needs_the_subscription_flag(self):
        perm = p.RequireFeature("feat_lab")()
        self.assertTrue(perm.has_permission(request_for("doctor", subscription=SimpleNamespace(feat_lab=True)), None))
        self.assertFalse(perm.has_permission(request_for("doctor", subscription=SimpleNamespace(feat_lab=False)), None))
        self.assertFalse(perm.has_permission(request_for("doctor", subscription=None), None))   # patients / platform admins
        self.assertFalse(perm.has_permission(request_for("doctor", subscription=SimpleNamespace()), None))

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
