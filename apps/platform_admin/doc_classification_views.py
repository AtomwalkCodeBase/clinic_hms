"""
apps/platform_admin/doc_classification_views.py
-----------------------------------------------
Platform-admin screens for the My Reports document classifier (internal —
never shown to patients or hospitals).

  GET    /api/v1/platform/doc-rules/          — every keyword rule
  POST   /api/v1/platform/doc-rules/          — create {doc_type, name, keywords, required_hits, is_active}
  PATCH  /api/v1/platform/doc-rules/<id>/     — edit any of those
  DELETE /api/v1/platform/doc-rules/<id>/
  POST   /api/v1/platform/doc-rules/test/     — {text} -> what the rules make of it
  GET    /api/v1/platform/doc-classification/report/
         — pipeline status counts and how often the rule / LLM verdicts
           agree with the human label (SharedDocument.human_doc_type).

`keywords` is pipe-separated ("reference range|mg/dl|haemoglobin"); a list
is accepted too. Saving a rule drops core.doc_rules' cache so the next
upload uses it — no code change or restart.
"""

from collections import Counter

from django.db.models import Q

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from core.permissions import IsPlatformAdmin
from core.response import created, error, not_found, success


def _clean_keywords(value):
    items = value if isinstance(value, list) else str(value or "").replace("\n", "|").split("|")
    seen, out = set(), []
    for k in items:
        k = str(k).strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return "|".join(out)


def _rule_dict(r):
    kws = r.keyword_list()
    return {
        "id": r.id, "doc_type": r.doc_type, "name": r.name,
        "keywords": kws, "keyword_count": len(kws),
        "required_hits": r.required_hits, "is_active": r.is_active,
        "updated_by": r.updated_by, "updated_at": r.updated_at.isoformat(),
    }


def _apply(rule, d, request):
    from apps.registry.models import DocumentClassificationRule
    if "doc_type" in d:
        if d["doc_type"] not in dict(DocumentClassificationRule.DOC_TYPE_CHOICES):
            return "Unknown document type."
        rule.doc_type = d["doc_type"]
    if "name" in d:
        rule.name = str(d["name"] or "").strip()[:80]
    if "keywords" in d:
        rule.keywords = _clean_keywords(d["keywords"])
    if "required_hits" in d:
        try:
            rule.required_hits = max(1, min(50, int(d["required_hits"])))
        except (TypeError, ValueError):
            return "required_hits must be a number."
    if "is_active" in d:
        rule.is_active = bool(d["is_active"])
    if not rule.name:
        return "Name is required."
    if not rule.keywords:
        return "Add at least one keyword."
    rule.updated_by = (getattr(request.user, "email", "") or str(request.user.id))[:120]
    return None


class DocRuleListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        from apps.registry.models import DocumentClassificationRule
        rows = DocumentClassificationRule.objects.using("default").all()
        return success(data={
            "rules": [_rule_dict(r) for r in rows],
            "doc_types": [{"value": v, "label": l} for v, l in DocumentClassificationRule.DOC_TYPE_CHOICES],
        })

    def post(self, request):
        from apps.registry.models import DocumentClassificationRule
        from core import doc_rules
        rule = DocumentClassificationRule(doc_type="", name="", keywords="", required_hits=5)
        d = dict(request.data)
        d.setdefault("doc_type", "")
        msg = _apply(rule, d, request)
        if msg:
            return error(msg)
        rule.save(using="default")
        doc_rules.invalidate()
        return created(data=_rule_dict(rule), message="Rule created.")


class DocRuleDetailView(APIView):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def patch(self, request, pk):
        from apps.registry.models import DocumentClassificationRule
        from core import doc_rules
        rule = DocumentClassificationRule.objects.using("default").filter(pk=pk).first()
        if not rule:
            return not_found("Rule not found.")
        msg = _apply(rule, request.data, request)
        if msg:
            return error(msg)
        rule.save(using="default")
        doc_rules.invalidate()
        return success(data=_rule_dict(rule), message="Rule saved.")

    def delete(self, request, pk):
        from apps.registry.models import DocumentClassificationRule
        from core import doc_rules
        n, _ = DocumentClassificationRule.objects.using("default").filter(pk=pk).delete()
        if not n:
            return not_found("Rule not found.")
        doc_rules.invalidate()
        return success(data={"id": pk, "deleted": True}, message="Rule deleted.")


