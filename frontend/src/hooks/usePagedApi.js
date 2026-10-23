/** hooks/usePagedApi.js
 *  A list the server pages (`?page=&page_size=` -> { results, pagination }): the page number and size live here, the list goes back to
 *  page 1 when the filters change, and the result plugs straight into <PaginationControls/>.
 *  `useClientPaging` does the same for a list that is already in the browser.
 */
import { useEffect, useMemo, useState } from "react";
import { useApi } from "./useApi";

export function usePagedApi(url, { params = {}, pageSize: initialSize = 10, pollMs = 0, skip = false } = {}) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(initialSize);
  const filterKey = JSON.stringify(params);

  useEffect(() => { setPage(1); }, [filterKey, pageSize]);

  const { data, isLoading, error, refetch } = useApi(url, { params: { ...params, page, page_size: pageSize }, pollMs, skip });
  const items = Array.isArray(data) ? data : (data?.results || []);
  return { data, items, pagination: data?.pagination || null, page, setPage, pageSize, setPageSize, isLoading, error, refetch };
}

export function useClientPaging(items, initialSize = 10) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(initialSize);
  const total = items?.length || 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const current = Math.min(page, totalPages);

  useEffect(() => { setPage(1); }, [total, pageSize]);

  const pageItems = useMemo(() => (items || []).slice((current - 1) * pageSize, current * pageSize), [items, current, pageSize]);
  const pagination = { page: current, page_size: pageSize, total_count: total, total_pages: totalPages, has_next: current < totalPages, has_previous: current > 1 };
  return { pageItems, pagination, page: current, setPage, pageSize, setPageSize };
}
