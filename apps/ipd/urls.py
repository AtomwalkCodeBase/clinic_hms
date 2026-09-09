from django.urls import path
from .views import (
    RecommendAdmissionView, AcceptExternalReferralView, PendingReferralsListView,
    CompleteAdmissionView, AdmissionListView, AdmissionDetailView, AdmissionDepositView,
    AdmissionTypeListCreateView, AdmissionTypeDetailView,
    AdmissionSourceListCreateView, AdmissionSourceDetailView,
)

urlpatterns = [
    # Doctor-authored referrals — the enforcement point (see views.py)
    path("referrals/",                   PendingReferralsListView.as_view(),  name="ipd-referral-list"),
    path("referrals/recommend/",         RecommendAdmissionView.as_view(),    name="ipd-referral-recommend"),
    path("referrals/<uuid:pk>/accept/",  AcceptExternalReferralView.as_view(),name="ipd-referral-accept"),

    # Front desk — registration only
    path("admissions/",                  AdmissionListView.as_view(),         name="ipd-admission-list"),
    path("admissions/register/",         CompleteAdmissionView.as_view(),     name="ipd-admission-register"),
    path("admissions/<uuid:pk>/",        AdmissionDetailView.as_view(),       name="ipd-admission-detail"),
    path("admissions/<uuid:pk>/deposit/",AdmissionDepositView.as_view(),      name="ipd-admission-deposit"),

    # Hospital-admin-configurable catalogs ("make it configurable")
    path("admission-types/",             AdmissionTypeListCreateView.as_view(),   name="ipd-admission-type-list"),
    path("admission-types/<int:pk>/",    AdmissionTypeDetailView.as_view(),       name="ipd-admission-type-detail"),
    path("admission-sources/",           AdmissionSourceListCreateView.as_view(), name="ipd-admission-source-list"),
    path("admission-sources/<int:pk>/",  AdmissionSourceDetailView.as_view(),     name="ipd-admission-source-detail"),
]