class DocRuleTestView(APIView):
    """Run the live rules (and the keyword pass verdict) over pasted text."""
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def post(self, request):
        from core import doc_classifier, doc_rules
        text = str(request.data.get("text") or "")[:20000]
        if len(text.strip()) < 10:
            return error("Paste some document text to test.")
        doc_rules.invalidate()
        lower = " " + " ".join(text.lower().split()) + " "
        kind, conf = doc_classifier._classify_kind(lower)
        return success(data={
            "kind": kind, "confidence": round(conf, 2),
            "scores": doc_rules.score(lower),
        })


def _norm(t):
    # A rule/LLM "not_medical" and a person's "other" mean the same bucket.
    return "other" if t in ("not_medical", "unreadable") else t


class LLMStatusView(APIView):
    """GET /api/v1/platform/llm/status/ — which LLM server this install uses
    (LLM_MODE local | production), whether it answers, and the queue."""
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        from core import llm_client
        from core.pipeline.llm_queue import llm_queue_counts
        return success(data={**llm_client.status(), "queue": llm_queue_counts(),
                             "max_chars": llm_client.max_chars()})


class DocClassificationReportView(APIView):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        from apps.registry.models import SharedDocument

        base = SharedDocument.objects.using("default").filter(
            deleted_at__isnull=True, uploaded_by="patient",
        ).exclude(doc_type__in=SharedDocument.STAFF_ONLY_DOC_TYPES)

        processing = Counter(base.values_list("processing_status", flat=True))
        classification = Counter(base.values_list("classification_status", flat=True))
        # A thumbs-down removes the document, but its verdict still counts.
        labelled = SharedDocument.objects.using("default").filter(uploaded_by="patient").exclude(
            doc_type__in=SharedDocument.STAFF_ONLY_DOC_TYPES).filter(
            Q(deleted_at__isnull=True) | Q(human_action="rejected"))
        actions = Counter(labelled.exclude(human_action="").values_list("human_action", flat=True))

        rows = list(labelled.exclude(human_doc_type="").values(
            "id", "title", "rule_doc_type", "rule_confidence", "llm_doc_type",
            "llm_confidence", "human_doc_type", "human_action", "human_at",
        ))

        def pair(a, b):
            both = [r for r in rows if r[a] and r[b]]
            agree = sum(1 for r in both if _norm(r[a]) == _norm(r[b]))
            return {"compared": len(both), "agree": agree, "disagree": len(both) - agree,
                    "rate": round(agree / len(both), 3) if both else None}

        # Rule vs LLM is meaningful on every row both ran on, labelled or not.
        rl_rows = list(base.exclude(rule_doc_type="").exclude(llm_doc_type="")
                       .values_list("rule_doc_type", "llm_doc_type"))
        rl_agree = sum(1 for a, b in rl_rows if _norm(a) == _norm(b))

        # Confusion: human label -> what the rules said.
        confusion = {}
        for r in rows:
            if not r["rule_doc_type"]:
                continue
            h, p = _norm(r["human_doc_type"]), _norm(r["rule_doc_type"])
            confusion.setdefault(h, Counter())[p] += 1

        disagreements = sorted(
            (r for r in rows if (r["rule_doc_type"] and _norm(r["rule_doc_type"]) != _norm(r["human_doc_type"]))
             or (r["llm_doc_type"] and _norm(r["llm_doc_type"]) != _norm(r["human_doc_type"]))),
            key=lambda r: r["human_at"] or 0, reverse=True,
        )[:25]

        return success(data={
            "totals": {
                "documents": base.count(),
                "human_labelled": len(rows),
                "llm_ran": base.exclude(llm_doc_type="").count(),
            },
            "processing_status": dict(processing),
            "classification_status": dict(classification),
            "human_actions": dict(actions),
            "rule_vs_human": pair("rule_doc_type", "human_doc_type"),
            "llm_vs_human": pair("llm_doc_type", "human_doc_type"),
            "rule_vs_llm": {"compared": len(rl_rows), "agree": rl_agree,
                            "disagree": len(rl_rows) - rl_agree,
                            "rate": round(rl_agree / len(rl_rows), 3) if rl_rows else None},
            "confusion": {h: dict(c) for h, c in confusion.items()},
            "recent_disagreements": [{**r, "human_at": r["human_at"].isoformat() if r["human_at"] else None}
                                     for r in disagreements],
        })
