"""Document, report-view and schedule routes, all under /api/v1/."""
from django.urls import include, path
from apps.atomwalk.documents.views import (
    BatchDetailView,
    StaffTimelineView,
    SubmitView,
    TimelineView,
    TypesView,
    UploadView,
)
from apps.atomwalk.documents.views import DocumentViewView
from apps.atomwalk.documents.views import (
    MilestoneScheduleActivateView,
    MilestoneScheduleDetailView,
    MilestoneScheduleListCreateView,
    VaccinationScheduleActivateView,
    VaccinationScheduleDetailView,
    VaccinationScheduleListCreateView,
)


records_urlpatterns = [
    path("types/", TypesView.as_view(), name="records-types"),
    path("upload/", UploadView.as_view(), name="records-upload"),
    path("batches/<int:batch_id>/", BatchDetailView.as_view(), name="records-batch"),
    path("submit/", SubmitView.as_view(), name="records-submit"),
    path("timeline/", TimelineView.as_view(), name="records-timeline"),
    path("patients/<int:pk>/timeline/", StaffTimelineView.as_view(), name="records-staff-timeline"),
]


view_report_urlpatterns = [
    path("<str:token>/", DocumentViewView.as_view(), name="document-view"),
]


schedule_urlpatterns = [
    path("vaccination-schedules/",             VaccinationScheduleListCreateView.as_view(), name="vaccination-schedule-list-create"),
    path("vaccination-schedules/<int:pk>/",    VaccinationScheduleDetailView.as_view(),     name="vaccination-schedule-detail"),
    path("vaccination-schedules/<int:pk>/activate/", VaccinationScheduleActivateView.as_view(), name="vaccination-schedule-activate"),
    path("milestone-schedules/",             MilestoneScheduleListCreateView.as_view(), name="milestone-schedule-list-create"),
    path("milestone-schedules/<int:pk>/",    MilestoneScheduleDetailView.as_view(),     name="milestone-schedule-detail"),
    path("milestone-schedules/<int:pk>/activate/", MilestoneScheduleActivateView.as_view(), name="milestone-schedule-activate"),
]


urlpatterns = [
    path("records/", include(records_urlpatterns)),
    path("view-report/", include(view_report_urlpatterns)),
    path("org/", include(schedule_urlpatterns)),
]
