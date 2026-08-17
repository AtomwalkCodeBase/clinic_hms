from django.urls import path
from .views import (
    LabCatalogView, LabTestDetailView, LabRequestListCreateView, LabRequestLookupView,
    LabRequestChoiceView, LabRequestStatusView, LabReportUploadView, LabReportDeliverView,
)

urlpatterns = [
    path("catalog/",                  LabCatalogView.as_view(),            name="lab-catalog"),
    path("catalog/<int:pk>/",         LabTestDetailView.as_view(),         name="lab-catalog-detail"),
    path("requests/",                 LabRequestListCreateView.as_view(),  name="lab-request-list"),
    path("requests/lookup/",          LabRequestLookupView.as_view(),      name="lab-request-lookup"),
    path("requests/<int:pk>/choice/", LabRequestChoiceView.as_view(),      name="lab-request-choice"),
    path("requests/<int:pk>/status/", LabRequestStatusView.as_view(),      name="lab-request-status"),
    path("requests/<int:pk>/report/", LabReportUploadView.as_view(),       name="lab-request-report"),
    path("reports/<int:pk>/deliver/", LabReportDeliverView.as_view(),      name="lab-report-deliver"),
]
