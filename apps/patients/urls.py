"""Patient portal, emergency summary, consult pad and record-sharing routes, all under /api/v1/."""
from django.urls import include, path
from apps.patients.views import (
    PortalRegisterView,
    PortalHospitalListView,
    PortalPlatformStatsView,
    PortalSearchView,
    PortalSpecialtyListView,
    PortalDoctorListView,
    PortalDoctorDetailView,
    PortalNextTokenView,
    PortalSlotListView,
    PortalBookView,
    PortalHospitalSharingView,
    PortalMyBookingsView,
    PortalCancelBookingView,
    PortalRescheduleBookingView,
    PortalMyRecordsView,
    PortalDocumentListCreateView,
    PortalDocumentDetailView,
    PortalDocumentPreviewView,
    PortalDocumentZipView,
    PortalDocumentCountsView,
    PortalDocumentDaysView,
    PortalLabOrderListView,
    PortalLabOrderChoiceView,
    PortalPrescriptionListView,
    PortalPrescriptionChoiceView,
    PortalPrescriptionReceiptPDFView,
    PortalLabReportFileView,
    PortalProfileView,
    PortalChangePasswordView,
    PortalMobileChangeRequestOTPView,
    PortalInvoiceListView,
    PortalInvoiceReceiptPDFView,
    PortalHealthSummaryView,
    PortalHealthTimelineView,
    PortalNotificationsView,
    PortalNotificationMarkReadView,
    PortalEmergencyTokenView,
)
from apps.documents.views import (
    PortalFamilyListCreateView,
    PortalFamilyDetailView,
    PortalVaccinationListView,
    PortalVaccinationUploadView,
    PortalVaccinationFileView,
    PortalGrowthView,
    PortalMilestoneListView,
)
from apps.patients.views import (
    RecordsShareCreateView,
    RecordsShareDecisionView,
    RecordsShareEndView,
    RecordsShareDownloadDecisionView,
    RecordsShareMineView,
    RecordsPrivacyView,
    RecordsPrivacyToggleView,
    RecordsShareRevealView,
    RecordsShareClaimView,
    RecordsShareStatusView,
    RecordsShareRecordsView,
    RecordsShareDownloadView,
    RecordsShareDocumentViewView,
    RecordsShareCloseView,
)
from apps.patients.views import EmergencySummaryView
from apps.patients.views import ConsultPadView


