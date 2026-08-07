from django.urls import path
from .views import (
    StaffLoginView, PlatformLoginView, PatientLoginView,
    MeView, PermissionsView, TokenRefreshView, LogoutView,
    SetupPasswordView, ChangePasswordView, StaffForgotPasswordView,
)

urlpatterns = [
    path("login/staff/",      StaffLoginView.as_view(),     name="staff-login"),
    path("login/platform/",   PlatformLoginView.as_view(),  name="platform-login"),
    path("login/patient/",    PatientLoginView.as_view(),   name="patient-login"),
    path("token/refresh/",    TokenRefreshView.as_view(),   name="token-refresh"),
    path("logout/",           LogoutView.as_view(),          name="logout"),
    path("setup-password/",   SetupPasswordView.as_view(),  name="setup-password"),
    path("change-password/",  ChangePasswordView.as_view(), name="change-password"),
    path("forgot-password/staff/", StaffForgotPasswordView.as_view(), name="staff-forgot-password"),
    path("me/",               MeView.as_view(),              name="me"),
    path("me/permissions/",   PermissionsView.as_view(),     name="me-permissions"),
]
