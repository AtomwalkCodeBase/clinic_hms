from django.urls import path
from .views import (
    AppointmentListCreateView, AppointmentDetailView, AppointmentStatusView, VitalsView, OPDStatsView,
    AppointmentHistoryView,
    TranscribeView, MonitoringListView,
    EncounterCreateView, EncounterDetailView, EncounterSignView,
    PrescriptionCreateView, PrescriptionDetailView, PrescriptionItemView,
    FavouriteListCreateView, FavouriteDeleteView,
)

urlpatterns = [
    # Stats
    path("stats/", OPDStatsView.as_view(), name="opd-stats"),

    # Voice dictation (Whisper)
    path("transcribe/", TranscribeView.as_view(), name="opd-transcribe"),

    # Nurse patient-monitoring list
    path("monitoring/", MonitoringListView.as_view(), name="opd-monitoring"),

    # Visit history — searchable, not date-limited to today
    path("history/", AppointmentHistoryView.as_view(), name="appointment-history"),

    # Appointments / Queue
    path("appointments/", AppointmentListCreateView.as_view(), name="appointment-list-create"),
    path("appointments/<uuid:pk>/", AppointmentDetailView.as_view(), name="appointment-detail"),
    path("appointments/<uuid:pk>/status/", AppointmentStatusView.as_view(), name="appointment-status"),
    path("appointments/<uuid:pk>/vitals/", VitalsView.as_view(), name="vitals"),

    # Encounters
    path("encounters/", EncounterCreateView.as_view(), name="encounter-create"),
    path("encounters/<uuid:pk>/", EncounterDetailView.as_view(), name="encounter-detail"),
    path("encounters/<uuid:pk>/sign/", EncounterSignView.as_view(), name="encounter-sign"),

    # Prescriptions
    path("prescriptions/", PrescriptionCreateView.as_view(), name="prescription-create"),
    path("prescriptions/<uuid:pk>/", PrescriptionDetailView.as_view(), name="prescription-detail"),
    path("prescriptions/<uuid:pk>/items/", PrescriptionItemView.as_view(), name="prescription-items"),
    path("prescriptions/<uuid:pk>/items/<uuid:item_id>/", PrescriptionItemView.as_view(), name="prescription-item-delete"),

    # Favourites
    path("favourites/", FavouriteListCreateView.as_view(), name="favourites"),
    path("favourites/<uuid:pk>/", FavouriteDeleteView.as_view(), name="favourite-delete"),
]
