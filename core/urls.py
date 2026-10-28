"""core/urls.py"""

from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from django.db import connections
from django.db.utils import OperationalError


def health(request):
    """Liveness/readiness probe. Checks the atomwalk DB connection so a load"""
    db_ok = True
    try:
        connections["default"].cursor()
    except OperationalError:
        db_ok = False
    status_code = 200 if db_ok else 503
    return JsonResponse(
        {"status": "ok" if db_ok else "degraded", "service": "atomwalk-hms", "database": db_ok},
        status=status_code,
    )


urlpatterns = [
    path("health/",              health),
    path("django-admin/",        admin.site.urls),
    path("api/v1/auth/",         include("core.auth.urls")),
    path("api/v1/platform/",     include("apps.hospital_master.platform_urls")),
    path("api/v1/opd/",          include("apps.opd.urls")),
    path("api/v1/patients/",     include("apps.hospital_patients.urls")),
    # portal/, emergency/, consult-pad/ and records-share/ (several of them deliberately public) are set up in apps/patients/urls.py;
    path("api/v1/",              include("apps.patients.urls")),
    path("api/v1/",              include("apps.documents.urls")),
    # apps.clinical's Encounter/Vital/Diagnosis/FollowUp/ClinicalDocument were
    path("api/v1/billing/",      include("apps.billing.urls")),
    path("api/v1/org/",          include("apps.hospital_setup.urls")),
    # apps.tasks (Task/TaskAssignment) was retired (v7 table-count
    path("api/v1/compliance/",   include("apps.hospital_setup.compliance_urls")),
]

# ── API docs (drf-spectacular) ──────────────────────────────────────────────
try:
    from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
    urlpatterns += [
        path("api/schema/",      SpectacularAPIView.as_view(), name="schema"),
        path("api/docs/",        SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    ]
except ImportError:
    pass
