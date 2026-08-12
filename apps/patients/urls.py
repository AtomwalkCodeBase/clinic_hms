from django.urls import path
from .views import (
    PatientRegisterView,
    PatientLookupView,
    PatientSearchView,
    PatientDetailView,
    PatientHistoryView,
    PatientAllergyListCreateView,
    PatientDocumentDetailView,
    PatientLabResultDetailView,
)
from .growth_vaccination_views import (
    PatientGrowthView,
    PatientVaccinationListCreateView,
    PatientVaccinationVerifyView,
    PatientVaccinationOrderView,
    PatientVaccinationDeclineView,
    PatientVaccinationAdministerView,
)

urlpatterns = [
    path("register/",          PatientRegisterView.as_view(),       name="patient-register"),
    path("lookup/",            PatientLookupView.as_view(),          name="patient-lookup"),
    path("search/",            PatientSearchView.as_view(),          name="patient-search"),
    path("documents/<int:doc_id>/", PatientDocumentDetailView.as_view(), name="patient-document-detail"),
    path("lab-results/<int:result_id>/", PatientLabResultDetailView.as_view(), name="patient-lab-result-detail"),
    path("vaccinations/<int:pk>/verify/", PatientVaccinationVerifyView.as_view(), name="patient-vaccination-verify"),
    path("<int:pk>/",          PatientDetailView.as_view(),          name="patient-detail"),
    path("<int:pk>/history/",  PatientHistoryView.as_view(),         name="patient-history"),
    path("<int:pk>/allergies/",PatientAllergyListCreateView.as_view(),name="patient-allergies"),
    path("<int:pk>/growth/",   PatientGrowthView.as_view(),          name="patient-growth"),
    path("<int:pk>/vaccinations/", PatientVaccinationListCreateView.as_view(), name="patient-vaccinations"),
    path("<int:pk>/vaccinations/order/",      PatientVaccinationOrderView.as_view(),      name="patient-vaccination-order"),
    path("<int:pk>/vaccinations/decline/",    PatientVaccinationDeclineView.as_view(),    name="patient-vaccination-decline"),
    path("<int:pk>/vaccinations/administer/", PatientVaccinationAdministerView.as_view(), name="patient-vaccination-administer"),
]
