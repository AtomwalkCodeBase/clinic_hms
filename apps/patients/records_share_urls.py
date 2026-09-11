"""
apps/patients/records_share_urls.py
-----------------------------------
Routed at /api/v1/records-share/ (see atomwalk/urls.py) — the PUBLIC,
token-gated half of "Share Records": the doctor's laptop (no account)
polling a session's status and, once the patient approves, reading the
records and asking to download a file. Its own top-level prefix, exempt
from JWTTenantMiddleware, same as /emergency/ and /consult-pad/.

The patient-authenticated half — create the session, approve / deny / end /
release-download / "who has access" — lives under
/api/v1/portal/records-share/ (see portal_urls.py).
"""

from django.urls import path

from .records_share_views import (
    RecordsShareClaimView,
    RecordsShareStatusView,
    RecordsShareRecordsView,
    RecordsShareDownloadView,
    RecordsShareDocumentViewView,
    RecordsShareCloseView,
)

urlpatterns = [
    # Must precede "<str:token>/" — the doctor's laptop binds itself here,
    # by the patient's 6-digit code (typed at /s) or by the link's token.
    path("claim/",                                  RecordsShareClaimView.as_view(),       name="records-share-claim"),
    path("<str:token>/records/",                    RecordsShareRecordsView.as_view(),     name="records-share-records"),
    path("<str:token>/documents/<int:doc_id>/view/", RecordsShareDocumentViewView.as_view(), name="records-share-doc-view"),
    path("<str:token>/downloads/",                  RecordsShareDownloadView.as_view(),    name="records-share-downloads"),
    path("<str:token>/close/",                      RecordsShareCloseView.as_view(),       name="records-share-close"),
    path("<str:token>/",                            RecordsShareStatusView.as_view(),      name="records-share-status"),
]
