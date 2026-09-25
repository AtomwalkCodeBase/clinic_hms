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
 *   pollMs   — re-fetches on this interval so this view stays live without
 *              the user hitting refresh (e.g. a second patient's slot list
 *              updating the moment someone else books). Defaults to
 *              DEFAULT_POLL_MS so every screen auto-updates out of the box;
 *              pass 0 to disable — do that ONLY when the fetched `data` is
 *              mirrored into local editable state (e.g. a draft/consult
 *              form seeded from the server via a `[data]`-keyed effect),
 *              since a background poll would silently overwrite in-progress
 *              edits. Background polls don't flip isLoading (no spinner
 *              flash) — only the very first load does. Polling pauses while
 *              the tab is hidden/backgrounded and resumes (with an
 *              immediate refetch) when it becomes visible again, so we're
 *              not hammering the API from a dozen forgotten background tabs.
 *
 * A failed fetch that looks transient (network drop, timeout, a 5xx —
 * anything that plausibly resolves on its own, e.g. a backend mid-deploy)
 * is silently retried in the background every RETRY_DELAY_MS until it
 * succeeds or the component unmounts — no visible "retrying…" state, no
 * countdown, the page just quietly gets its data the moment the backend
 * is reachable again instead of making the user hit refresh. A real 4xx
 * (permission denied, not found, validation error) is left alone —
 * retrying a request that can never succeed would just spin forever.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import apiClient from "../services/api.client";

const RETRY_DELAY_MS = 5000;
const DEFAULT_POLL_MS = 30000;

function isRetryableError(err) {
  // No HTTP status at all means the request never reached a server
  // (network drop, timeout, CORS, DNS) — always worth another try.
  return err?.status == null || err.status >= 500;
}

export function useApi(url, { params = {}, skip = false, onSuccess, pollMs = DEFAULT_POLL_MS } = {}) {
  const [data,      setData]      = useState(null);
  const [isLoading, setIsLoading] = useState(!skip);
  const [error,     setError]     = useState(null);

  // Stringify params so the effect only re-runs when params actually change
  const paramsKey = JSON.stringify(params);
  const isMounted = useRef(true);
  const retryTimer = useRef(null);

  const fetch = useCallback(async (opts = {}) => {
    if (!url || skip) return;
    const { silent = false } = opts;
    if (retryTimer.current) { clearTimeout(retryTimer.current); retryTimer.current = null; }
    if (!silent) setIsLoading(true);
    try {
      const { data: responseData } = await apiClient.get(url, { params });
      if (isMounted.current) {
        // Backend has two response shapes:
        //   1. core.response wrapper: { success, message, data: {...} }
        //   2. plain DRF Response:    { results: [...], count } or raw payload
        const payload = responseData?.data !== undefined ? responseData.data : responseData;
        setData(payload);
        setError(null);
        onSuccess?.(payload);
      }
    } catch (err) {
      if (isMounted.current) {
        setError(err);
        if (isRetryableError(err)) {
          retryTimer.current = setTimeout(() => fetch({ silent: true }), RETRY_DELAY_MS);
        }
      }
    } finally {
      if (isMounted.current && !silent) setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, paramsKey, skip]);

  useEffect(() => {
    isMounted.current = true;
    fetch();
    return () => {
      isMounted.current = false;
      if (retryTimer.current) clearTimeout(retryTimer.current);
    };
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
