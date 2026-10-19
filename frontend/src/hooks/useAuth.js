/** hooks/useAuth.js */

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
