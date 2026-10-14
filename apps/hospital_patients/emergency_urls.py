from django.urls import path
from .emergency_views import EmergencySummaryView

urlpatterns = [
    path("<str:token>/", EmergencySummaryView.as_view(), name="emergency-summary"),
]
