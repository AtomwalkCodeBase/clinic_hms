from django.urls import path
from apps.hospital_master.platform_views import (
    HospitalListCreateView,
    HospitalDetailView,
    HospitalAuditLogView,
    PlatformStatsView,
    HospitalOverviewView,
    HospitalStaffListView,
    HospitalStaffDetailView,
    HospitalStaffResetPasswordView,
    PlatformUserListView,
    PlanListView,
)
from apps.documents.views import (
    VaccinationTemplateListCreateView,
    VaccinationTemplateDetailView,
)
from apps.hospital_master.classification_rule_views import DocumentReportView, DocumentCorrectView, ReclassifyView

urlpatterns = [
    path("records/report/",         DocumentReportView.as_view(), name="platform-records-report"),
    path("records/report/<int:pk>/", DocumentCorrectView.as_view(), name="platform-records-report-detail"),
    path("records/reclassify/", ReclassifyView.as_view(), name="platform-records-reclassify"),
    path("stats/",          PlatformStatsView.as_view(), name="platform-stats"),
    path("plans/",          PlanListView.as_view(), name="platform-plans"),
    path("users/",          PlatformUserListView.as_view(), name="platform-users"),

    path("hospitals/",        HospitalListCreateView.as_view(), name="platform-hospital-list"),
    path("hospitals/<int:pk>/", HospitalDetailView.as_view(), name="platform-hospital-detail"),
    path("hospitals/<int:pk>/audit-log/", HospitalAuditLogView.as_view(), name="platform-hospital-audit-log"),
    path("hospitals/<int:pk>/overview/",  HospitalOverviewView.as_view(), name="platform-hospital-overview"),
    path("hospitals/<int:pk>/staff/",     HospitalStaffListView.as_view(), name="platform-hospital-staff-list"),
    path("hospitals/<int:pk>/staff/<int:staff_id>/", HospitalStaffDetailView.as_view(), name="platform-hospital-staff-detail"),
    path("hospitals/<int:pk>/staff/<int:staff_id>/reset-password/",
         HospitalStaffResetPasswordView.as_view(), name="platform-hospital-staff-reset-password"),

    # System-level vaccination schedule templates (owner_hospital_id=None,
    path("vaccination-templates/", VaccinationTemplateListCreateView.as_view(), name="platform-vaccination-template-list-create"),
    path("vaccination-templates/<int:pk>/", VaccinationTemplateDetailView.as_view(), name="platform-vaccination-template-detail"),

    # System-level developmental-milestone schedule templates — same
]
