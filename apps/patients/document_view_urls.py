from django.urls import path
from .document_view_views import DocumentViewView

urlpatterns = [
    path("<str:token>/", DocumentViewView.as_view(), name="document-view"),
]
