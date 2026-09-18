from django.urls import path
from .views import (
    BranchListCreateView, BranchDetailView,
    DepartmentListCreateView, DepartmentDetailView,
    StaffListView, StaffInviteView, StaffDetailView, StaffResendInviteView,
    DoctorProfileView, DoctorListView, DoctorSpecialisationListView, MyDoctorProfileView, MyStaffProfileView,
    StaffProfileView, MyStaffProfileDetailsView,
    StaffBranchesView, MyBranchesView, StaffDoctorsView,
    PermissionListView, RoleListCreateView, RoleDetailView, StaffRolesView,
    TenantSettingsView, DoctorScheduleView,
    FloorListCreateView, FloorDetailView,
    RoomListCreateView, RoomDetailView,
    RoomAssignmentListCreateView, RoomAssignmentDetailView,
    BedListCreateView, BedDetailView, BedMarkCleanView, BedMaintenanceView, BedBoardView,
    DepartmentAvailabilityView,
)
from .vaccination_schedule_views import (
    VaccinationScheduleListCreateView, VaccinationScheduleDetailView, VaccinationScheduleActivateView,
)
from .milestone_schedule_views import (
    MilestoneScheduleListCreateView, MilestoneScheduleDetailView, MilestoneScheduleActivateView,
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
    path("staff/<int:pk>/doctors/",  StaffDoctorsView.as_view(),  name="staff-doctors"),

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
    path("doctors/specialisations/", DoctorSpecialisationListView.as_view(), name="doctor-specialisations"),

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

    # Pediatric developmental-milestone schedules — same hospital-configurable
    # clone-a-template pattern as vaccination schedules above.
    path("milestone-schedules/",             MilestoneScheduleListCreateView.as_view(), name="milestone-schedule-list-create"),
    path("milestone-schedules/<int:pk>/",    MilestoneScheduleDetailView.as_view(),     name="milestone-schedule-detail"),
    path("milestone-schedules/<int:pk>/activate/", MilestoneScheduleActivateView.as_view(), name="milestone-schedule-activate"),

    # Tenant-level clinical settings (fee_ownership, etc.)
    path("settings/",                          TenantSettingsView.as_view(),   name="tenant-settings"),

    # Doctor working-hours schedule
    path("staff/<int:pk>/schedule/",           DoctorScheduleView.as_view(),   name="doctor-schedule"),

    # Rooms & room assignments (floors, which doctor sits where and when)
    path("rooms/",                             RoomListCreateView.as_view(),       name="room-list-create"),
    path("rooms/<int:pk>/",                    RoomDetailView.as_view(),           name="room-detail"),
    path("room-assignments/",                  RoomAssignmentListCreateView.as_view(), name="room-assignment-list-create"),
    path("room-assignments/<int:pk>/",         RoomAssignmentDetailView.as_view(),     name="room-assignment-detail"),

    # Floors (set up once per branch; Rooms — OPD and bed-based IPD alike —
    # assign to one)
    path("floors/",                            FloorListCreateView.as_view(),      name="floor-list-create"),
    path("floors/<int:pk>/",                   FloorDetailView.as_view(),          name="floor-detail"),

    # Beds (IPD bed assignment — see docs/PENDING_IMPROVEMENTS.md item 3).
    # What used to be a separate wards/ endpoint is just rooms/ above now —
    # a ward IS a Room (bed-based room_type) since the v8 unification.
    path("beds/board/",                        BedBoardView.as_view(),             name="bed-board"),
    path("beds/",                              BedListCreateView.as_view(),        name="bed-list-create"),
    path("beds/<int:pk>/",                     BedDetailView.as_view(),            name="bed-detail"),
    path("beds/<int:pk>/mark-clean/",          BedMarkCleanView.as_view(),         name="bed-mark-clean"),
    path("beds/<int:pk>/maintenance/",         BedMaintenanceView.as_view(),       name="bed-maintenance"),

    # Front-desk triage: per-department doctor availability
    path("departments/availability/",          DepartmentAvailabilityView.as_view(), name="dept-availability"),
]
