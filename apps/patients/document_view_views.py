"""
apps/patients/document_view_views.py
-------------------------------------
The public webpage a printed prescription/lab-report QR opens when it's
scanned by anything other than the patient app itself — Google Lens, any
other camera app, a second phone. The app's own capture flow never hits this
endpoint: it decodes the same QR with expo-camera and posts the raw string
straight to the "My Reports pipeline" in portal_views.py, which auto-files it.

No login here — whoever has the printout can view the document, same trust
model as a paper copy. GET returns only doc_type/title (for the confirm
prompt copy); the file itself is resolved to a signed URL only from
GET-with-confirm, i.e. the frontend calls this endpoint just once, after the
patient has already clicked "Yes" on the view-report page — nothing is
fetched or logged before that click.
"""
import logging

from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle

from core.response import success, error
from core import qr_token as _qt
from core import storage as blob_storage

logger = logging.getLogger(__name__)


class DocumentViewView(APIView):
    """
    GET /api/v1/view-report/<token>/

    Verifies the signed token (bare, or the "/view-report/<token>" shape a
    generic scanner hands back unchanged), resolves the SharedDocument it
    points to, and returns a signed file URL. Any invalid/malformed/unknown
    token returns a patient-safe 400/404 — this is reachable by anyone with a
    camera, never a stack trace.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "view_report"

    def get(self, request, token):
        v = _qt.verify(token)
        if not v.ok or not v.awpid or not v.public_document_id:
            return error(message="This code is invalid.", status=400)

        from apps.registry.models import SharedDocument

        doc = (
            SharedDocument.objects.using("default")
            .filter(
                awpid=v.awpid,
                public_document_id=v.public_document_id,
                doc_type=v.doc_type,
                deleted_at__isnull=True,
            )
            .order_by("-created_at")
            .first()
        )
        if not doc:
            return error(message="This document could not be found.", status=404)

        try:
            file_url = blob_storage.signed_url(doc.file_data, download_name=doc.file_name or None)
        except Exception:
            logger.exception("view-report: signed_url failed for SharedDocument id=%s", doc.id)
            return error(message="This document could not be opened right now. Please try again.", status=500)

        return success(data={
            "doc_type": doc.doc_type,
            "title": doc.title,
            "document_date": doc.document_date,
            "file_url": file_url,
        })
