"""
Platform Admin → Classification rules (apps.records.ClassificationRule).

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
  GET       /api/v1/platform/records/report/            SharedDocument rows: type, method, score, status
  PATCH     /api/v1/platform/records/report/<id>/        human-correct a document's type
"""
import re

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.records.models import ClassificationRule, SharedDocument, SweepConfig
from core.pagination import paginate_queryset
from core.permissions import IsPlatformAdmin
from core.response import created, error, not_found, success


def _row(r):
    return {"id": r.id, "doc_type": r.doc_type, "keywords": r.keywords,
            "is_active": r.is_active, "updated_at": r.updated_at}


def _apply(rule, data):
    """Copy + clean the request fields onto `rule`. Returns an error message or None."""
    if "doc_type" in data:
        doc_type = re.sub(r"[^a-z0-9_]+", "_", str(data["doc_type"] or "").strip().lower()).strip("_")[:30]
        if not doc_type:
            return "Document type is required, e.g. lab_report."
        if ClassificationRule.objects.filter(doc_type=doc_type).exclude(pk=rule.pk).exists():
            return f"There is already a rule for {doc_type}."
        rule.doc_type = doc_type
    if "keywords" in data:
        words = [w.strip().lower() for w in str(data["keywords"] or "").split("|") if w.strip()]
        if not words:
            return "Add at least one keyword (pipe-separated)."
        rule.keywords = "|".join(dict.fromkeys(words))
    if "is_active" in data:
        rule.is_active = bool(data["is_active"])
    return None


class ClassificationRuleListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        return success(data=[_row(r) for r in ClassificationRule.objects.all()])

    def post(self, request):
        rule = ClassificationRule()
        msg = _apply(rule, {"doc_type": "", "keywords": "", **request.data})
        if msg:
            return error(msg)
        rule.save()
        return created(data=_row(rule))


class ClassificationRuleDetailView(APIView):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def patch(self, request, pk):
        rule = ClassificationRule.objects.filter(pk=pk).first()
        if not rule:
            return not_found("Rule not found.")
        msg = _apply(rule, request.data)
        if msg:
            return error(msg)
        rule.save()
        return success(data=_row(rule))

    def delete(self, request, pk):
        deleted, _ = ClassificationRule.objects.filter(pk=pk).delete()
        return success(data={"deleted": bool(deleted)}) if deleted else not_found("Rule not found.")


def _sweep_row(c):
    return {"instant_max_files": c.instant_max_files, "sweep_dispatch_limit": c.sweep_dispatch_limit,
            "sweep_interval_seconds": c.sweep_interval_seconds}


class SweepConfigView(APIView):
    """Platform Admin → Records settings: all three sweep settings, live (no restart) — saving
    also updates the actual Celery Beat schedule (see SweepConfig.save())."""
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        return success(data=_sweep_row(SweepConfig.current()))

    def patch(self, request):
        c = SweepConfig.current()
        for field in ("instant_max_files", "sweep_dispatch_limit", "sweep_interval_seconds"):
            if field not in request.data:
                continue
            try:
                value = int(request.data[field])
            except (TypeError, ValueError):
                return error(f"{field} must be a whole number.")
            if value < 1:
                return error(f"{field} must be at least 1.")
            setattr(c, field, value)
        c.save()
        return success(data=_sweep_row(c))


def _doc_row(d):
    return {"id": d.id, "title": d.title, "doc_type": d.doc_type, "method": d.method, "score": d.score,
            "processing_status": d.processing_status, "awpid": d.awpid, "created_at": d.created_at}


class DocumentReportView(APIView):
    """Platform Admin → Records report: every document, newest first.
    ?method=rule|llm|staff  ?status=<processing_status>  ?page=  ?page_size="""
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        qs = SharedDocument.objects.filter(deleted_at__isnull=True).order_by("-created_at")
        if request.query_params.get("method"):
            qs = qs.filter(method=request.query_params["method"])
        if request.query_params.get("status"):
            qs = qs.filter(processing_status=request.query_params["status"])
        page, meta = paginate_queryset(request, qs)
        return success(data={"results": [_doc_row(d) for d in page], "pagination": meta,
                              "doc_types": [c[0] for c in SharedDocument.DOC_TYPE_CHOICES]})


class DocumentCorrectView(APIView):
    """PATCH {doc_type} — a person overriding a wrong rule/LLM verdict by hand. Sets method="staff"
    so the report shows this row is now a human correction, not an automatic one."""
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def patch(self, request, pk):
        doc = SharedDocument.objects.filter(pk=pk).first()
        if not doc:
            return not_found("Document not found.")
        doc_type = request.data.get("doc_type")
        if doc_type not in dict(SharedDocument.DOC_TYPE_CHOICES):
            return error("doc_type must be one of the known document types.")
        doc.doc_type, doc.method = doc_type, "staff"
        doc.save(update_fields=["doc_type", "method", "updated_at"])
        return success(data=_doc_row(doc))
