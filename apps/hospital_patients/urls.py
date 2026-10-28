from django.urls import path
from core.api.permissions import in_module
from apps.hospital_patients.views import (
    PatientRegisterView,
    PatientLookupView,
    PatientAttachNetworkView,
    PatientSearchView,
    PatientFamilyTreeView,
    PatientDetailView,
    PatientHistoryView,
    PatientDocumentDetailView,
    PatientLabResultDetailView,
)
from apps.documents.views import (
    PatientVaccinationListCreateView,
    PatientVaccinationVerifyView,
    PatientVaccinationOrderView,
    PatientVaccinationDeclineView,
    PatientVaccinationAdministerView,
)
from apps.documents.views import BirthHistoryView

urlpatterns = [
    path("register/",          in_module(PatientRegisterView, "patients").as_view(),       name="patient-register"),
    path("lookup/",            in_module(PatientLookupView, "patients").as_view(),          name="patient-lookup"),
    path("attach-network/",    in_module(PatientAttachNetworkView, "patients").as_view(),   name="patient-attach-network"),
    path("search/",            in_module(PatientSearchView, "patients").as_view(),          name="patient-search"),
    path("family-tree/",       in_module(PatientFamilyTreeView, "patients").as_view(),      name="patient-family-tree"),
    path("documents/<int:doc_id>/", in_module(PatientDocumentDetailView, "patients").as_view(), name="patient-document-detail"),
    path("lab-results/<int:result_id>/", in_module(PatientLabResultDetailView, "patients").as_view(), name="patient-lab-result-detail"),
    path("vaccinations/<int:pk>/verify/", in_module(PatientVaccinationVerifyView, "patients").as_view(), name="patient-vaccination-verify"),
    path("<int:pk>/",          in_module(PatientDetailView, "patients").as_view(),          name="patient-detail"),
    path("<int:pk>/history/",  in_module(PatientHistoryView, "patients").as_view(),         name="patient-history"),
    path("<int:pk>/vaccinations/", in_module(PatientVaccinationListCreateView, "patients").as_view(), name="patient-vaccinations"),
    path("<int:pk>/vaccinations/order/",      in_module(PatientVaccinationOrderView, "patients").as_view(),      name="patient-vaccination-order"),
    path("<int:pk>/vaccinations/decline/",    in_module(PatientVaccinationDeclineView, "patients").as_view(),    name="patient-vaccination-decline"),
    path("<int:pk>/vaccinations/administer/", in_module(PatientVaccinationAdministerView, "patients").as_view(), name="patient-vaccination-administer"),
    # ── Pediatric-only additions ────────────────────────────────────────
    path("<int:pk>/birth-history/", in_module(BirthHistoryView, "patients").as_view(),              name="patient-birth-history"),
]
