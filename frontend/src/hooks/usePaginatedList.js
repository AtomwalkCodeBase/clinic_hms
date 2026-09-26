/**
 * hooks/usePaginatedList.js
 * --------------------------
 * Data-fetching hook for endpoints that return { results: [...], pagination: {...} }
 * (see core/pagination.py paginate_queryset / paginate_list on the backend).
 *
 * Unlike useApi, this accumulates pages via loadMore() instead of replacing
 * the list on every param change — suited to "Load more" style list views
 * where the caller may also apply client-side filtering over the accumulated
 * items (e.g. the patient portal's Records/Prescriptions/Lab pages, which all
 * derive their view from the same underlying paginated record list).
 *
 * Usage:
 *   const { items, isLoading, isLoadingMore, hasMore, loadMore, refetch } =
 *     usePaginatedList(API_ENDPOINTS.PORTAL.MY_RECORDS, { pageSize: 20 });
 *
 * Options:
 *   pollMs — if set, silently re-fetches page 1 on this interval to keep
 *            the list live (e.g. a new booking/prescription appearing
 *            without a manual refresh). Skipped while the user has loaded
 *            additional pages (page > 1), so a background tick never
 *            discards "Load more" progress, and paused while the tab is
 *            hidden.
 */

import { useState, useEffect, useCallback } from "react";
import apiClient from "../services/api.client";

export function usePaginatedList(url, { pageSize = 20, params = {}, pollMs = 0 } = {}) {
  const [items,         setItems]         = useState([]);
  const [page,          setPage]          = useState(1);
  const [pagination,    setPagination]    = useState(null);
  const [isLoading,     setIsLoading]     = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [error,         setError]         = useState(null);

  const paramsKey = JSON.stringify(params);

  const fetchPage = useCallback(async (targetPage, append, opts = {}) => {
    if (!url) return;
    const { silent = false } = opts;
    if (!silent) {
      if (append) setIsLoadingMore(true); else setIsLoading(true);
      setError(null);
    }
    try {
      const { data: responseData } = await apiClient.get(url, {
        params: { ...params, page: targetPage, page_size: pageSize },
      });
      const payload = responseData?.data !== undefined ? responseData.data : responseData;
      const newItems = payload?.results || [];
      setPagination(payload?.pagination || null);
      setItems(prev => (append ? [...prev, ...newItems] : newItems));
      setPage(targetPage);
    } catch (err) {
      if (!silent) {
        setError(err);
        if (!append) setItems([]);
      }
    } finally {
      if (!silent) {
        if (append) setIsLoadingMore(false); else setIsLoading(false);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, paramsKey, pageSize]);

  useEffect(() => {
    fetchPage(1, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, paramsKey]);

  useEffect(() => {
    if (!pollMs || !url) return undefined;
    const tick = () => {
      if (document.hidden) return;
      if (page > 1) return; // don't clobber "Load more" progress
      fetchPage(1, false, { silent: true });
    };
    const id = setInterval(tick, pollMs);
    const onVisible = () => { if (!document.hidden && page === 1) fetchPage(1, false, { silent: true }); };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [pollMs, url, page, fetchPage]);

  const loadMore = useCallback(() => {
    if (pagination?.has_next && !isLoadingMore) fetchPage(page + 1, true);
  }, [fetchPage, page, pagination, isLoadingMore]);

  const refetch = useCallback(() => fetchPage(1, false), [fetchPage]);

  return { items, isLoading, isLoadingMore, hasMore: !!pagination?.has_next, pagination, error, loadMore, refetch };
}

export default usePaginatedList;
