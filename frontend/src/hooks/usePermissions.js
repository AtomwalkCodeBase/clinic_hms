/** hooks/usePermissions.js */

import { useContext, useCallback } from "react";
import { PermissionContext } from "../context/PermissionContext";

const LIMIT_FIELD = { doctors: "max_doctors", branches: "max_branches", staff: "max_staff" };

export function usePermissions() {
  const ctx = useContext(PermissionContext);
  if (!ctx) throw new Error("usePermissions must be used inside <PermissionProvider>");

  const atCapacity = useCallback((resource) => {
    const limitField = LIMIT_FIELD[resource];
    const limit = ctx.permissions?.[limitField];
    const used = ctx.permissions?.usage?.[resource];
    if (!limitField || limit == null || used == null) return false;
    if (limit <= 0) return false; // unlimited on this tier
    return used >= limit;
  }, [ctx.permissions]);

  const remaining = useCallback((resource) => {
    const limitField = LIMIT_FIELD[resource];
    const limit = ctx.permissions?.[limitField];
    const used = ctx.permissions?.usage?.[resource];
    if (!limitField || limit == null || used == null) return null;
    if (limit <= 0) return null; // unlimited — nothing meaningful to show
    return Math.max(0, limit - used);
  }, [ctx.permissions]);

  return { ...ctx, atCapacity, remaining };
}

export default usePermissions;
