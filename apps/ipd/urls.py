from django.urls import path
from .views import (
    RecommendAdmissionView, RegisterExternalReferralView, AcceptExternalReferralView, PendingReferralsListView,
    CompleteAdmissionView, AdmissionListView, AdmissionDetailView, AdmissionDepositView,
    AdmissionTypeListCreateView, AdmissionTypeDetailView,
    AdmissionSourceListCreateView, AdmissionSourceDetailView,
    AssignBedView, ReleaseBedView, AwaitingBedListView,
    ReserveBedView, CancelBedReservationView, TransferBedView, AdmissionMovementsView,
    DischargeAdmissionView, GenerateInvoiceView,
    MyReferralsListView, MyAdmittedPatientsView,
)

urlpatterns = [
    # Referrals — the enforcement point (see views.py). Doctor-authored via
    # recommend/; front-desk-logged-from-an-external-letter via
    # register-external/ — either way accept/ is the same doctor countersign.
    path("referrals/",                   PendingReferralsListView.as_view(),  name="ipd-referral-list"),
    path("referrals/mine/",              MyReferralsListView.as_view(),       name="ipd-referral-mine"),
    path("referrals/recommend/",         RecommendAdmissionView.as_view(),    name="ipd-referral-recommend"),
    path("referrals/register-external/", RegisterExternalReferralView.as_view(), name="ipd-referral-register-external"),
    path("referrals/<uuid:pk>/accept/",  AcceptExternalReferralView.as_view(),name="ipd-referral-accept"),

    # Front desk — registration, edit, discharge, billing
    path("admissions/",                  AdmissionListView.as_view(),         name="ipd-admission-list"),
    path("admissions/mine/",             MyAdmittedPatientsView.as_view(),    name="ipd-admission-mine"),
    path("admissions/register/",         CompleteAdmissionView.as_view(),     name="ipd-admission-register"),
    path("admissions/awaiting-bed/",     AwaitingBedListView.as_view(),       name="ipd-admission-awaiting-bed"),
    path("admissions/<uuid:pk>/",        AdmissionDetailView.as_view(),       name="ipd-admission-detail"),  # GET (any staff) + PATCH (front desk)
    path("admissions/<uuid:pk>/deposit/",AdmissionDepositView.as_view(),      name="ipd-admission-deposit"),
    path("admissions/<uuid:pk>/assign-bed/",  AssignBedView.as_view(),        name="ipd-admission-assign-bed"),
    path("admissions/<uuid:pk>/release-bed/", ReleaseBedView.as_view(),       name="ipd-admission-release-bed"),
    path("admissions/<uuid:pk>/reserve-bed/", ReserveBedView.as_view(),       name="ipd-admission-reserve-bed"),
    path("admissions/<uuid:pk>/cancel-bed-reservation/", CancelBedReservationView.as_view(), name="ipd-admission-cancel-bed-reservation"),
    path("admissions/<uuid:pk>/transfer-bed/",    TransferBedView.as_view(),       name="ipd-admission-transfer-bed"),
    path("admissions/<uuid:pk>/movements/",       AdmissionMovementsView.as_view(), name="ipd-admission-movements"),
    path("admissions/<uuid:pk>/discharge/",       DischargeAdmissionView.as_view(), name="ipd-admission-discharge"),
    path("admissions/<uuid:pk>/generate-invoice/",GenerateInvoiceView.as_view(),    name="ipd-admission-generate-invoice"),

    # Hospital-admin-configurable catalogs ("make it configurable")
    path("admission-types/",             AdmissionTypeListCreateView.as_view(),   name="ipd-admission-type-list"),
    path("admission-types/<int:pk>/",    AdmissionTypeDetailView.as_view(),       name="ipd-admission-type-detail"),
    path("admission-sources/",           AdmissionSourceListCreateView.as_view(), name="ipd-admission-source-list"),
    path("admission-sources/<int:pk>/",  AdmissionSourceDetailView.as_view(),     name="ipd-admission-source-detail"),
]
