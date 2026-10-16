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
    Liveness/readiness probe. Checks the atomwalk DB connection so a load
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
    path("django-admin/",        admin.site.urls),
    path("api/v1/auth/",         include("core.auth.urls")),
    path("api/v1/platform/",     include("apps.hospital_master.platform_urls")),
    path("api/v1/opd/",          include("apps.opd.urls")),
    path("api/v1/ipd/",          include("apps.ipd.urls")),  # Phase 1 — admission intake only
    path("api/v1/patients/",     include("apps.opd.patient_urls")),
    # portal/, emergency/, consult-pad/ and records-share/ (several of them deliberately public) are set up in apps/patients/urls.py;
    # records/, view-report/ (public) and the org/ schedule routes in apps/documents/urls.py
    path("api/v1/",              include("apps.patients.urls")),
    path("api/v1/",              include("apps.documents.urls")),
    # apps.clinical's Encounter/Vital/Diagnosis/FollowUp/ClinicalDocument were
    # retired (HMS-07c-1, confirmed dead — the live flow writes through
    # apps.opd, see apps/hie.py::sync_encounter_to_hie for the actual HIE write
    # path), so its URL route is gone too. apps.pharmacy stays routed
    # for its still-live Drug/DrugFormType catalog endpoints
    # (Prescription/PrescriptionItem were retired the same way).
    path("api/v1/prescriptions/",include("apps.pharmacy.drug_urls")),
    path("api/v1/lab/",          include("apps.lab.urls")),
    path("api/v1/billing/",      include("apps.billing.urls")),
    path("api/v1/pharmacy/",     include("apps.pharmacy.urls")),
    path("api/v1/org/",          include("apps.hospital_setup.urls")),
    # apps.tasks (Task/TaskAssignment) was retired (v7 table-count
    # redesign) — a complete, working API with zero frontend consumer
    # anywhere (confirmed by grep), so its URL route is gone too. See
    # apps/tasks/models.py for the full removal note.
    path("api/v1/compliance/",   include("apps.hospital_setup.compliance_urls")),
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
