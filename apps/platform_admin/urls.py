from django.urls import path
from .views import (
    TenantListCreateView, TenantDetailView, TenantAuditLogView,
    PlatformStatsView, TenantOverviewView, TenantStaffListView,
    TenantStaffDetailView, TenantStaffResetPasswordView,
    PlatformUserListView, PlanListView,
)
from .vaccination_template_views import (
    VaccinationTemplateListCreateView, VaccinationTemplateDetailView,
)
from .classification_rule_views import (
    ClassificationRuleListCreateView, ClassificationRuleDetailView,
    SweepConfigView, DocumentReportView, DocumentCorrectView,
)
from .milestone_template_views import (
    MilestoneTemplateListCreateView, MilestoneTemplateDetailView,
)

urlpatterns = [
    path("classification-rules/",          ClassificationRuleListCreateView.as_view(), name="platform-classification-rules"),
    path("classification-rules/<int:pk>/", ClassificationRuleDetailView.as_view(), name="platform-classification-rule-detail"),
    path("records/sweep-config/",   SweepConfigView.as_view(), name="platform-records-sweep-config"),
    path("records/report/",         DocumentReportView.as_view(), name="platform-records-report"),
    path("records/report/<int:pk>/", DocumentCorrectView.as_view(), name="platform-records-report-detail"),
    path("stats/",          PlatformStatsView.as_view(), name="platform-stats"),
    path("plans/",          PlanListView.as_view(), name="platform-plans"),
    path("users/",          PlatformUserListView.as_view(), name="platform-users"),

    path("tenants/",        TenantListCreateView.as_view(), name="platform-tenant-list"),
    path("tenants/<int:pk>/", TenantDetailView.as_view(), name="platform-tenant-detail"),
    path("tenants/<int:pk>/audit-log/", TenantAuditLogView.as_view(), name="platform-tenant-audit-log"),
    path("tenants/<int:pk>/overview/",  TenantOverviewView.as_view(), name="platform-tenant-overview"),
    path("tenants/<int:pk>/staff/",     TenantStaffListView.as_view(), name="platform-tenant-staff-list"),
    path("tenants/<int:pk>/staff/<int:staff_id>/", TenantStaffDetailView.as_view(), name="platform-tenant-staff-detail"),
    path("tenants/<int:pk>/staff/<int:staff_id>/reset-password/",
         TenantStaffResetPasswordView.as_view(), name="platform-tenant-staff-reset-password"),

    # System-level vaccination schedule templates (owner_tenant_id=None,
    # is_template=True) — cloned by hospital admins via
    # apps.org.vaccination_schedule_views.VaccinationScheduleListCreateView.
    path("vaccination-templates/", VaccinationTemplateListCreateView.as_view(), name="platform-vaccination-template-list-create"),
    path("vaccination-templates/<int:pk>/", VaccinationTemplateDetailView.as_view(), name="platform-vaccination-template-detail"),

    # System-level developmental-milestone schedule templates — same
    # clone-a-template pattern as vaccination templates above.
    path("milestone-templates/", MilestoneTemplateListCreateView.as_view(), name="platform-milestone-template-list-create"),
    path("milestone-templates/<int:pk>/", MilestoneTemplateDetailView.as_view(), name="platform-milestone-template-detail"),
]
