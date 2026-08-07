from django.urls import path
from .views import (
    EncounterListCreateView, EncounterDetailView, EncounterCloseView,
    VitalListCreateView, DiagnosisListCreateView,
)

urlpatterns = [
    path("encounters/",              EncounterListCreateView.as_view(), name="encounter-list"),
    path("encounters/<int:pk>/",     EncounterDetailView.as_view(),     name="encounter-detail"),
    path("encounters/<int:pk>/close/",EncounterCloseView.as_view(),    name="encounter-close"),
    path("vitals/",                  VitalListCreateView.as_view(),     name="vital-list"),
    path("diagnoses/",               DiagnosisListCreateView.as_view(), name="diagnosis-list"),
]
