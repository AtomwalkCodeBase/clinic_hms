from django.urls import path
from .views import (
    DrugSearchView, DrugCatalogView, DrugCatalogDetailView,
    DrugFormTypeListCreateView, DrugFormTypeDetailView,
    PrescriptionListCreateView, PrescriptionFinalizeView,
)

urlpatterns = [
    path("drugs/search/",        DrugSearchView.as_view(),            name="drug-search"),
    path("drugs/",                DrugCatalogView.as_view(),           name="drug-catalog"),
    path("drugs/<int:pk>/",       DrugCatalogDetailView.as_view(),     name="drug-catalog-detail"),
    path("drug-forms/",          DrugFormTypeListCreateView.as_view(), name="drug-form-list"),
    path("drug-forms/<int:pk>/", DrugFormTypeDetailView.as_view(),     name="drug-form-detail"),
    path("",                     PrescriptionListCreateView.as_view(), name="prescription-list"),
    path("<int:pk>/finalize/",   PrescriptionFinalizeView.as_view(),  name="prescription-finalize"),
]
