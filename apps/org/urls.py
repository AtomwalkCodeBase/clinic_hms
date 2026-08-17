from django.urls import path
from .views import (
    BranchListCreateView, BranchDetailView,
    DepartmentListCreateView, DepartmentDetailView,
    StaffListView, StaffInviteView, StaffDetailView, StaffResendInviteView,
    DoctorProfileView, DoctorListView, MyDoctorProfileView, MyStaffProfileView,
    StaffProfileView, MyStaffProfileDetailsView,
    StaffBranchesView, MyBranchesView,
    PermissionListView, RoleListCreateView, RoleDetailView, StaffRolesView,
    TenantSettingsView, DoctorScheduleView,
    RoomListCreateView, RoomDetailView,
    RoomAssignmentListCreateView, RoomAssignmentDetailView,
)
from .vaccination_schedule_views import (
    VaccinationScheduleListCreateView, VaccinationScheduleDetailView, VaccinationScheduleActivateView,
)

urlpatterns = [
    # Branches
    path("branches/",              BranchListCreateView.as_view(), name="branch-list-create"),
    path("branches/<int:pk>/",     BranchDetailView.as_view(),     name="branch-detail"),

    # Departments
    path("departments/",           DepartmentListCreateView.as_view(), name="dept-list-create"),
    path("departments/<int:pk>/",  DepartmentDetailView.as_view(),     name="dept-detail"),

    # Staff
    path("staff/",                 StaffListView.as_view(),   name="staff-list"),
    path("staff/invite/",          StaffInviteView.as_view(), name="staff-invite"),
    path("staff/<int:pk>/",        StaffDetailView.as_view(), name="staff-detail"),
    path("staff/<int:pk>/resend-invite/", StaffResendInviteView.as_view(), name="staff-resend-invite"),
    path("staff/<int:pk>/branches/", StaffBranchesView.as_view(), name="staff-branches"),

    # Doctor profiles (nested under staff — admin only)
    path("staff/<int:pk>/doctor-profile/", DoctorProfileView.as_view(), name="doctor-profile"),

    # Non-doctor staff profiles (nested under staff — admin only)
    path("staff/<int:pk>/profile/", StaffProfileView.as_view(), name="staff-profile"),

    # Doctor self-service profile (own login — no :pk, always "me")
    path("me/doctor-profile/",     MyDoctorProfileView.as_view(), name="my-doctor-profile"),

    # Non-doctor self-service profile (own login — no :pk, always "me")
    path("me/staff-profile/",      MyStaffProfileDetailsView.as_view(), name="my-staff-profile-details"),

    # Any staff role's own basic profile (currently: photo) — own login only
    path("me/profile/",            MyStaffProfileView.as_view(), name="my-staff-profile"),

    # Own branch assignment — self-service read, used to decide whether to
    # show a branch switcher (see apps.org.branch_utils)
    path("me/branches/",           MyBranchesView.as_view(), name="my-branches"),

    # Doctors list (for scheduling dropdowns, any staff can read)
    path("doctors/",               DoctorListView.as_view(), name="doctor-list"),

    # Table-driven RBAC — see apps.org.rbac
    path("permissions/",           PermissionListView.as_view(),  name="permission-list"),
    path("roles/",                 RoleListCreateView.as_view(),  name="role-list-create"),
    path("roles/<int:pk>/",        RoleDetailView.as_view(),      name="role-detail"),
    path("staff/<int:pk>/roles/",  StaffRolesView.as_view(),      name="staff-roles"),

    # Vaccination schedules — per-hospital roadmap configuration (clone a
    # system template, edit its rules, switch which schedule is active).
    path("vaccination-schedules/",             VaccinationScheduleListCreateView.as_view(), name="vaccination-schedule-list-create"),
    path("vaccination-schedules/<int:pk>/",    VaccinationScheduleDetailView.as_view(),     name="vaccination-schedule-detail"),
    path("vaccination-schedules/<int:pk>/activate/", VaccinationScheduleActivateView.as_view(), name="vaccination-schedule-activate"),

    # Tenant-level clinical settings (fee_ownership, etc.)
    path("settings/",                          TenantSettingsView.as_view(),   name="tenant-settings"),

    # Doctor working-hours schedule
    path("staff/<int:pk>/schedule/",           DoctorScheduleView.as_view(),   name="doctor-schedule"),

    # Rooms & room assignments (floors, which doctor sits where and when)
    path("rooms/",                             RoomListCreateView.as_view(),       name="room-list-create"),
    path("rooms/<int:pk>/",                    RoomDetailView.as_view(),           name="room-detail"),
    path("room-assignments/",                  RoomAssignmentListCreateView.as_view(), name="room-assignment-list-create"),
    path("room-assignments/<int:pk>/",         RoomAssignmentDetailView.as_view(),     name="room-assignment-detail"),
]
