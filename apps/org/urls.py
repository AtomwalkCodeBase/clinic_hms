from django.urls import path
from .views import (
    BranchListCreateView, BranchDetailView,
    DepartmentListCreateView, DepartmentDetailView,
    StaffListView, StaffInviteView, StaffDetailView, StaffResendInviteView,
    DoctorProfileView, DoctorListView, MyDoctorProfileView, MyStaffProfileView,
    StaffProfileView, MyStaffProfileDetailsView,
    StaffBranchesView, MyBranchesView,
    PermissionListView, RoleListCreateView, RoleDetailView, StaffRolesView,
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
]
