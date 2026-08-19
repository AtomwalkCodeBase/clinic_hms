from django.urls import path
from .views import (
    StaffLoginView, PlatformLoginView, PatientLoginView,
    MeView, PermissionsView, TokenRefreshView, LogoutView,
    SetupPasswordView, ChangePasswordView,
)
from .otp_views import (
    OTPRequestView, OTPVerifyView,
    StaffForgotPasswordResetView, PatientForgotPasswordResetView,
    PatientOTPLoginView,
)

urlpatterns = [
    path("login/staff/",      StaffLoginView.as_view(),     name="staff-login"),
    path("login/platform/",   PlatformLoginView.as_view(),  name="platform-login"),
    path("login/patient/",    PatientLoginView.as_view(),   name="patient-login"),
    path("login/patient/otp/", PatientOTPLoginView.as_view(), name="patient-login-otp"),
    path("token/refresh/",    TokenRefreshView.as_view(),   name="token-refresh"),
    path("logout/",           LogoutView.as_view(),          name="logout"),
    path("setup-password/",   SetupPasswordView.as_view(),  name="setup-password"),
    path("change-password/",  ChangePasswordView.as_view(), name="change-password"),
    path("otp/request/",      OTPRequestView.as_view(),      name="otp-request"),
    path("otp/verify/",       OTPVerifyView.as_view(),       name="otp-verify"),
    path("forgot-password/staff/reset/",   StaffForgotPasswordResetView.as_view(),   name="staff-forgot-password-reset"),
    path("forgot-password/patient/reset/", PatientForgotPasswordResetView.as_view(), name="patient-forgot-password-reset"),
    path("me/",               MeView.as_view(),              name="me"),
    path("me/permissions/",   PermissionsView.as_view(),     name="me-permissions"),
]
