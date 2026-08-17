from django.urls import path
from .views import (
    DrugSearchView, DrugCatalogView, DrugCatalogDetailView,
    DrugFormTypeListCreateView, DrugFormTypeDetailView,
)

# Prescription list/create/finalize routes were removed along with the dead
# Prescription/PrescriptionItem models (HMS-07c-1) — prescriptions live in
# apps.opd now (see apps/opd/urls.py).
urlpatterns = [
    path("drugs/search/",        DrugSearchView.as_view(),            name="drug-search"),
    path("drugs/",                DrugCatalogView.as_view(),           name="drug-catalog"),
    path("drugs/<int:pk>/",       DrugCatalogDetailView.as_view(),     name="drug-catalog-detail"),
    path("drug-forms/",          DrugFormTypeListCreateView.as_view(), name="drug-form-list"),
    path("drug-forms/<int:pk>/", DrugFormTypeDetailView.as_view(),     name="drug-form-detail"),
]
