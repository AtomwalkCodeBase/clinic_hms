"""
Platform Admin → Document types and their keywords (apps.records.DocumentClassification).

  GET    /api/v1/platform/classification-rules/        every rule
  POST   /api/v1/platform/classification-rules/        {doc_type, keywords, is_active}
  PATCH  /api/v1/platform/classification-rules/<id>/   any of those
  DELETE /api/v1/platform/classification-rules/<id>/

keywords are pipe-separated ("laboratory|hemoglobin|glucose"). The records
pipeline reads the rules fresh for every document, so a change applies to the
next upload — no restart.

Also here: the records periodic-sweep settings and the classification results report — same
Platform Admin surface, same pipeline (apps.records).

  GET/PATCH /api/v1/platform/records/sweep-config/      SweepConfig (instant_max_files, sweep_dispatch_limit)
  GET       /api/v1/platform/records/report/            MedicalDocument rows: type, who classified, confidence, status
  PATCH     /api/v1/platform/records/report/<id>/        a person overwrites one document's type
"""
import re

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.records import services
from apps.records.models import DocumentClassification, MedicalDocument, SweepConfig
from apps.records.scoring import parse_keywords
from core.pagination import paginate_queryset
from core.permissions import IsPlatformAdmin
from core.response import created, error, not_found, success


def _row(r):
    return {"id": r.id, "doc_type": r.code, "keywords": r.keywords,
            "is_active": r.is_active, "updated_at": r.updated_at}


def _apply(rule, data):
    """Copy + clean the request fields onto `rule`. Returns an error message or None."""
    if "doc_type" in data:
        code = re.sub(r"[^a-z0-9_]+", "_", str(data["doc_type"] or "").strip().lower()).strip("_")[:30]
        if not code:
            return "Document type is required, e.g. lab_report."
        if DocumentClassification.objects.filter(code=code).exclude(pk=rule.pk).exists():
            return f"There is already a rule for {code}."
        rule.code = code
        rule.name = rule.name or code.replace("_", " ").capitalize()
    if "keywords" in data:
        words = [w.strip().lower() for w in str(data["keywords"] or "").split("|") if w.strip()]
        if not parse_keywords("|".join(words))[0]:
            return "Add at least one keyword (pipe-separated); -word and word^3 are allowed on top of that."
        rule.keywords = "|".join(dict.fromkeys(words))
    if "is_active" in data:
        rule.is_active = bool(data["is_active"])
    return None


class ClassificationRuleListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        return success(data=[_row(r) for r in DocumentClassification.objects.all()])

    def post(self, request):
        rule = DocumentClassification()
        msg = _apply(rule, {"doc_type": "", "keywords": "", **request.data})
        if msg:
            return error(msg)
        rule.save()
        return created(data=_row(rule))


class ClassificationRuleDetailView(APIView):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def patch(self, request, pk):
        rule = DocumentClassification.objects.filter(pk=pk).first()
        if not rule:
            return not_found("Rule not found.")
        msg = _apply(rule, request.data)
        if msg:
            return error(msg)
        rule.save()
        return success(data=_row(rule))

    def delete(self, request, pk):
        deleted, _ = DocumentClassification.objects.filter(pk=pk).delete()
        return success(data={"deleted": bool(deleted)}) if deleted else not_found("Rule not found.")


_SETTINGS_LIMITS = {          # field → (lowest, highest) a Platform Admin may set
    "instant_max_files": (1, None), "sweep_dispatch_limit": (1, None), "sweep_interval_seconds": (1, None),
    "min_confidence": (1, 100), "evidence_scale": (1, 100),
}


def _sweep_row(c):
    return {field: getattr(c, field) for field in _SETTINGS_LIMITS}


class SweepConfigView(APIView):
    """Platform Admin → Records settings: the sweep settings and how a verdict is judged (the confidence a type
    needs, the evidence scale), live (no restart) — saving also updates the actual Celery Beat schedule."""
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        return success(data=_sweep_row(SweepConfig.current()))

    def patch(self, request):
        c = SweepConfig.current()
        for field, (low, high) in _SETTINGS_LIMITS.items():
            if field not in request.data:
                continue
            try:
                value = int(request.data[field])
            except (TypeError, ValueError):
                return error(f"{field} must be a whole number.")
            if value < low or (high and value > high):
                return error(f"{field} must be between {low} and {high}." if high else f"{field} must be at least {low}.")
            setattr(c, field, value)
        c.save()
        return success(data=_sweep_row(c))


def _doc_row(d):
    return {"id": d.id, "title": d.title, "doc_type": d.doc_type, "method": d.method, "score": d.score,
            "best_guess": d.best_guess, "processing_status": d.processing_status, "awpid": d.awpid_id, "created_at": d.created_at}


class DocumentReportView(APIView):
    """Platform Admin → Records report: every document, newest first.
    ?method=rule|staff  ?status=<processing_status>  ?page=  ?page_size="""
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        qs = MedicalDocument.objects.filter(deleted_at__isnull=True, hidden_at__isnull=True).order_by("-created_at")
        by = {"staff": "human", "rule": "system"}.get(request.query_params.get("method"))
        if by:
            qs = qs.filter(classification_source=by)
        if request.query_params.get("status"):
            qs = qs.filter(status=request.query_params["status"])
        page, meta = paginate_queryset(request, qs)
        return success(data={"results": [_doc_row(d) for d in page], "pagination": meta,
                              "doc_types": [c.code for c in DocumentClassification.configured()]})


class DocumentCorrectView(APIView):
    """PATCH {doc_type} — a person overriding a wrong rule verdict by hand. Sets method="staff"
    so the report shows this row is now a human correction, not an automatic one. Works on a failed
    document too: the file is still there, so it becomes a normal completed document."""
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def patch(self, request, pk):
        doc = MedicalDocument.objects.filter(pk=pk).first()
        if not doc:
            return not_found("Document not found.")
        doc_type = request.data.get("doc_type")
        if doc_type not in [c.code for c in DocumentClassification.configured()]:
            return error("doc_type must be one of the known document types.")
        try:
            services.correct_document(doc, doc_type)
        except ValueError as exc:
            return error(str(exc))
        return success(data=_doc_row(MedicalDocument.objects.get(pk=doc.pk)))


class ReclassifyView(APIView):
    """POST — run today's rules again over the documents the rules classified (never a person's verdict), using
    the text already read, no OCR. For after the keywords or the settings were tuned."""
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def post(self, request):
        return success(data=services.reclassify_existing())
