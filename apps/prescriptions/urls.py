from django.urls import path
from .views import (
    DrugSearchView, DrugCatalogView, DrugCatalogDetailView,
    PrescriptionListCreateView, PrescriptionFinalizeView,
)

urlpatterns = [
    path("drugs/search/",        DrugSearchView.as_view(),            name="drug-search"),
    path("drugs/",                DrugCatalogView.as_view(),           name="drug-catalog"),
    path("drugs/<int:pk>/",       DrugCatalogDetailView.as_view(),     name="drug-catalog-detail"),
    path("",                     PrescriptionListCreateView.as_view(), name="prescription-list"),
    path("<int:pk>/finalize/",   PrescriptionFinalizeView.as_view(),  name="prescription-finalize"),
]
