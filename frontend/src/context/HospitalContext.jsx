/**
 * context/HospitalContext.jsx
 * -------------------------
 * Provides hospital-level metadata fetched from /api/v1/auth/me/.
 *
 * Separate from AuthContext so hospital info can be refreshed
 * independently without touching the JWT.
 */

import { createContext, useState, useEffect, useContext } from "react";
import { apiClient }   from "../services/api.client";
import API_ENDPOINTS   from "../config/api.config";
import { AuthContext } from "./AuthContext";

export const HospitalContext = createContext(null);

export function HospitalProvider({ children }) {
  const { user } = useContext(AuthContext);
  const [hospital,    setHospital]    = useState(null);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (!user) {
      setHospital(null);
      return;
    }
    // Platform admin has no hospital
    if (user.role === "platform_admin") {
      setHospital({ name: "Platform", isPlatform: true });
      return;
    }

    setIsLoading(true);
    apiClient
      .get(API_ENDPOINTS.AUTH.ME)
      .then(({ data }) => setHospital(data.data))
      .catch(() => setHospital(null))
      .finally(() => setIsLoading(false));
  }, [user]);

  return (
    <HospitalContext.Provider value={{ hospital, isLoading }}>
      {children}
    </HospitalContext.Provider>
  );
}
