"""Platform Admin → the records report (apps.documents)."""
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.documents.models import MedicalDocument
from core.api.pagination import paginate_queryset
from core.api.permissions import IsPlatformAdmin
from core.api.response import error, not_found, success
from apps.documents import lib_documents as classification
from apps.documents import lib_documents as records
from apps.documents.models import CHOOSABLE_TYPES, HUMAN_CLASSIFIED, ISSUED, REVIEW_REQUIRED, RULE_CLASSIFIED


def _doc_row(d):
    return {"id": d.id, "title": records.display_name(d), "doc_type": d.doc_classification, "method": classification.method_of(d),
            "score": classification.score_of(d), "best_guess": classification.best_guess_of(d), "processing_status": d.status,
            "awpid": d.patient.awpid, "created_at": d.created_at}


class DocumentReportView(APIView):
    """Platform Admin → Records report: every document, newest first."""
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        qs = MedicalDocument.objects.select_related("patient", "d_classification").order_by("-created_at")
        method = request.query_params.get("method")
        if method == "staff":
            qs = qs.filter(d_classification__status__in=(HUMAN_CLASSIFIED, ISSUED))
        elif method == "rule":
            qs = qs.filter(d_classification__status__in=(RULE_CLASSIFIED, REVIEW_REQUIRED))
        if request.query_params.get("status"):
            qs = qs.filter(status=request.query_params["status"])
        page, meta = paginate_queryset(request, qs)
        return success(data={"results": [_doc_row(d) for d in page], "pagination": meta,
                              "doc_types": CHOOSABLE_TYPES})


class DocumentCorrectView(APIView):
    """PATCH {doc_type} — a person overriding a wrong rule verdict by hand. The report then shows method="staff":"""
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def patch(self, request, pk):
        doc = MedicalDocument.objects.filter(pk=pk).first()
        if not doc:
            return not_found("Document not found.")
        doc_type = request.data.get("doc_type")
        if doc_type not in CHOOSABLE_TYPES:
            return error("doc_type must be one of the known document types.")
        try:
            records.correct_document(doc, doc_type)
        except ValueError as exc:
            return error(str(exc))
        return success(data=_doc_row(MedicalDocument.objects.get(pk=doc.pk)))


class ReclassifyView(APIView):
    """POST — run today's rules again over the documents the rules classified (never a person's choice), using the"""
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def post(self, request):
        return success(data=records.reclassify_existing())
