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
from .doc_classification_views import (
    DocRuleListCreateView, DocRuleDetailView, DocRuleTestView, DocClassificationReportView, LLMStatusView,
)
from .jobs_views import (
    JobsRuntimeView, JobsProcessActionView, JobsProcessLogView, JobsTaskCatalogView,
    JobsRunNowView, JobsScheduleListCreateView, JobsScheduleDetailView, JobsScheduleRunView,
    JobsHistoryView,
)
from .milestone_template_views import (
    MilestoneTemplateListCreateView, MilestoneTemplateDetailView,
)

urlpatterns = [
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

    # My Reports document classifier — keyword rules + agreement report.
    path("doc-rules/", DocRuleListCreateView.as_view(), name="platform-doc-rules"),
    path("doc-rules/test/", DocRuleTestView.as_view(), name="platform-doc-rules-test"),
    path("doc-rules/<int:pk>/", DocRuleDetailView.as_view(), name="platform-doc-rule-detail"),
    path("doc-classification/report/", DocClassificationReportView.as_view(), name="platform-doc-classification-report"),
    path("llm/status/", LLMStatusView.as_view(), name="platform-llm-status"),

    # Background jobs — Celery worker/beat control, scheduled jobs, history.
    path("jobs/runtime/", JobsRuntimeView.as_view(), name="platform-jobs-runtime"),
    path("jobs/runtime/<str:kind>/log/", JobsProcessLogView.as_view(), name="platform-jobs-log"),
    path("jobs/runtime/<str:kind>/<str:action>/", JobsProcessActionView.as_view(), name="platform-jobs-action"),
    path("jobs/tasks/", JobsTaskCatalogView.as_view(), name="platform-jobs-tasks"),
    path("jobs/run/", JobsRunNowView.as_view(), name="platform-jobs-run"),
    path("jobs/schedules/", JobsScheduleListCreateView.as_view(), name="platform-jobs-schedules"),
    path("jobs/schedules/<int:pk>/", JobsScheduleDetailView.as_view(), name="platform-jobs-schedule-detail"),
    path("jobs/schedules/<int:pk>/run/", JobsScheduleRunView.as_view(), name="platform-jobs-schedule-run"),
    path("jobs/history/", JobsHistoryView.as_view(), name="platform-jobs-history"),
]
