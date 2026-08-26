/**
 * hooks/useApi.js
 * ---------------
 * Generic data-fetching hook that wraps apiClient calls.
 *
 * Usage:
 *   const { data, isLoading, error, refetch } = useApi(API_ENDPOINTS.ORG.BRANCHES);
 *
 * For POST/PATCH calls use apiClient directly in a service file,
 * then call refetch() to update the list.
 *
 * Options:
 *   params   — query params object (appended as ?key=value)
 *   skip     — if true, do not fetch (useful for conditional fetching)
 *   onSuccess — callback(data) called after a successful fetch
 *   pollMs   — if set, silently re-fetches on this interval so this view
 *              stays live without the user hitting refresh (e.g. a second
 *              patient's slot list updating the moment someone else books).
 *              Background polls don't flip isLoading (no spinner flash) —
 *              only the very first load does. Polling pauses while the tab
 *              is hidden/backgrounded and resumes (with an immediate
 *              refetch) when it becomes visible again, so we're not
 *              hammering the API from a dozen forgotten background tabs.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import apiClient from "../services/api.client";

export function useApi(url, { params = {}, skip = false, onSuccess, pollMs = 0 } = {}) {
  const [data,      setData]      = useState(null);
  const [isLoading, setIsLoading] = useState(!skip);
  const [error,     setError]     = useState(null);

  // Stringify params so the effect only re-runs when params actually change
  const paramsKey = JSON.stringify(params);
  const isMounted = useRef(true);

  const fetch = useCallback(async (opts = {}) => {
    if (!url || skip) return;
    const { silent = false } = opts;
    if (!silent) setIsLoading(true);
    setError(null);
    try {
      const { data: responseData } = await apiClient.get(url, { params });
      if (isMounted.current) {
        // Backend has two response shapes:
        //   1. core.response wrapper: { success, message, data: {...} }
        //   2. plain DRF Response:    { results: [...], count } or raw payload
        const payload = responseData?.data !== undefined ? responseData.data : responseData;
        setData(payload);
        onSuccess?.(payload);
      }
    } catch (err) {
      if (isMounted.current) setError(err);
    } finally {
      if (isMounted.current && !silent) setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, paramsKey, skip]);

  useEffect(() => {
    isMounted.current = true;
    fetch();
    return () => { isMounted.current = false; };
  }, [fetch]);

  // Background polling — separate effect so a poll tick never touches
  // isLoading/error the way the initial fetch does.
  useEffect(() => {
    if (!pollMs || !url || skip) return undefined;
    const tick = () => {
      if (document.hidden) return;
      fetch({ silent: true });
    };
    const id = setInterval(tick, pollMs);
    const onVisible = () => { if (!document.hidden) fetch({ silent: true }); };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [pollMs, url, skip, fetch]);

  return { data, isLoading, error, refetch: fetch };
}

export default useApi;
