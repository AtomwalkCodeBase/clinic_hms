from django.urls import path
from core.api.permissions import in_module
from apps.opd.views import (
    AppointmentListCreateView,
    AppointmentDetailView,
    AppointmentStatusView,
    AppointmentRescheduleView,
    VitalsView,
    OPDStatsView,
    AppointmentHistoryView,
    AppointmentUpcomingView,
    TranscribeView,
    MonitoringListView,
    EncounterCreateView,
    EncounterDetailView,
    EncounterSignView,
    EncounterSummaryPDFView,
    FollowUpActionView,
    PreviousEncounterView,
    FollowupNurseWorklistView,
    FollowupMarkBookedView,
    EncounterConsultSessionView,
    EncounterInternalNoteView,
    PrescriptionCreateView,
    PrescriptionDetailView,
    PrescriptionItemView,
    FavouriteListCreateView,
    FavouriteDeleteView,
    AppointmentTypeListCreateView,
    AppointmentTypeDetailView,
)

urlpatterns = [
    # Stats
    path("stats/", in_module(OPDStatsView, "opd", "reports").as_view(), name="opd-stats"),

    # Hospital-admin-configurable catalog ("make it configurable")
    path("appointment-types/", in_module(AppointmentTypeListCreateView, "opd").as_view(), name="appointment-type-list"),
    path("appointment-types/<int:pk>/", in_module(AppointmentTypeDetailView, "opd").as_view(), name="appointment-type-detail"),

    # Voice dictation (Whisper)
    path("transcribe/", in_module(TranscribeView, "opd").as_view(), name="opd-transcribe"),

    # Nurse patient-monitoring list
    path("monitoring/", in_module(MonitoringListView, "opd").as_view(), name="opd-monitoring"),

    # Visit history — searchable, not date-limited to today
    path("history/", in_module(AppointmentHistoryView, "opd").as_view(), name="appointment-history"),

    # Upcoming — today onward, ascending, powers the doctor's multi-day dashboard
    path("appointments/upcoming/", in_module(AppointmentUpcomingView, "opd").as_view(), name="appointment-upcoming"),

    # Appointments / Queue
    path("appointments/", in_module(AppointmentListCreateView, "opd").as_view(), name="appointment-list-create"),
    path("appointments/<uuid:pk>/", in_module(AppointmentDetailView, "opd").as_view(), name="appointment-detail"),
    path("appointments/<uuid:pk>/status/", in_module(AppointmentStatusView, "opd").as_view(), name="appointment-status"),
    path("appointments/<uuid:pk>/reschedule/", in_module(AppointmentRescheduleView, "opd").as_view(), name="appointment-reschedule"),
    path("appointments/<uuid:pk>/vitals/", in_module(VitalsView, "opd").as_view(), name="vitals"),

    # Encounters
    path("encounters/", in_module(EncounterCreateView, "opd").as_view(), name="encounter-create"),
    path("encounters/<uuid:pk>/", in_module(EncounterDetailView, "opd").as_view(), name="encounter-detail"),
    path("encounters/<uuid:pk>/sign/", in_module(EncounterSignView, "opd").as_view(), name="encounter-sign"),
    path("encounters/<uuid:pk>/consult-session/", in_module(EncounterConsultSessionView, "opd").as_view(), name="encounter-consult-session"),
    path("encounters/<uuid:pk>/internal-note/", in_module(EncounterInternalNoteView, "opd").as_view(), name="encounter-internal-note"),
    path("encounters/<uuid:pk>/pdf/", in_module(EncounterSummaryPDFView, "opd").as_view(), name="encounter-summary-pdf"),
    path("encounters/<uuid:pk>/follow-up/", in_module(FollowUpActionView, "opd").as_view(), name="encounter-follow-up"),
    path("encounters/<uuid:pk>/previous/", in_module(PreviousEncounterView, "opd").as_view(), name="encounter-previous"),

    # Nurse follow-up-booking worklist (Phase 1 of the doctor->nurse handoff)
    path("followups/nurse-worklist/", in_module(FollowupNurseWorklistView, "opd").as_view(), name="followup-nurse-worklist"),
    path("followups/<uuid:pk>/mark-booked/", in_module(FollowupMarkBookedView, "opd").as_view(), name="followup-mark-booked"),

    # Prescriptions
    path("prescriptions/", in_module(PrescriptionCreateView, "opd").as_view(), name="prescription-create"),
    path("prescriptions/<uuid:pk>/", in_module(PrescriptionDetailView, "opd").as_view(), name="prescription-detail"),
    path("prescriptions/<uuid:pk>/items/", in_module(PrescriptionItemView, "opd").as_view(), name="prescription-items"),
    path("prescriptions/<uuid:pk>/items/<uuid:item_id>/", in_module(PrescriptionItemView, "opd").as_view(), name="prescription-item-delete"),

    # Favourites
    path("favourites/", in_module(FavouriteListCreateView, "opd").as_view(), name="favourites"),
    path("favourites/<uuid:pk>/", in_module(FavouriteDeleteView, "opd").as_view(), name="favourite-delete"),
]
