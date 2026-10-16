from django.urls import path
from apps.facility.views import (
    BedBoardView,
    BedDetailView,
    BedListCreateView,
    BedMaintenanceView,
    BedMarkCleanView,
    BranchDetailView,
    BranchListCreateView,
    DepartmentAvailabilityView,
    DepartmentDetailView,
    DepartmentListCreateView,
    FloorDetailView,
    FloorListCreateView,
    RoomDetailView,
    RoomListCreateView,
)

urlpatterns = [
    path("branches/",              BranchListCreateView.as_view(), name="branch-list-create"),
    path("branches/<int:pk>/",     BranchDetailView.as_view(),     name="branch-detail"),
    path("departments/",           DepartmentListCreateView.as_view(), name="dept-list-create"),
    path("departments/<int:pk>/",  DepartmentDetailView.as_view(),     name="dept-detail"),
    path("rooms/",                             RoomListCreateView.as_view(),       name="room-list-create"),
    path("rooms/<int:pk>/",                    RoomDetailView.as_view(),           name="room-detail"),
    path("floors/",                            FloorListCreateView.as_view(),      name="floor-list-create"),
    path("floors/<int:pk>/",                   FloorDetailView.as_view(),          name="floor-detail"),
    path("beds/board/",                        BedBoardView.as_view(),             name="bed-board"),
    path("beds/",                              BedListCreateView.as_view(),        name="bed-list-create"),
    path("beds/<int:pk>/",                     BedDetailView.as_view(),            name="bed-detail"),
    path("beds/<int:pk>/mark-clean/",          BedMarkCleanView.as_view(),         name="bed-mark-clean"),
    path("beds/<int:pk>/maintenance/",         BedMaintenanceView.as_view(),       name="bed-maintenance"),
    path("departments/availability/",          DepartmentAvailabilityView.as_view(), name="dept-availability"),
]
