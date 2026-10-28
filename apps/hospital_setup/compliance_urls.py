"""apps/hospital_setup/compliance_urls.py"""

from django.urls import path
from core.api.permissions import in_module

from apps.hospital_setup.compliance_views import (
    AuditLogListView,
    RecordAmendmentStaffListView,
    RecordAmendmentResolveView,
    PortalRecordAmendmentView,
)

urlpatterns = [
    path("audit-log/",                in_module(AuditLogListView, "compliance").as_view(),          name="compliance-audit-log"),
    path("amendments/",               in_module(RecordAmendmentStaffListView, "compliance").as_view(), name="compliance-amendments"),
    path("amendments/<int:pk>/resolve/", in_module(RecordAmendmentResolveView, "compliance").as_view(), name="compliance-amendment-resolve"),
    path("portal/amendments/",        PortalRecordAmendmentView.as_view(), name="compliance-portal-amendments"),
]
