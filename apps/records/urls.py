from django.urls import path

from .views import BatchDetailView, StaffTimelineView, SubmitView, TimelineView, TypesView, UploadView

urlpatterns = [
    path("types/", TypesView.as_view(), name="records-types"),
    path("upload/", UploadView.as_view(), name="records-upload"),
    path("batches/<int:batch_id>/", BatchDetailView.as_view(), name="records-batch"),
    path("submit/", SubmitView.as_view(), name="records-submit"),
    path("timeline/", TimelineView.as_view(), name="records-timeline"),
    path("patients/<int:pk>/timeline/", StaffTimelineView.as_view(), name="records-staff-timeline"),
]
