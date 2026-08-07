/**
 * context/TenantContext.jsx
 * -------------------------
 * Provides tenant-level metadata fetched from /api/v1/auth/me/.
 *
 * Separate from AuthContext so tenant info can be refreshed
 * independently without touching the JWT.
 */

import { createContext, useState, useEffect, useContext } from "react";
import { apiClient }   from "../services/api.client";
import API_ENDPOINTS   from "../config/api.config";
import { AuthContext } from "./AuthContext";

export const TenantContext = createContext(null);

export function TenantProvider({ children }) {
  const { user } = useContext(AuthContext);
  const [tenant,    setTenant]    = useState(null);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (!user) {
      setTenant(null);
      return;
    }
    // Platform admin has no tenant
    if (user.role === "platform_admin") {
      setTenant({ name: "Platform", isPlatform: true });
      return;
    }

    setIsLoading(true);
    apiClient
      .get(API_ENDPOINTS.AUTH.ME)
      .then(({ data }) => setTenant(data.data))
      .catch(() => setTenant(null))
      .finally(() => setIsLoading(false));
  }, [user]);

  return (
    <TenantContext.Provider value={{ tenant, isLoading }}>
      {children}
    </TenantContext.Provider>
  );
}
