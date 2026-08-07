from django.urls import path
from .views import (
    TenantListCreateView, TenantDetailView, TenantAuditLogView,
    PlatformStatsView, TenantOverviewView, TenantStaffListView,
    TenantStaffDetailView, TenantStaffResetPasswordView,
    PlatformUserListView, PlanListView,
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
]
