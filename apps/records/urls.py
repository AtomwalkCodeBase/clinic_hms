from django.urls import path

from .views import BatchDetailView, UploadView

urlpatterns = [
    path("upload/", UploadView.as_view(), name="records-upload"),
    path("batches/<int:batch_id>/", BatchDetailView.as_view(), name="records-batch"),
]