portal_urlpatterns = [
    path("register/",                       PortalRegisterView.as_view(),     name="portal-register"),
    path("hospitals/",                      PortalHospitalListView.as_view(), name="portal-hospitals"),
    path("stats/",                          PortalPlatformStatsView.as_view(), name="portal-stats"),
    path("search/",                         PortalSearchView.as_view(),       name="portal-search"),
    path("specialties/",                    PortalSpecialtyListView.as_view(), name="portal-specialties"),
    path("hospitals/<int:hospital_id>/doctors/", PortalDoctorListView.as_view(), name="portal-doctors"),
    path("hospitals/<int:hospital_id>/doctors/<int:doctor_id>/", PortalDoctorDetailView.as_view(), name="portal-doctor-detail"),
    path("hospitals/<int:hospital_id>/doctors/<int:doctor_id>/slots/", PortalSlotListView.as_view(), name="portal-slots"),
    path("hospitals/<int:hospital_id>/doctors/<int:doctor_id>/next-token/", PortalNextTokenView.as_view(), name="portal-next-token"),
    path("book/",                           PortalBookView.as_view(),         name="portal-book"),
    path("hospital-sharing/",               PortalHospitalSharingView.as_view(), name="portal-hospital-sharing"),
    path("my-bookings/",                    PortalMyBookingsView.as_view(),   name="portal-my-bookings"),
    path("my-bookings/<int:pk>/cancel/",     PortalCancelBookingView.as_view(), name="portal-my-bookings-cancel"),
    path("my-bookings/<int:pk>/reschedule/", PortalRescheduleBookingView.as_view(), name="portal-my-bookings-reschedule"),
    path("my-records/",                     PortalMyRecordsView.as_view(),    name="portal-my-records"),
    path("invoices/",                       PortalInvoiceListView.as_view(),  name="portal-invoices"),
    path("invoices/<str:hospital_db>/<int:pk>/receipt/", PortalInvoiceReceiptPDFView.as_view(), name="portal-invoice-receipt"),
    path("documents/",                      PortalDocumentListCreateView.as_view(), name="portal-documents"),
    path("documents/zip/",                  PortalDocumentZipView.as_view(), name="portal-documents-zip"),
    path("documents/counts/",               PortalDocumentCountsView.as_view(), name="portal-documents-counts"),
    path("documents/days/",                 PortalDocumentDaysView.as_view(), name="portal-documents-days"),
    path("documents/<int:doc_id>/",         PortalDocumentDetailView.as_view(), name="portal-document-detail"),
    path("documents/<int:doc_id>/preview/", PortalDocumentPreviewView.as_view(), name="portal-document-preview"),
    path("lab-orders/",                     PortalLabOrderListView.as_view(), name="portal-lab-orders"),
    path("lab-orders/choice/",              PortalLabOrderChoiceView.as_view(), name="portal-lab-order-choice"),
    path("lab-orders/<str:hospital_db>/<int:request_id>/report/", PortalLabReportFileView.as_view(), name="portal-lab-report-file"),
    path("prescriptions/",                  PortalPrescriptionListView.as_view(), name="portal-prescriptions"),
    path("prescriptions/choice/",           PortalPrescriptionChoiceView.as_view(), name="portal-prescription-choice"),
    path("prescriptions/<str:hospital_db>/<uuid:pk>/receipt/", PortalPrescriptionReceiptPDFView.as_view(), name="portal-prescription-receipt"),
    path("profile/",                        PortalProfileView.as_view(),      name="portal-profile"),
    path("profile/change-password/",        PortalChangePasswordView.as_view(), name="portal-change-password"),
    path("profile/mobile-change/request-otp/", PortalMobileChangeRequestOTPView.as_view(), name="portal-mobile-change-request-otp"),
    path("family/",                         PortalFamilyListCreateView.as_view(), name="portal-family"),
    path("family/<str:awpid>/",             PortalFamilyDetailView.as_view(), name="portal-family-detail"),
    path("health-summary/",                 PortalHealthSummaryView.as_view(), name="portal-health-summary"),
    path("vaccinations/",                   PortalVaccinationListView.as_view(), name="portal-vaccinations"),
    path("vaccinations/upload/",            PortalVaccinationUploadView.as_view(), name="portal-vaccinations-upload"),
    path("vaccinations/<int:record_id>/file/", PortalVaccinationFileView.as_view(), name="portal-vaccinations-file"),
    path("growth/",                         PortalGrowthView.as_view(), name="portal-growth"),
    path("milestones/",                     PortalMilestoneListView.as_view(), name="portal-milestones"),
    path("timeline/",                       PortalHealthTimelineView.as_view(), name="portal-timeline"),
    path("notifications/",                  PortalNotificationsView.as_view(), name="portal-notifications"),
    path("notifications/<str:hospital_db>/<int:pk>/read/", PortalNotificationMarkReadView.as_view(), name="portal-notifications-read"),
    path("emergency/token/",                PortalEmergencyTokenView.as_view(), name="portal-emergency-token"),

    # "Share Records" — patient-authenticated half: create the session, then
    path("records-share/",                            RecordsShareCreateView.as_view(),           name="portal-records-share-create"),
    path("records-share/mine/",                       RecordsShareMineView.as_view(),             name="portal-records-share-mine"),
    # Shared-records privacy — the standing "what a doctor sees" config, the
    path("records-privacy/",                          RecordsPrivacyView.as_view(),               name="portal-records-privacy"),
    path("records-privacy/toggle/",                   RecordsPrivacyToggleView.as_view(),         name="portal-records-privacy-toggle"),
    path("records-share/<str:token>/reveal/",         RecordsShareRevealView.as_view(),           name="portal-records-share-reveal"),
    path("records-share/<str:token>/decision/",       RecordsShareDecisionView.as_view(),         name="portal-records-share-decision"),
    path("records-share/<str:token>/end/",            RecordsShareEndView.as_view(),              name="portal-records-share-end"),
    path("records-share/<str:token>/downloads/decision/", RecordsShareDownloadDecisionView.as_view(), name="portal-records-share-download-decision"),
]


emergency_urlpatterns = [
    path("<str:token>/", EmergencySummaryView.as_view(), name="emergency-summary"),
]


# One path, both verbs — GET fetches the patient header for the phone
consult_pad_urlpatterns = [
    path("<str:token>/", ConsultPadView.as_view(), name="consult-pad"),
]


records_share_urlpatterns = [
    # Must precede "<str:token>/" — the doctor's laptop binds itself here,
    path("claim/",                                  RecordsShareClaimView.as_view(),       name="records-share-claim"),
    path("<str:token>/records/",                    RecordsShareRecordsView.as_view(),     name="records-share-records"),
    path("<str:token>/documents/<int:doc_id>/view/", RecordsShareDocumentViewView.as_view(), name="records-share-doc-view"),
    path("<str:token>/downloads/",                  RecordsShareDownloadView.as_view(),    name="records-share-downloads"),
    path("<str:token>/close/",                      RecordsShareCloseView.as_view(),       name="records-share-close"),
    path("<str:token>/",                            RecordsShareStatusView.as_view(),      name="records-share-status"),
]


urlpatterns = [
    path("portal/", include(portal_urlpatterns)),
    path("emergency/", include(emergency_urlpatterns)),
    path("consult-pad/", include(consult_pad_urlpatterns)),
    path("records-share/", include(records_share_urlpatterns)),
]
