"""
atomwalk/urls.py
----------------
Root URL configuration for Atomwalk HMS.
All API routes are versioned under /api/v1/.
"""

from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from django.db import connections
from django.db.utils import OperationalError


def health(request):
    """
    Liveness/readiness probe. Checks the registry DB connection so a load
    balancer can tell "process is up" apart from "process can actually serve
    requests" — a common gap in bare 200-OK health checks.
    """
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
    path("admin/",               admin.site.urls),
    path("api/v1/auth/",         include("apps.auth_app.urls")),
    path("api/v1/platform/",     include("apps.platform_admin.urls")),
    path("api/v1/opd/",          include("apps.opd.urls")),
    path("api/v1/patients/",     include("apps.patients.urls")),
    path("api/v1/portal/",       include("apps.patients.portal_urls")),
    # apps.clinical / apps.prescriptions stay routed — apps.billing/lab/pharmacy
    # hold live foreign keys into their models, even though the OPD flow itself
    # writes through apps.opd. See apps/opd/views.py::_sync_to_hie for the
    # actual HIE write path.
    path("api/v1/clinical/",     include("apps.clinical.urls")),
    path("api/v1/prescriptions/",include("apps.prescriptions.urls")),
    path("api/v1/lab/",          include("apps.lab.urls")),
    path("api/v1/billing/",      include("apps.billing.urls")),
    path("api/v1/pharmacy/",     include("apps.pharmacy.urls")),
    path("api/v1/org/",          include("apps.org.urls")),
    path("api/v1/tasks/",        include("apps.tasks.urls")),
]

# ── API docs (drf-spectacular) ──────────────────────────────────────────────
# Installed since the start of this project but never wired up until now.
try:
    from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
    urlpatterns += [
        path("api/schema/",      SpectacularAPIView.as_view(), name="schema"),
        path("api/docs/",        SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    ]
except ImportError:
    pass
