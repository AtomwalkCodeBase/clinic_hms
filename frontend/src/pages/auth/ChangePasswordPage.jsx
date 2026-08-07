/**
 * pages/auth/ChangePasswordPage.jsx
 * -----------------------------------
 * Shown after staff logs in with a temporary password.
 * Forces them to set a new password before accessing anything else.
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useToast }    from "../../hooks/useToast";
import apiClient       from "../../services/api.client";
import API_ENDPOINTS   from "../../config/api.config";
import APP_CONFIG      from "../../config/app.config";

export default function ChangePasswordPage() {
  const navigate = useNavigate();
  const { toastSuccess, toastApiError } = useToast();

  const [newPassword,     setNewPassword]     = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading,         setLoading]         = useState(false);
  const [errors,          setErrors]          = useState({});

  async function handleSubmit(e) {
    e.preventDefault();
    setErrors({});

    if (newPassword !== confirmPassword) {
      setErrors({ confirm_password: "Passwords do not match." });
      return;
    }

    setLoading(true);
    try {
      await apiClient.post(API_ENDPOINTS.AUTH.CHANGE_PASSWORD, {
        new_password:     newPassword,
        confirm_password: confirmPassword,
      });
      toastSuccess("Password changed. Welcome!");
      navigate("/");
    } catch (err) {
      if (err?.errors) setErrors(err.errors);
      toastApiError(err, "Failed to change password.");
    } finally {
      setLoading(false);
    }
  }

  const inputStyle = (hasError) => ({
    outline: "none",
    border: `1.5px solid ${hasError ? "var(--color-error)" : "var(--color-border)"}`,
    borderRadius: "var(--radius-button)",
    padding: "10px 12px",
    fontSize: "var(--font-size-md)",
    width: "100%",
    boxSizing: "border-box",
    background: "var(--color-surface)",
    color: "var(--color-text)",
  });

  const labelStyle = {
    display: "block",
    fontSize: "var(--font-size-sm)",
    fontWeight: 600,
    marginBottom: 6,
    color: "var(--color-text)",
  };

  return (
    <div style={{
      minHeight: "100vh",
      background: "var(--color-bg)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      padding: "24px",
    }}>
      <div style={{ width: "100%", maxWidth: 420 }}>

        <div style={{ textAlign: "center", marginBottom: 32 }}>
          <div style={{
            width: 52, height: 52, background: "var(--color-primary)",
            borderRadius: 14, margin: "0 auto 12px",
            display: "flex", alignItems: "center", justifyContent: "center",
            color: "#fff", fontWeight: 700, fontSize: 22,
          }}>A</div>
          <h1 style={{ fontSize: "var(--font-size-xl)", fontWeight: 700, margin: 0 }}>
            Set Your Password
          </h1>
          <p style={{ color: "var(--color-text-muted)", fontSize: "var(--font-size-sm)", marginTop: 8 }}>
            You logged in with a temporary password.<br />Please set a new password to continue.
          </p>
        </div>

        <div className="card" style={{ padding: 32 }}>
          <form onSubmit={handleSubmit}>
            <div style={{ marginBottom: 16 }}>
              <label style={labelStyle}>New Password</label>
              <input
                style={inputStyle(!!errors.new_password)}
                type="password"
                value={newPassword}
                onChange={e => setNewPassword(e.target.value)}
                placeholder="Minimum 8 characters"
                minLength={8}
                required
                autoFocus
              />
              {errors.new_password && (
                <div style={{ color: "var(--color-error)", fontSize: 12, marginTop: 4 }}>
                  {errors.new_password}
                </div>
              )}
            </div>

            <div style={{ marginBottom: 24 }}>
              <label style={labelStyle}>Confirm Password</label>
              <input
                style={inputStyle(!!errors.confirm_password)}
                type="password"
                value={confirmPassword}
                onChange={e => setConfirmPassword(e.target.value)}
                placeholder="Repeat your new password"
                required
              />
              {errors.confirm_password && (
                <div style={{ color: "var(--color-error)", fontSize: 12, marginTop: 4 }}>
                  {errors.confirm_password}
                </div>
              )}
            </div>

            <button
              className="btn-primary"
              type="submit"
              disabled={loading}
              style={{ width: "100%" }}
            >
              {loading ? "Saving…" : "Set Password & Continue"}
            </button>
          </form>
        </div>

        <p style={{
          textAlign: "center", marginTop: 20,
          fontSize: "var(--font-size-sm)", color: "var(--color-text-muted)",
        }}>
          Need help? {APP_CONFIG.SUPPORT_EMAIL}
        </p>
      </div>
    </div>
  );
}
