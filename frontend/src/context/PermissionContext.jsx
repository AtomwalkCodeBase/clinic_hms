/** context/PermissionContext.jsx */

import { createContext, useState, useEffect, useContext, useCallback } from "react";
import { apiClient }   from "../services/api.client";
import API_ENDPOINTS   from "../config/api.config";
import { AuthContext } from "./AuthContext";

export const PermissionContext = createContext(null);

export function PermissionProvider({ children }) {
  const { user } = useContext(AuthContext);
  const [permissions, setPermissions] = useState({});
  const [isLoading,   setIsLoading]   = useState(false);

  const refresh = useCallback(() => {
    if (!user) {
      setPermissions({});
      return Promise.resolve();
    }
    setIsLoading(true);
    return apiClient
      .get(API_ENDPOINTS.AUTH.PERMISSIONS)
      .then(({ data }) => setPermissions(data.data || {}))
      .catch(() => setPermissions({}))
      .finally(() => setIsLoading(false));
  }, [user]);

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  /** Returns true if the given feature flag is enabled for this hospital. */
  const can = useCallback(
    (feature) => Boolean(permissions[feature]),
    [permissions]
  );

  return (
    <PermissionContext.Provider value={{ permissions, can, isLoading, refresh }}>
      {children}
    </PermissionContext.Provider>
  );
}
