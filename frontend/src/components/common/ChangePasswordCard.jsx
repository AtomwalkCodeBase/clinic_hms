/**
 * components/common/ChangePasswordCard.jsx
 * --------------------------------------------
 * Self-service "Change Password" section, dropped into each role's My
 * Profile page. Always requires the current password — unlike the forced
 * first-login flow (ChangePasswordPage), this can be reached any time by
 * someone who already has a working session, so proving the current
 * password again is what stops a hijacked/left-open session from locking
 * the real owner out.
 */
import { useState } from "react";
import { useToast } from "../../hooks/useToast";
import apiClient from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";

const inputStyle = {
  width: "100%", boxSizing: "border-box",
  border: "1.5px solid var(--color-border)", borderRadius: 8,
  padding: "9px 12px", fontSize: 14,
  background: "var(--color-surface)", color: "var(--color-text)", outline: "none",
};
const labelStyle = { display: "block", fontSize: 13, fontWeight: 600, marginBottom: 5 };

export default function ChangePasswordCard() {
  const { toastSuccess, toastApiError } = useToast();
  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState({});

  function reset() {
    setCurrent(""); setNext(""); setConfirm(""); setErrors({});
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setErrors({});
    if (next !== confirm) {
      setErrors({ confirm_password: "Passwords do not match." });
      return;
    }
    setSaving(true);
    try {
      await apiClient.post(API_ENDPOINTS.AUTH.CHANGE_PASSWORD, {
        current_password: current,
        new_password: next,
        confirm_password: confirm,
      });
      toastSuccess("Password changed.");
      reset();
      setOpen(false);
    } catch (err) {
      if (err?.errors) setErrors(err.errors);
      toastApiError(err, "Failed to change password.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card" style={{ padding: 24, marginTop: 20 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: open ? 16 : 0 }}>
        <div className="dot-label dot-label--green">Password</div>
        <button type="button" className="btn-outline" style={{ fontSize: 12, padding: "5px 14px" }}
          onClick={() => { setOpen(o => !o); if (open) reset(); }}>
          {open ? "Cancel" : "Change Password"}
        </button>
      </div>

      {open && (
        <form onSubmit={handleSubmit} style={{ maxWidth: 360 }}>
          <div style={{ display: "grid", gap: 14 }}>
            <div>
              <label style={labelStyle}>Current Password</label>
              <input type="password" style={inputStyle} value={current}
                onChange={e => setCurrent(e.target.value)} required autoComplete="current-password" />
              {errors.current_password && (
                <div style={{ color: "var(--color-error)", fontSize: 12, marginTop: 4 }}>{errors.current_password}</div>
              )}
            </div>
            <div>
              <label style={labelStyle}>New Password</label>
              <input type="password" style={inputStyle} value={next}
                onChange={e => setNext(e.target.value)} minLength={8} required autoComplete="new-password"
                placeholder="Minimum 8 characters" />
              {errors.new_password && (
                <div style={{ color: "var(--color-error)", fontSize: 12, marginTop: 4 }}>{errors.new_password}</div>
              )}
            </div>
            <div>
              <label style={labelStyle}>Confirm New Password</label>
              <input type="password" style={inputStyle} value={confirm}
                onChange={e => setConfirm(e.target.value)} required autoComplete="new-password" />
              {errors.confirm_password && (
                <div style={{ color: "var(--color-error)", fontSize: 12, marginTop: 4 }}>{errors.confirm_password}</div>
              )}
            </div>
          </div>
          <button type="submit" disabled={saving} className="btn-primary" style={{ marginTop: 18, padding: "9px 20px" }}>
            {saving ? "Saving…" : "Save New Password"}
          </button>
        </form>
      )}
    </div>
  );
}
