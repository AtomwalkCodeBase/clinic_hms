"""A portal account is a login on the person's one patient row."""
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIRequestFactory

from apps.hospital_patients.portal_views import PortalRegisterView
from django.core.exceptions import FieldDoesNotExist

from apps.auth_app.otp_views import OTPRequestView
from apps.auth_app.views import PatientLoginView
from apps.hospital_patients.portal_views import PortalProfileView
from apps.atomwalk.models import OTPCode, PatientAccount, Patient
from core.authentication import MockUser
from rest_framework.test import force_authenticate
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
        self.assertEqual(Patient.objects.count(), 1)
        account = PatientAccount.objects.get()
        self.assertEqual((account.mobile_hash, account.email), (hash_mobile(normalize_mobile("9876543210")), "asha@example.com"))
        self.assertTrue(account.check_password("Str0ng!pass"))

    def test_a_walk_in_who_later_signs_up_keeps_the_awpid_they_already_have(self):
        walk_in = Patient.objects.create(
            awpid="AW-WALKIN", full_name="Asha Rao", mobile_hash=hash_mobile(normalize_mobile("9876543210")))
        self.assertEqual(PatientAccount.objects.count(), 0)          # registered at a front desk: no login yet
        self.assertEqual(self.register().status_code, 200)
        self.assertEqual(Patient.objects.count(), 1)
        self.assertEqual(PatientAccount.objects.get().awpid, walk_in.awpid)

    def test_signing_up_twice_with_the_same_mobile_is_refused(self):
        self.register()
        self.assertEqual(self.register().status_code, 400)
        self.assertEqual(Patient.objects.count(), 1)


class MobileIsOnlyStoredScrambledTests(TestCase):
    """The mobile number exists once, scrambled: hospitals match on it and the patient logs in with it."""
    databases = {"default"}

    def setUp(self):
        self.acct = PatientAccount.objects.using("default").create(
            awpid="AWPID-LOGIN1", full_name="Asha", mobile="9876543210", email="asha@example.com", password="x")
        self.acct.set_password("Str0ng!pass")
        self.acct.save(using="default")

    def post(self, view, data):
        return view.as_view()(APIRequestFactory().post("/x/", data, format="json"))

    def test_there_is_no_plain_mobile_column(self):
        with self.assertRaises(FieldDoesNotExist):
            Patient._meta.get_field("mobile")
        self.assertEqual(self.acct.mobile_hash, hash_mobile(normalize_mobile("9876543210")))

    def test_a_patient_logs_in_with_the_number_however_they_type_it(self):
        for typed in ("9876543210", "+91 98765 43210", "98765-43210"):
            resp = self.post(PatientLoginView, {"mobile": typed, "password": "Str0ng!pass"})
            self.assertEqual(resp.status_code, 200, typed)
        self.assertEqual(self.post(PatientLoginView, {"mobile": "9876543210", "password": "wrong"}).status_code, 400)
        self.assertEqual(self.post(PatientLoginView, {"mobile": "9000000000", "password": "Str0ng!pass"}).status_code, 400)
        for junk in ("abc", "12", "not a number"):                     # something that isn't a phone number is just a failed login
            self.assertEqual(self.post(PatientLoginView, {"mobile": junk, "password": "x"}).status_code, 400, junk)

    def test_a_walk_in_with_the_same_number_but_no_password_cannot_log_in(self):
        Patient.objects.using("default").create(awpid="AW-WALK", full_name="Walk In", mobile_hash=hash_mobile(normalize_mobile("9111111111")))
        self.assertEqual(self.post(PatientLoginView, {"mobile": "9111111111", "password": ""}).status_code, 400)

    def test_the_profile_says_a_number_is_on_file_without_showing_it(self):
        request = APIRequestFactory().get("/x/")
        force_authenticate(request, user=MockUser({"user_id": self.acct.id, "role": "patient", "awpid": "AWPID-LOGIN1"}))
        data = PortalProfileView.as_view()(request).data["data"]
        self.assertEqual((data["mobile"], data["mobile_on_file"]), ("", True))

    def test_a_code_for_someone_who_typed_their_awpid_goes_to_their_email(self):
        with mock.patch("apps.auth_app.otp_views._send_code", return_value=True) as send:
            resp = self.post(OTPRequestView, {"purpose": OTPCode.PURPOSE_LOGIN_PATIENT, "identifier": "AWPID-LOGIN1"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(send.call_args.args[0], "asha@example.com")
        self.assertEqual(send.call_args.args[1], "email")

    def test_an_account_with_no_email_is_asked_to_use_its_mobile_instead(self):
        PatientAccount.objects.using("default").filter(pk=self.acct.pk).update(email="")
        with mock.patch("apps.auth_app.otp_views._send_code", return_value=True) as send:
            resp = self.post(OTPRequestView, {"purpose": OTPCode.PURPOSE_LOGIN_PATIENT, "identifier": "AWPID-LOGIN1"})
        self.assertEqual(resp.status_code, 400)
        send.assert_not_called()
