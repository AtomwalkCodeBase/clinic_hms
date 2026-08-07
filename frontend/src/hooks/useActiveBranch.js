/**
 * hooks/useActiveBranch.js
 * --------------------------
 * For staff assigned to more than one branch (today, realistically just
 * doctors — see StaffBranchMapping / docs/onboarding_auth_rbac_architecture.md
 * 4.4) — fetches their own branch assignment and tracks which one is
 * "active" for branch-scoped views (queue, dashboard), persisted in
 * localStorage so the choice survives a refresh.
 *
 * Staff with 0 or 1 branch get `hasMultiple: false` and nothing changes
 * for them — no switcher UI, no explicit branch_id sent, same behavior as
 * before this existed.
 */

import { useState, useEffect, useCallback } from "react";
import apiClient from "../services/api.client";
import API_ENDPOINTS from "../config/api.config";

const STORAGE_KEY = "atomwalk:active_branch_id";

export function useActiveBranch() {
  const [branches, setBranches] = useState([]);
  const [activeBranchId, setActiveBranchIdState] = useState(() => localStorage.getItem(STORAGE_KEY) || "");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiClient.get(API_ENDPOINTS.ORG.MY_BRANCHES)
      .then(r => {
        const list = r.data?.data || [];
        setBranches(list);
        const stored = localStorage.getItem(STORAGE_KEY);
        const stillValid = list.some(b => String(b.id) === String(stored));
        if (!stillValid) {
          const primary = list.find(b => b.is_primary) || list[0] || null;
          const nextId = primary ? String(primary.id) : "";
          if (nextId) localStorage.setItem(STORAGE_KEY, nextId);
          setActiveBranchIdState(nextId);
        }
      })
      .catch(() => setBranches([]))
      .finally(() => setLoading(false));
  }, []);

  const setActiveBranchId = useCallback((id) => {
    const idStr = String(id);
    localStorage.setItem(STORAGE_KEY, idStr);
    setActiveBranchIdState(idStr);
  }, []);

  return {
    branches,
    activeBranchId,
    setActiveBranchId,
    loading,
    hasMultiple: branches.length > 1,
  };
}

export default useActiveBranch;
