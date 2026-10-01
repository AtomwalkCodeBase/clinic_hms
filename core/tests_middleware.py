"""
core/tests_middleware.py
------------------------
Which paths JWTTenantMiddleware lets through without a Bearer token.
"""

from django.conf import settings
from django.test import TestCase, override_settings


PLAIN_STATIC = {"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}


class ExemptPathTests(TestCase):
    # The manifest storage used by the real settings needs `collectstatic`; irrelevant to this check.
    @override_settings(STORAGES=PLAIN_STATIC)
    def test_django_admin_login_is_reachable_without_a_token(self):
        """Regression: the exemption said /admin/ but admin is mounted at /django-admin/ (401 JSON)."""
        resp = self.client.get("/django-admin/login/")
        self.assertEqual(resp.status_code, 200)

    def test_tenant_api_still_requires_a_token(self):
        resp = self.client.get("/api/v1/org/branches/")
        self.assertEqual(resp.status_code, 401)

    def test_a_similar_prefix_is_not_exempt(self):
        self.assertEqual(self.client.get("/django-admin-evil/").status_code, 401)

    @override_settings(DEBUG=False)
    def test_docs_and_schema_stay_behind_the_token_in_production(self):
        for path in ("/api/docs/", "/api/schema/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)

    @override_settings(DEBUG=True)
    def test_docs_and_schema_are_reachable_in_debug(self):
        for path in ("/api/docs/", "/api/schema/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)


class TenantResolutionTests(TestCase):
    """JWTTenantMiddleware: which DB alias a token's db_name claim may select."""

    def setUp(self):
        from django.http import HttpResponse
        from core.db_router import get_tenant_db, set_tenant_db
        from core.middleware import JWTTenantMiddleware

        self.seen = []

        def view(request):
            self.seen.append(get_tenant_db())
            return HttpResponse("ok")

        self.middleware = JWTTenantMiddleware(view)
        self.addCleanup(set_tenant_db, None)
        from core.logging_context import reset_request_identity
        self.addCleanup(reset_request_identity)
        self.addCleanup(settings.DATABASES.pop, "aw_tenant_mw", None)

    def call(self, **claims):
        import time
        import jwt
        from django.test import RequestFactory

        payload = {"user_id": 1, "role": "doctor", "token_type": "access", "exp": int(time.time()) + 300, **claims}
        token = jwt.encode(payload, settings.JWT_SIGNING_KEY, algorithm="HS256")
        return self.middleware(RequestFactory().get("/api/v1/opd/stats/", HTTP_AUTHORIZATION=f"Bearer {token}"))

    def test_a_staff_token_without_a_tenant_is_rejected(self):
        self.assertEqual(self.call().status_code, 401)

    def test_an_unknown_db_name_is_rejected_and_not_registered(self):
        resp = self.call(db_name="aw_tenant_mw")
        self.assertEqual(resp.status_code, 401)
        self.assertNotIn("aw_tenant_mw", settings.DATABASES)

    def test_an_active_tenants_alias_is_registered_and_selected(self):
        from apps.tenants.models import Tenant
        Tenant.objects.using("default").create(name="MW", subdomain="mw", db_name="aw_tenant_mw")
        resp = self.call(db_name="aw_tenant_mw")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("aw_tenant_mw", settings.DATABASES)
        self.assertEqual(self.seen, ["aw_tenant_mw"])

    def test_an_inactive_tenant_is_rejected(self):
        from apps.tenants.models import Tenant
        Tenant.objects.using("default").create(name="MW", subdomain="mw", db_name="aw_tenant_mw", is_active=False)
        self.assertEqual(self.call(db_name="aw_tenant_mw").status_code, 401)

    def test_platform_and_patient_tokens_never_select_a_tenant_alias(self):
        for claims in ({"is_platform": True, "role": "platform_admin"}, {"role": "patient"}):
            with self.subTest(claims=claims):
                self.seen.clear()
                self.assertEqual(self.call(**claims).status_code, 200)
                self.assertEqual(self.seen, ["default"])

    def test_the_alias_does_not_leak_into_the_next_request(self):
        from apps.tenants.models import Tenant
        Tenant.objects.using("default").create(name="MW", subdomain="mw", db_name="aw_tenant_mw")
        self.call(db_name="aw_tenant_mw")
        self.seen.clear()
        self.middleware(__import__("django.test", fromlist=["RequestFactory"]).RequestFactory().get("/health/"))
        self.assertEqual(self.seen, ["default"])
