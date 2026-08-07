from django.urls import path
from .views import DrugSearchView, PrescriptionListCreateView, PrescriptionFinalizeView

urlpatterns = [
    path("drugs/search/",        DrugSearchView.as_view(),            name="drug-search"),
    path("",                     PrescriptionListCreateView.as_view(), name="prescription-list"),
    path("<int:pk>/finalize/",   PrescriptionFinalizeView.as_view(),  name="prescription-finalize"),
]
