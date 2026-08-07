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

urlpatterns = [
    path("register/",          PatientRegisterView.as_view(),       name="patient-register"),
    path("lookup/",            PatientLookupView.as_view(),          name="patient-lookup"),
    path("search/",            PatientSearchView.as_view(),          name="patient-search"),
    path("documents/<int:doc_id>/", PatientDocumentDetailView.as_view(), name="patient-document-detail"),
    path("lab-results/<int:result_id>/", PatientLabResultDetailView.as_view(), name="patient-lab-result-detail"),
    path("<int:pk>/",          PatientDetailView.as_view(),          name="patient-detail"),
    path("<int:pk>/history/",  PatientHistoryView.as_view(),         name="patient-history"),
    path("<int:pk>/allergies/",PatientAllergyListCreateView.as_view(),name="patient-allergies"),
]
