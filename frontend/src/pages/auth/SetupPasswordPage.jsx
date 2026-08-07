/**
 * pages/auth/SetupPasswordPage.jsx
 * ----------------------------------
 * Staff use this page (via invite link) to set their own password.
 * Token is passed as a URL query param: /setup-password?token=<invite_token>
 */

import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { publicClient } from "../../services/api.client";
import { useToast }     from "../../hooks/useToast";
import API_ENDPOINTS    from "../../config/api.config";
import { MESSAGES }     from "../../constants/messages";
import APP_CONFIG       from "../../config/app.config";

export default function SetupPasswordPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const { toastSuccess, toastApiError } = useToast();

  const [password,  setPassword]  = useState("");
  const [confirm,   setConfirm]   = useState("");
  const [loading,   setLoading]   = useState(false);
  const [errors,    setErrors]    = useState({});

  async function handleSubmit(e) {
    e.preventDefault();
    setErrors({});
    if (password !== confirm) {
      setErrors({ confirm_password: MESSAGES.PASSWORDS_MISMATCH });
      return;
    }
    setLoading(true);
    try {
      await publicClient.post(API_ENDPOINTS.AUTH.SETUP_PASSWORD, {
        invite_token: token, new_password: password, confirm_password: confirm,
      });
      toastSuccess(MESSAGES.PASSWORD_SETUP_SUCCESS);
      navigate("/login");
    } catch (err) {
      if (err?.errors) setErrors(err.errors);
      toastApiError(err, "Failed to set password.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{
      minHeight: "100vh", background: "var(--color-bg)",
      display: "flex", alignItems: "center", justifyContent: "center", padding: 24,
    }}>
      <div style={{ width: "100%", maxWidth: 400 }}>
        <div style={{ textAlign: "center", marginBottom: 28 }}>
          <h1 style={{ fontSize: "var(--font-size-xl)", fontWeight: 700 }}>Set Your Password</h1>
          <p style={{ color: "var(--color-text-muted)", fontSize: "var(--font-size-sm)", marginTop: 6 }}>
            Create a secure password for your {APP_CONFIG.APP_NAME} account.
          </p>
        </div>
        <div className="card" style={{ padding: 32 }}>
          {!token && (
            <p style={{ color: "var(--color-error)", marginBottom: 16, fontSize: "var(--font-size-sm)" }}>
              Invalid or missing invite token. Please use the link from your invite email.
            </p>
          )}
          <form onSubmit={handleSubmit}>
            <div style={{ marginBottom: 16 }}>
              <label style={{ display: "block", fontSize: "var(--font-size-sm)", fontWeight: 600, marginBottom: 6 }}>
                New Password
              </label>
              <input className={`form-input ${errors.new_password ? "error" : ""}`}
                type="password" value={password} onChange={e => setPassword(e.target.value)}
                placeholder="Min. 8 characters" required minLength={8} />
              {errors.new_password && <div className="field-error">{errors.new_password}</div>}
            </div>
            <div style={{ marginBottom: 24 }}>
              <label style={{ display: "block", fontSize: "var(--font-size-sm)", fontWeight: 600, marginBottom: 6 }}>
                Confirm Password
              </label>
              <input className={`form-input ${errors.confirm_password ? "error" : ""}`}
                type="password" value={confirm} onChange={e => setConfirm(e.target.value)}
                placeholder="Repeat password" required />
              {errors.confirm_password && <div className="field-error">{errors.confirm_password}</div>}
            </div>
            <button className="btn-primary" type="submit" disabled={!token || loading}
              style={{ width: "100%" }}>
              {loading ? "Setting password…" : "Set Password & Sign In"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
