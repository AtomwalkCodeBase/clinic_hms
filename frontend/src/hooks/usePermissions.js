/**
 * hooks/usePermissions.js
 * ------------------------
 * Convenience hook. Consume PermissionContext anywhere in the tree.
 *
 * Returns:
 *   permissions — flat object of feature flags + tier limits + live usage,
 *                 e.g. { feat_lab, max_doctors, max_branches, max_staff,
 *                        usage: { doctors, branches, staff } }
 *   can(feature) — convenience function to check a single feature flag
 *   isLoading    — true while fetching
 *   atCapacity(resource) — true if usage.<resource> >= max_<resource> and
 *                          the limit isn't 0 (0 = unlimited on this tier)
 *   remaining(resource)  — max minus current usage, or null if usage/limit
 *                          isn't known yet (still loading) — never negative
 */

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
