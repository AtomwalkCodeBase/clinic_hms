/**
 * pages/auth/ForgotPasswordPage.jsx
 * -------------------------------------
 * Self-service password reset for staff and patients.
 *
 * There's no email/SMS gateway wired into this stack, so this can't send
 * a reset link or OTP — it verifies identity with two things already on
 * file: the mobile number (or AWPID, for patients) used to log in, plus
 * date of birth from the person's own profile. If DOB was never set, the
 * backend rejects the request and this page says so — staff are pointed
 * to their hospital admin (who can always reset a password directly),
 * patients are pointed to support.
 */

import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useToast }   from "../../hooks/useToast";
import apiClient      from "../../services/api.client";
import API_ENDPOINTS  from "../../config/api.config";
import APP_CONFIG     from "../../config/app.config";
import { ROUTES }     from "../../config/routes.config";

const TABS = [
  { key: "staff",   label: "Staff" },
  { key: "patient", label: "Patient" },
];

const labelStyle = {
  display: "block", fontSize: 11, fontWeight: 700, letterSpacing: "0.06em",
  textTransform: "uppercase", marginBottom: 7, color: "var(--color-text-secondary)",
};
const inputStyle = {
  outline: "none", border: "1.5px solid var(--color-border)", borderRadius: "var(--radius-input)",
  padding: "10px 14px", fontSize: 14, width: "100%", boxSizing: "border-box",
  background: "var(--color-bg)", color: "var(--color-text)",
};

