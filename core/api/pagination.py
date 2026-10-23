"""core/api/pagination.py"""

import math

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def _parse_page_params(request, default_page_size=DEFAULT_PAGE_SIZE, max_page_size=MAX_PAGE_SIZE):
    try:
        page = int(request.query_params.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    page = max(page, 1)

    try:
        page_size = int(request.query_params.get("page_size", default_page_size))
    except (TypeError, ValueError):
        page_size = default_page_size
    page_size = max(1, min(page_size, max_page_size))

    return page, page_size


def _build_meta(page, page_size, total_count):
    total_pages = max(1, math.ceil(total_count / page_size)) if total_count else 1
    page = min(page, total_pages)
    return page, {
        "page": page,
        "page_size": page_size,
        "total_count": total_count,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_previous": page > 1,
    }


def paginate_queryset(request, queryset, default_page_size=DEFAULT_PAGE_SIZE, max_page_size=MAX_PAGE_SIZE):
    """Slice an (unsliced) Django QuerySet according to ?page=&page_size=."""
    page, page_size = _parse_page_params(request, default_page_size, max_page_size)
    total_count = queryset.count()
    page, meta = _build_meta(page, page_size, total_count)
    start = (page - 1) * page_size
    end = start + page_size
    return queryset[start:end], meta


def page_payload(request, source, serialize=list, **kw):
    """One page with its pagination block when the caller asked for ?page=, else None, so a list that used to come back whole still does for
    every caller that does not ask. `source` is a QuerySet or a list; `serialize` turns the page's items into JSON-ready rows."""
    if "page" not in request.query_params:
        return None
    paginate = paginate_list if isinstance(source, (list, tuple)) else paginate_queryset
    items, meta = paginate(request, source, **kw)
    return {"results": serialize(items), "pagination": meta}


def paginate_list(request, items, default_page_size=DEFAULT_PAGE_SIZE, max_page_size=MAX_PAGE_SIZE):
    """Slice an already-materialized Python list (e.g. aggregated across"""
    page, page_size = _parse_page_params(request, default_page_size, max_page_size)
    total_count = len(items)
    page, meta = _build_meta(page, page_size, total_count)
    start = (page - 1) * page_size
    end = start + page_size
    return items[start:end], meta
