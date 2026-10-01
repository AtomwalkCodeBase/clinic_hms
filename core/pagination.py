"""
core/pagination.py
------------------
Pagination helpers for Atomwalk HMS.

The views in this codebase are plain APIView subclasses that return the shared
`success(data=...)` envelope (see core/response.py) rather than DRF generic views, so DRF's
pagination classes never run (the old StandardResultsPagination/LargeResultsPagination were
removed as dead code). List endpoints use `paginate_queryset` / `paginate_list`, which read
?page=&page_size= from the request, slice the data, and return a `meta` dict
that should be embedded in the response alongside the page's items, e.g.:

    page_items, meta = paginate_queryset(request, qs)
    return success(data={
        "results": MySerializer(page_items, many=True).data,
        "pagination": meta,
    })
"""

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
    """
    Slice an (unsliced) Django QuerySet according to ?page=&page_size=.

    Returns:
        (page_items, meta) — page_items is the sliced queryset for this page,
        meta is a dict: {page, page_size, total_count, total_pages, has_next, has_previous}.
    """
    page, page_size = _parse_page_params(request, default_page_size, max_page_size)
    total_count = queryset.count()
    page, meta = _build_meta(page, page_size, total_count)
    start = (page - 1) * page_size
    end = start + page_size
    return queryset[start:end], meta


def paginate_list(request, items, default_page_size=DEFAULT_PAGE_SIZE, max_page_size=MAX_PAGE_SIZE):
    """
    Slice an already-materialized Python list (e.g. aggregated across
    multiple tenant databases) according to ?page=&page_size=.

    Returns:
        (page_items, meta) — same shape as paginate_queryset.
    """
    page, page_size = _parse_page_params(request, default_page_size, max_page_size)
    total_count = len(items)
    page, meta = _build_meta(page, page_size, total_count)
    start = (page - 1) * page_size
    end = start + page_size
    return items[start:end], meta