export default function ForgotPasswordPage() {
  const navigate = useNavigate();
  const { toastSuccess, toastApiError } = useToast();

  const [tab, setTab] = useState("staff");
  const [loginId, setLoginId] = useState("");     // mobile (staff) / mobile-or-AWPID (patient)
  const [dob, setDob]         = useState("");
  const [newPassword, setNewPassword]         = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [errors, setErrors]   = useState({});
  const [done, setDone]       = useState(false);

  function switchTab(key) {
    setTab(key);
    setErrors({});
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setErrors({});

    if (newPassword !== confirmPassword) {
      setErrors({ confirm_password: "Passwords do not match." });
      return;
    }

    setLoading(true);
    try {
      const endpoint = tab === "staff" ? API_ENDPOINTS.AUTH.STAFF_FORGOT_PASSWORD : API_ENDPOINTS.PORTAL.FORGOT_PASSWORD;
      const body = tab === "staff"
        ? { mobile: loginId, date_of_birth: dob, new_password: newPassword, confirm_password: confirmPassword }
        : { mobile_or_awpid: loginId, date_of_birth: dob, new_password: newPassword, confirm_password: confirmPassword };
      const { publicClient } = await import("../../services/api.client");
      await publicClient.post(endpoint, body);
      setDone(true);
      toastSuccess("Password reset. You can now sign in.");
    } catch (err) {
      if (err?.errors) setErrors(err.errors);
      toastApiError(err, "Could not reset your password.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{
      minHeight: "100vh", background: "var(--color-bg)", display: "flex",
      alignItems: "center", justifyContent: "center", padding: 24,
    }}>
      <div style={{ width: "100%", maxWidth: 420 }}>

        <div style={{ textAlign: "center", marginBottom: 28 }}>
          <div style={{
            width: 52, height: 52, background: "var(--color-primary)", borderRadius: 14,
            margin: "0 auto 12px", display: "flex", alignItems: "center", justifyContent: "center",
            color: "#fff", fontWeight: 700, fontSize: 22,
          }}>A</div>
          <h1 style={{ fontFamily: "var(--font-display)", fontWeight: 600, fontSize: 24, margin: 0 }}>
            Reset your password
          </h1>
          <p style={{ color: "var(--color-text-muted)", fontSize: 13, marginTop: 8 }}>
            Verify your identity with your mobile number and date of birth.
          </p>
        </div>

        <div className="card" style={{ padding: 28 }}>

          {!done && (
            <div style={{
              display: "flex", background: "var(--color-bg)", borderRadius: "var(--radius-button)",
              padding: 4, marginBottom: 22, gap: 2,
            }}>
              {TABS.map(t => (
                <button key={t.key} type="button" onClick={() => switchTab(t.key)}
                  style={{
                    flex: 1, padding: "8px 4px", border: "none", borderRadius: "var(--radius-button)",
                    background: tab === t.key ? "var(--color-surface)" : "transparent",
                    color: tab === t.key ? "var(--color-primary)" : "var(--color-text-muted)",
                    fontWeight: tab === t.key ? 700 : 500, fontSize: 12.5,
                    boxShadow: tab === t.key ? "var(--shadow-card)" : "none", cursor: "pointer",
                  }}>{t.label}</button>
              ))}
            </div>
          )}

          {done ? (
            <div style={{ textAlign: "center", padding: "12px 0" }}>
              <p style={{ fontSize: 14, color: "var(--color-text)", marginBottom: 20 }}>
                Your password has been reset. Sign in with your new password.
              </p>
              <button className="btn-primary" style={{ width: "100%" }} onClick={() => navigate(ROUTES.LOGIN)}>
                Go to Sign In
              </button>
            </div>
          ) : (
            <form onSubmit={handleSubmit}>
              <div style={{ marginBottom: 16 }}>
                <label style={labelStyle}>
                  {tab === "staff" ? "Mobile Number" : "Mobile Number or Patient ID (AWPID)"}
                </label>
                <input style={inputStyle} value={loginId} onChange={e => setLoginId(e.target.value)}
                  placeholder={tab === "staff" ? "98xxxxxxxx" : "98xxxxxxxx or AWPID-…"} required />
                {errors.mobile && <div style={{ color: "var(--color-error)", fontSize: 12, marginTop: 5 }}>{errors.mobile}</div>}
              </div>

              <div style={{ marginBottom: 16 }}>
                <label style={labelStyle}>Date of Birth</label>
                <input type="date" style={inputStyle} value={dob} onChange={e => setDob(e.target.value)} required />
                <div style={{ fontSize: 11.5, color: "var(--color-text-muted)", marginTop: 5 }}>
                  Must match the date of birth on your profile.
                </div>
              </div>

              <div style={{ marginBottom: 16 }}>
                <label style={labelStyle}>New Password</label>
                <input type="password" style={inputStyle} value={newPassword} onChange={e => setNewPassword(e.target.value)}
                  placeholder="Minimum 8 characters" minLength={8} required />
                {errors.new_password && <div style={{ color: "var(--color-error)", fontSize: 12, marginTop: 5 }}>{errors.new_password}</div>}
              </div>

              <div style={{ marginBottom: 22 }}>
                <label style={labelStyle}>Confirm New Password</label>
                <input type="password" style={inputStyle} value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)}
                  placeholder="Repeat your new password" required />
                {errors.confirm_password && <div style={{ color: "var(--color-error)", fontSize: 12, marginTop: 5 }}>{errors.confirm_password}</div>}
              </div>

              <button className="btn-primary" type="submit" disabled={loading} style={{ width: "100%", padding: "12px 0", fontWeight: 700 }}>
                {loading ? "Verifying…" : "Reset Password"}
              </button>

              {tab === "staff" ? (
                <p style={{ marginTop: 16, fontSize: 12.5, color: "var(--color-text-muted)", textAlign: "center" }}>
                  No date of birth on file, or details not matching? Ask your hospital admin to reset your password instead.
                </p>
              ) : (
                <p style={{ marginTop: 16, fontSize: 12.5, color: "var(--color-text-muted)", textAlign: "center" }}>
                  No date of birth on file, or details not matching? Contact {APP_CONFIG.SUPPORT_EMAIL} for help.
                </p>
              )}
            </form>
          )}
        </div>

        <p style={{ textAlign: "center", marginTop: 20, fontSize: 13 }}>
          <Link to={ROUTES.LOGIN} style={{ color: "var(--color-primary)", fontWeight: 600 }}>← Back to Sign In</Link>
        </p>
      </div>
    </div>
  );
}
