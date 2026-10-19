/** hooks/useApi.js */

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
