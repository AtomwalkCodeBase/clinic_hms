"""A portal account is a login on the person's one patient_identity row."""
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIRequestFactory

from apps.patients.portal_views import PortalRegisterView
from apps.registry.models import PatientAccount, PatientIdentity
from core.utils.hashing import hash_mobile, normalize_mobile

BODY = {"action_token": "t", "full_name": "Asha Rao", "mobile": "9876543210", "password": "Str0ng!pass"}


class PortalAccountTests(TestCase):
    databases = {"default"}

    def register(self):
        request = APIRequestFactory().post("/api/v1/portal/register/", BODY, format="json")
        with mock.patch("core.otp.decode_action_token", return_value={"identifier": "asha@example.com"}), \
                mock.patch("core.realworld_validation.validate_mobile_real", return_value=(True, "")):
            return PortalRegisterView.as_view()(request)

    def test_signing_up_creates_one_row_that_is_both_the_identity_and_the_login(self):
        self.assertEqual(self.register().status_code, 200)
        self.assertEqual(PatientIdentity.objects.count(), 1)
        account = PatientAccount.objects.get()
        self.assertEqual((account.mobile, account.email), ("9876543210", "asha@example.com"))
        self.assertTrue(account.check_password("Str0ng!pass"))

    def test_a_walk_in_who_later_signs_up_keeps_the_awpid_they_already_have(self):
        walk_in = PatientIdentity.objects.create(
            awpid="AW-WALKIN", full_name="Asha Rao", mobile_hash=hash_mobile(normalize_mobile("9876543210")))
        self.assertEqual(PatientAccount.objects.count(), 0)          # registered at a front desk: no login yet
        self.assertEqual(self.register().status_code, 200)
        self.assertEqual(PatientIdentity.objects.count(), 1)
        self.assertEqual(PatientAccount.objects.get().awpid, walk_in.awpid)

    def test_signing_up_twice_with_the_same_mobile_is_refused(self):
        self.register()
        self.assertEqual(self.register().status_code, 400)
        self.assertEqual(PatientIdentity.objects.count(), 1)
