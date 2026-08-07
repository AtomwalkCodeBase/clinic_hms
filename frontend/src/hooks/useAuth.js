/**
 * hooks/useAuth.js
 * ----------------
 * Convenience hook. Consume AuthContext anywhere in the tree.
 *
 * Returns:
 *   user         — decoded JWT payload or null
 *   role         — current role string
 *   isLoading    — true while hydrating on first mount
 *   loginStaff   — async (email, password, subdomain) => void
 *   loginPatient — async (awpid, password) => void
 *   logout       — () => void
 */

import { useContext } from "react";
import { AuthContext } from "../context/AuthContext";

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return {
    ...ctx,
    role: ctx.user?.role ?? null,
  };
}

export default useAuth;
