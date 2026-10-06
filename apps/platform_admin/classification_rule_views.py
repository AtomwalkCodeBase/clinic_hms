"""
Platform Admin → the records report (apps.records).

  GET    /api/v1/platform/records/report/            MedicalDocument rows: type, who classified, score, status
  PATCH  /api/v1/platform/records/report/<id>/       a person overwrites one document's type
  POST   /api/v1/platform/records/reclassify/        run the rules again over the documents they classified

The document types and their keywords are not editable here: they are fixed in code (apps/records/classification.py),
so changing one is a code change, not a screen.
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.records import classification as rules
from apps.records import services
from apps.records.models import MedicalDocument
from core.pagination import paginate_queryset
from core.permissions import IsPlatformAdmin
from core.response import error, not_found, success


def _doc_row(d):
    return {"id": d.id, "title": d.file_name, "doc_type": d.document_type, "method": rules.method_of(d),
            "score": rules.score_of(d), "best_guess": rules.best_guess_of(d), "processing_status": d.processing_status,
            "awpid": d.patient.awpid, "created_at": d.created_at}


class DocumentReportView(APIView):
    """Platform Admin → Records report: every document, newest first.
    ?method=rule|staff  ?status=<processing_status>  ?page=  ?page_size="""
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        qs = MedicalDocument.objects.select_related("patient", "classification").order_by("-created_at")
        method = request.query_params.get("method")
        if method == "staff":
            qs = qs.filter(classification__status__in=(rules.HUMAN_CLASSIFIED, rules.ISSUED))
        elif method == "rule":
            qs = qs.filter(classification__status__in=(rules.RULE_CLASSIFIED, rules.REVIEW_REQUIRED))
        if request.query_params.get("status"):
            qs = qs.filter(status=request.query_params["status"])
        page, meta = paginate_queryset(request, qs)
        return success(data={"results": [_doc_row(d) for d in page], "pagination": meta,
                              "doc_types": rules.CHOOSABLE_TYPES})


class DocumentCorrectView(APIView):
    """PATCH {doc_type} — a person overriding a wrong rule verdict by hand. The report then shows method="staff":
    this row is now a human choice, not an automatic one. Works on a failed document too: the file is still there,
    so it becomes a normal completed document."""
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def patch(self, request, pk):
        doc = MedicalDocument.objects.filter(pk=pk).first()
        if not doc:
            return not_found("Document not found.")
        doc_type = request.data.get("doc_type")
        if doc_type not in rules.CHOOSABLE_TYPES:
            return error("doc_type must be one of the known document types.")
        try:
            services.correct_document(doc, doc_type)
        except ValueError as exc:
            return error(str(exc))
        return success(data=_doc_row(MedicalDocument.objects.get(pk=doc.pk)))


class ReclassifyView(APIView):
    """POST — run today's rules again over the documents the rules classified (never a person's choice), using the
    text already read, no OCR. For after a keyword in classification.py was edited."""
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def post(self, request):
        return success(data=services.reclassify_existing())
