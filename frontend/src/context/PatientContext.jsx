/** context/PatientContext.jsx */

import { createContext, useState, useEffect, useContext, useCallback } from "react";
import { apiClient }   from "../services/api.client";
import API_ENDPOINTS   from "../config/api.config";
import { AuthContext } from "./AuthContext";

export const PatientContext = createContext(null);

const STORAGE_PREFIX = "atomwalk:portal_selected_patient";

function storageKeyFor(userId) {
  return userId ? `${STORAGE_PREFIX}:${userId}` : null;
}

/** Called from AuthContext on logout / detected session expiry — tidies up */
export function clearStoredSelection(userId) {
  const key = storageKeyFor(userId);
  if (key) localStorage.removeItem(key);
}

function readStored(userId) {
  const key = storageKeyFor(userId);
  if (!key) return null;
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed && parsed.awpid) return { awpid: parsed.awpid, name: parsed.name || "" };
  } catch {
    // ignore malformed storage
  }
  return null;
}

export function PatientProvider({ children }) {
  const { user } = useContext(AuthContext);
  const userId = user?.user_id ?? null;
  const [familyMembers, setFamilyMembers] = useState([]);
  const [isLoadingFamily, setIsLoadingFamily] = useState(false);

  const selfName = user?.full_name || user?.email?.split("@")[0] || "Me";

  const [selectedPatient, setSelectedPatient] = useState(() => {
    const stored = readStored(userId);
    return stored
      ? { awpid: stored.awpid, name: stored.name, isSelf: false }
      : { awpid: null, name: selfName, isSelf: true };
  });

  // Keep the "self" label in sync once the user's real name loads (the
  useEffect(() => {
    setSelectedPatient(prev => (prev.isSelf ? { ...prev, name: selfName } : prev));
  }, [selfName]);

  // Fetch the family list once on mount (patient portal only).
  useEffect(() => {
    if (!user) return;
    setIsLoadingFamily(true);
    apiClient.get(API_ENDPOINTS.PORTAL.FAMILY)
      .then(({ data: res }) => {
        const results = res?.data?.results || [];
        setFamilyMembers(results);
        // Belt-and-suspenders: the per-account key already means this
        setSelectedPatient(prev => {
          if (prev.isSelf) return prev;
          const stillValid = results.some(m => m.awpid === prev.awpid);
          if (stillValid) return prev;
          clearStoredSelection(userId);
          return { awpid: null, name: selfName, isSelf: true };
        });
      })
      .catch(() => setFamilyMembers([]))
      .finally(() => setIsLoadingFamily(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  /** selectPatient(null, null) (or no args) resets the view back to self. */
  const selectPatient = useCallback((awpid, name) => {
    if (!awpid) {
      clearStoredSelection(userId);
      setSelectedPatient({ awpid: null, name: selfName, isSelf: true });
      return;
    }
    const key = storageKeyFor(userId);
    if (key) localStorage.setItem(key, JSON.stringify({ awpid, name }));
    setSelectedPatient({ awpid, name: name || "", isSelf: false });
  }, [selfName, userId]);

  return (
    <PatientContext.Provider value={{ familyMembers, isLoadingFamily, selectedPatient, selectPatient }}>
      {children}
    </PatientContext.Provider>
  );
}

export function usePatientContext() {
  const ctx = useContext(PatientContext);
  if (!ctx) {
    throw new Error("usePatientContext must be used within a PatientProvider");
  }
  return ctx;
}

export default PatientContext;
