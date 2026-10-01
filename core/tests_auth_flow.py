"""
core/tests_auth_flow.py
-----------------------
JWTTenantAuthentication end to end against real rows: what makes a token unusable (expiry, wrong type,
revocation, hospital suspended/read-only, staff deactivated, patient session stale) and what logout does.
Needs the tenant_test alias:  python manage.py test core.tests_auth_flow --settings=atomwalk.settings.test
"""

import time

import jwt
from django.conf import settings
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.auth_app.views import LogoutView, TokenRefreshView, _make_tokens
from apps.org.models import Branch, StaffUser
from apps.registry.models import BlacklistedToken, PatientAccount
from apps.tenants.models import Subscription, Tenant
from core.authentication import JWTTenantAuthentication
from core.testing import TenantDBTestCase, requires_tenant_db

FAR_FUTURE = "2099-01-01T00:00:00Z"


@requires_tenant_db
class AuthenticationTests(TenantDBTestCase):
    def setUp(self):
        super().setUp()
        db = self.tenant_alias
        self.tenant = Tenant.objects.using("default").create(name="Auth H", subdomain="auth-h", db_name=db)
        self.sub = Subscription.objects.using("default").create(
            tenant=self.tenant, license_tier="starter", status="active",
        )
        branch = Branch.objects.using(db).create(name="Main")
        self.staff = StaffUser.objects.using(db).create(
            email="a@x.test", role="doctor", phone="9000000030", branch=branch,
        )
        self.staff_payload = {
            "user_id": self.staff.id, "role": "doctor", "tenant_id": self.tenant.id,
            "db_name": db, "email": "a@x.test",
        }

    def authenticate(self, token, method="get"):
        request = getattr(APIRequestFactory(), method)("/x/", HTTP_AUTHORIZATION=f"Bearer {token}")
        return JWTTenantAuthentication().authenticate(request)

    def access(self, **payload):
        return _make_tokens({**self.staff_payload, **payload})["access"]

    # ── accepted ─────────────────────────────────────────────────────────────
    def test_no_header_is_anonymous(self):
        request = APIRequestFactory().get("/x/")
        self.assertIsNone(JWTTenantAuthentication().authenticate(request))

    def test_a_valid_staff_token_yields_a_user_with_the_subscription(self):
        user, _ = self.authenticate(self.access())
        self.assertEqual((user.id, user.role, user.tenant_id), (self.staff.id, "doctor", self.tenant.id))
        self.assertEqual(user.subscription.pk, self.sub.pk)

    # ── rejected token ───────────────────────────────────────────────────────
    def test_expired_token(self):
        token = jwt.encode(
            {**self.staff_payload, "token_type": "access", "exp": int(time.time()) - 10},
            settings.JWT_SIGNING_KEY, algorithm="HS256",
        )
        with self.assertRaisesMessage(AuthenticationFailed, "expired"):
            self.authenticate(token)

    def test_a_token_signed_with_another_key(self):
        token = jwt.encode(
            {**self.staff_payload, "token_type": "access", "exp": int(time.time()) + 60},
            "some-other-key", algorithm="HS256",
        )
        with self.assertRaises(AuthenticationFailed):
            self.authenticate(token)

    def test_a_refresh_token_cannot_be_used_as_an_access_token(self):
        refresh = _make_tokens(self.staff_payload)["refresh"]
        with self.assertRaisesMessage(AuthenticationFailed, "access token"):
            self.authenticate(refresh)

    def test_a_revoked_token(self):
        token = self.access()
        jti = jwt.decode(token, settings.JWT_SIGNING_KEY, algorithms=["HS256"])["jti"]
        BlacklistedToken.objects.using("default").create(jti=jti, expires_at=FAR_FUTURE)
        with self.assertRaisesMessage(AuthenticationFailed, "revoked"):
            self.authenticate(token)

    def test_logout_revokes_the_access_token_it_was_called_with(self):
        token = self.access()
        request = APIRequestFactory().post(
            "/api/v1/auth/logout/", {}, format="json", HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        user, _ = self.authenticate(token)
        force_authenticate(request, user=user)
        self.assertEqual(LogoutView.as_view()(request).status_code, 200)
        with self.assertRaisesMessage(AuthenticationFailed, "revoked"):
            self.authenticate(token)

    # ── hospital subscription ────────────────────────────────────────────────
    def test_a_frozen_or_suspended_hospital_is_locked_out(self):
        for status in ("frozen", "suspended"):
            with self.subTest(status=status):
                Subscription.objects.using("default").filter(pk=self.sub.pk).update(status=status)
                with self.assertRaisesMessage(PermissionDenied, "account is"):
                    self.authenticate(self.access())

    def test_a_read_only_hospital_can_read_but_not_write(self):
        Subscription.objects.using("default").filter(pk=self.sub.pk).update(status="read_only")
        self.assertIsNotNone(self.authenticate(self.access(), method="get"))
        for method in ("post", "patch", "delete"):
            with self.subTest(method=method), self.assertRaisesMessage(PermissionDenied, "read-only"):
                self.authenticate(self.access(), method=method)

    # ── staff status ─────────────────────────────────────────────────────────
    def test_a_deactivated_staff_member_is_cut_off_immediately(self):
        token = self.access()
        self.authenticate(token)                                   # fine today
        StaffUser.objects.using(self.tenant_alias).filter(pk=self.staff.pk).update(is_active=False)
        with self.assertRaisesMessage(PermissionDenied, "deactivated"):
            self.authenticate(token)                               # the same, still-unexpired token

    # ── patients ─────────────────────────────────────────────────────────────
    def make_patient(self, awpid="AW-AUTH-1"):
        return PatientAccount.objects.using("default").create(
            awpid=awpid, full_name="P", mobile="9111111111", password="x",
        )

    def test_a_patient_token_matching_the_account_is_accepted(self):
        acct = self.make_patient()
        token = _make_tokens({"user_id": acct.id, "role": "patient", "awpid": acct.awpid})["access"]
        user, _ = self.authenticate(token)
        self.assertEqual((user.role, user.awpid), ("patient", "AW-AUTH-1"))

    def test_a_patient_token_whose_account_id_now_belongs_to_someone_else_is_rejected(self):
        """Registry wiped and re-seeded: an old token's user_id must not silently become another patient."""
        acct = self.make_patient(awpid="AW-NEW")
        token = _make_tokens({"user_id": acct.id, "role": "patient", "awpid": "AW-OLD"})["access"]
        with self.assertRaisesMessage(AuthenticationFailed, "no longer valid"):
            self.authenticate(token)

    def test_a_deactivated_patient_account_is_rejected(self):
        acct = self.make_patient()
        PatientAccount.objects.using("default").filter(pk=acct.pk).update(is_active=False)
        token = _make_tokens({"user_id": acct.id, "role": "patient", "awpid": acct.awpid})["access"]
        with self.assertRaises(AuthenticationFailed):
            self.authenticate(token)


@requires_tenant_db
class RefreshTests(TenantDBTestCase):
    """Documents today's refresh behaviour (a design decision is pending, see REVIEW_NOTES.md)."""

    def refresh(self, refresh_token):
        request = APIRequestFactory().post(
            "/api/v1/auth/token/refresh/", {"refresh": refresh_token}, format="json",
        )
        return TokenRefreshView.as_view()(request)

    def test_refresh_issues_a_new_pair_with_the_same_claims(self):
        pair = _make_tokens({"user_id": 7, "role": "doctor", "db_name": "x", "acts_as": []})
        resp = self.refresh(pair["refresh"])
        self.assertEqual(resp.status_code, 200)
        new = jwt.decode(resp.data["data"]["access"], settings.JWT_SIGNING_KEY, algorithms=["HS256"])
        self.assertEqual((new["user_id"], new["role"], new["token_type"]), (7, "doctor", "access"))

    def test_an_access_token_is_not_accepted_for_refresh(self):
        self.assertEqual(self.refresh(_make_tokens({"user_id": 7})["access"]).status_code, 401)

    def test_a_revoked_refresh_token_is_refused(self):
        pair = _make_tokens({"user_id": 7})
        jti = jwt.decode(pair["refresh"], settings.JWT_SIGNING_KEY, algorithms=["HS256"])["jti"]
        BlacklistedToken.objects.using("default").create(jti=jti, expires_at=FAR_FUTURE)
        self.assertEqual(self.refresh(pair["refresh"]).status_code, 401)
