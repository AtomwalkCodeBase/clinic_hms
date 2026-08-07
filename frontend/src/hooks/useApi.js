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
 */

import { useState, useEffect, useCallback, useRef } from "react";
import apiClient from "../services/api.client";

export function useApi(url, { params = {}, skip = false, onSuccess } = {}) {
  const [data,      setData]      = useState(null);
  const [isLoading, setIsLoading] = useState(!skip);
  const [error,     setError]     = useState(null);

  // Stringify params so the effect only re-runs when params actually change
  const paramsKey = JSON.stringify(params);
  const isMounted = useRef(true);

  const fetch = useCallback(async () => {
    if (!url || skip) return;
    setIsLoading(true);
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
      if (isMounted.current) setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, paramsKey, skip]);

  useEffect(() => {
    isMounted.current = true;
    fetch();
    return () => { isMounted.current = false; };
  }, [fetch]);

  return { data, isLoading, error, refetch: fetch };
}

export default useApi;
