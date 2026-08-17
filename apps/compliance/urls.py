"""
apps/compliance/urls.py
-------------------------
Mounted at /api/v1/compliance/ (see atomwalk/urls.py).
"""

from django.urls import path

from .views import (
    AuditLogListView,
    RecordAmendmentStaffListView,
    RecordAmendmentResolveView,
    ConsentRecordListView,
    PortalRecordAmendmentView,
)

urlpatterns = [
    path("audit-log/",                AuditLogListView.as_view(),          name="compliance-audit-log"),
    path("amendments/",               RecordAmendmentStaffListView.as_view(), name="compliance-amendments"),
    path("amendments/<int:pk>/resolve/", RecordAmendmentResolveView.as_view(), name="compliance-amendment-resolve"),
    path("consents/",                 ConsentRecordListView.as_view(),     name="compliance-consents"),
    path("portal/amendments/",        PortalRecordAmendmentView.as_view(), name="compliance-portal-amendments"),
]
