"""
core/pipeline/filing.py — turn a classifier verdict into database fields.

  verdict_fields(cr)  what the keyword rules said   → rule_doc_type, rule_confidence, rule_scores
  filing_fields(cr)   where the document goes       → doc_type, review_state,
                                                      review_needs (what the patient must confirm)
  save(doc, **f)      write only those fields

Used by processing.py (after the rules) and llm_queue.py (after the LLM).
"""


def save(doc, **fields) -> None:
    for k, v in fields.items():
        setattr(doc, k, v)
    doc.save(using="default", update_fields=list(fields))


def verdict_fields(cr) -> dict:
    return {
        "rule_doc_type": cr.rule_kind or ("unreadable" if cr.unreadable else ""),
        "rule_confidence": cr.rule_conf if cr.rule_kind else None,
        "rule_scores": cr.rule_scores or {},
    }


def filing_fields(cr) -> dict:
    """
    Four outcomes:
      unreadable page      → "Other", waits for the patient (retake / fill in)
      clearly not medical  → "Other", waits for the patient (keep or remove)
      confident type       → filed under that type (still asks for a missing panel/date)
      unsure               → "Other", waits for the patient to pick the type
    Nothing is ever dropped: a person always gets the last word.
    """
    f = {
        "classification_method": cr.method,
        "classification_confidence": cr.confidence,
        "document_date": cr.doc_date,
        "collection_date": cr.collection_date,
        "date_source": cr.date_source or "",
        "report_categories": [],
        "category_method": "",
        "category_confidence": None,
        "review_notes": "",
    }
    if cr.unreadable:
        f.update(doc_type="other", review_state="unsorted", verification_status="needs_review",
                 review_needs=["file"], review_notes=cr.quality_message or "")
    elif cr.non_medical:
        f.update(doc_type="other", review_state="unsorted", verification_status="needs_review",
                 review_needs=["kind"],
                 review_notes="This doesn't look like a medical document. "
                              "Pick its type if it is one, or remove it.")
    elif cr.confident:
        f.update(doc_type=cr.doc_type,
                 review_state="filed" if not cr.needs else "unsorted",
                 verification_status="unverified" if not cr.needs else "needs_review",
                 review_needs=list(cr.needs))
        if cr.doc_type == "lab_report":
            f.update(report_categories=list(cr.categories),
                     category_confidence=cr.category_confidence,
                     category_method="keyword" if cr.method == "ocr_keyword" else cr.method)
    else:
        f.update(doc_type="other", review_state="unsorted", verification_status="needs_review",
                 review_needs=list(cr.needs) or ["kind"])
    return f


def describe(fields) -> str:
    """For the log: 'as lab_report · ready for the patient's check'."""
    where = fields.get("doc_type", "?")
    if fields.get("review_state") == "filed":
        return f"as {where} · ready for the patient's check"
    needs = ", ".join(fields.get("review_needs") or []) or "type"
    return f"as {where} · the patient must confirm: {needs}"
