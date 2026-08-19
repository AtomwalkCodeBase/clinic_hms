/**
 * components/auth/ForgotPasswordFlow.jsx
 * -----------------------------------------
 * Shared 3-step OTP forgot-password flow: Identify -> Enter code -> New
 * password. Driven entirely by the generic OTP endpoints
 * (apps/auth_app/otp_views.py) — `audience` picks the purpose + the
 * reset endpoint that consumes the resulting action_token, everything
 * else is identical between staff and patient.
 *
 * Rendered by two separate routed pages (StaffForgotPasswordPage /
 * PatientForgotPasswordPage) rather than a shared tab-switcher — each
 * audience gets its own URL, its own copy, and never sees the other's
 * form, which is one less place to pick the wrong tab by mistake.
 */

import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useToast } from "../../hooks/useToast";
import { publicClient } from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import APP_CONFIG from "../../config/app.config";
import { ROUTES } from "../../config/routes.config";
import NewPasswordFields from "./NewPasswordFields";
import AutofillDecoy from "./AutofillDecoy";

const AUDIENCE_CONFIG = {
  staff: {
    purpose: "password_reset_staff",
    resetEndpoint: API_ENDPOINTS.AUTH.STAFF_FORGOT_PASSWORD_RESET,
    label: "your mobile number or work email",
    placeholder: "98xxxxxxxx or you@hospital.com",
    helpText: "Ask your hospital admin to reset your password instead.",
  },
  patient: {
    purpose: "password_reset_patient",
    resetEndpoint: API_ENDPOINTS.AUTH.PATIENT_FORGOT_PASSWORD_RESET,
    label: "your mobile number, email, or Patient ID (AWPID)",
    placeholder: "98xxxxxxxx, you@example.com, or AWPID-…",
    helpText: `Contact ${APP_CONFIG.SUPPORT_EMAIL} for help.`,
  },
};

const labelStyle = {
  display: "block", fontSize: 11, fontWeight: 700, letterSpacing: "0.06em",
  textTransform: "uppercase", marginBottom: 7, color: "var(--color-text-secondary)",
};
const inputStyle = {
  outline: "none", border: "1.5px solid var(--color-border)", borderRadius: "var(--radius-input)",
  padding: "10px 14px", fontSize: 14, width: "100%", boxSizing: "border-box",
  background: "var(--color-bg)", color: "var(--color-text)",
};

export default function ForgotPasswordFlow({ audience }) {
  const cfg = AUDIENCE_CONFIG[audience];
  const navigate = useNavigate();
  const { toastSuccess, toastApiError } = useToast();

  const [step, setStep] = useState("identify"); // identify -> code -> password -> done
  const [identifier, setIdentifier] = useState("");
  const [maskedIdentifier, setMaskedIdentifier] = useState("");
  const [code, setCode] = useState("");
  const [actionToken, setActionToken] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [errors, setErrors] = useState({});
  const [resendIn, setResendIn] = useState(0);

  function startResendTimer() {
    setResendIn(60);
    const t = setInterval(() => {
      setResendIn(s => {
        if (s <= 1) { clearInterval(t); return 0; }
        return s - 1;
      });
    }, 1000);
  }

  async function requestCode(e) {
    e?.preventDefault();
    if (!identifier.trim()) return;
    setLoading(true);
    setErrors({});
    try {
      const { data } = await publicClient.post(API_ENDPOINTS.AUTH.OTP_REQUEST, {
        purpose: cfg.purpose, identifier: identifier.trim(),
      });
      setMaskedIdentifier(data.data?.masked_identifier || "");
      setStep("code");
      startResendTimer();
      toastSuccess(data.message || "Verification code sent.");
    } catch (err) {
      toastApiError(err, "Couldn't send a verification code.");
    } finally {
      setLoading(false);
    }
  }

  async function verifyCode(e) {
    e.preventDefault();
    if (!code.trim()) return;
    setLoading(true);
    setErrors({});
    try {
      const { data } = await publicClient.post(API_ENDPOINTS.AUTH.OTP_VERIFY, {
        purpose: cfg.purpose, identifier: identifier.trim(), code: code.trim(),
      });
      setActionToken(data.data.action_token);
      setStep("password");
    } catch (err) {
      toastApiError(err, "That code didn't work.");
    } finally {
      setLoading(false);
    }
  }

  async function resetPassword(e) {
    e.preventDefault();
    setErrors({});
    if (newPassword !== confirmPassword) {
      setErrors({ confirm_password: "Passwords do not match." });
      return;
    }
    setLoading(true);
    try {
      await publicClient.post(cfg.resetEndpoint, {
        action_token: actionToken, new_password: newPassword, confirm_password: confirmPassword,
      });
      setStep("done");
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
            {audience === "staff" ? "Staff" : "Patient"} account recovery via one-time code.
          </p>
        </div>

        <div className="card" style={{ padding: 28 }}>
          {step === "identify" && (
            <form onSubmit={requestCode}>
              <AutofillDecoy />
              <div style={{ marginBottom: 20 }}>
                <label style={labelStyle}>Enter {cfg.label}</label>
                <input style={inputStyle} value={identifier} onChange={e => setIdentifier(e.target.value)}
                  placeholder={cfg.placeholder} required autoFocus />
                {errors.identifier && <div style={{ color: "var(--color-error)", fontSize: 12, marginTop: 5 }}>{errors.identifier}</div>}
              </div>
              <button className="btn-primary" type="submit" disabled={loading} style={{ width: "100%", padding: "12px 0", fontWeight: 700 }}>
                {loading ? "Sending code…" : "Send verification code"}
              </button>
              <p style={{ marginTop: 16, fontSize: 12.5, color: "var(--color-text-muted)", textAlign: "center" }}>
                {cfg.helpText}
              </p>
              {audience === "patient" && (
                <p style={{ marginTop: 6, fontSize: 13, color: "var(--color-text-muted)", textAlign: "center" }}>
                  Don't have an account yet?{" "}
                  <Link to={`${ROUTES.LOGIN}?register=1`} style={{ color: "var(--color-primary)", fontWeight: 700 }}>
                    Create one
                  </Link>
                </p>
              )}
            </form>
          )}

          {step === "code" && (
            <form onSubmit={verifyCode}>
              <p style={{ fontSize: 13.5, color: "var(--color-text)", marginBottom: 18 }}>
                Enter the 6-digit code we sent to <strong>{maskedIdentifier || "your device"}</strong>.
              </p>
              <div style={{ marginBottom: 16 }}>
                <label style={labelStyle}>Verification Code</label>
                <input style={{ ...inputStyle, letterSpacing: "0.3em", fontSize: 20, textAlign: "center" }}
                  value={code} onChange={e => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  inputMode="numeric" maxLength={6} placeholder="••••••" required autoFocus />
              </div>
              <button className="btn-primary" type="submit" disabled={loading || code.length < 6}
                style={{ width: "100%", padding: "12px 0", fontWeight: 700 }}>
                {loading ? "Verifying…" : "Verify code"}
              </button>
              <p style={{ marginTop: 16, textAlign: "center", fontSize: 12.5 }}>
                {resendIn > 0 ? (
                  <span style={{ color: "var(--color-text-muted)" }}>Resend code in {resendIn}s</span>
                ) : (
                  <button type="button" onClick={requestCode} disabled={loading}
                    style={{ background: "none", border: "none", color: "var(--color-primary)", fontWeight: 700, cursor: "pointer", fontSize: "inherit" }}>
                    Resend code
                  </button>
                )}
              </p>
            </form>
          )}

          {step === "password" && (
            <form onSubmit={resetPassword}>
              <AutofillDecoy />
              <NewPasswordFields
                password={newPassword} onPasswordChange={e => setNewPassword(e.target.value)}
                confirmPassword={confirmPassword} onConfirmPasswordChange={e => setConfirmPassword(e.target.value)}
                errors={errors}
              />
              <button className="btn-primary" type="submit" disabled={loading} style={{ width: "100%", padding: "12px 0", fontWeight: 700, marginTop: 6 }}>
                {loading ? "Resetting…" : "Reset Password"}
              </button>
            </form>
          )}

          {step === "done" && (
            <div style={{ textAlign: "center", padding: "12px 0" }}>
              <p style={{ fontSize: 14, color: "var(--color-text)", marginBottom: 20 }}>
                Your password has been reset. Sign in with your new password.
              </p>
              <button className="btn-primary" style={{ width: "100%" }} onClick={() => navigate(ROUTES.LOGIN)}>
                Go to Sign In
              </button>
            </div>
          )}
        </div>

        <p style={{ textAlign: "center", marginTop: 20, fontSize: 13 }}>
          <Link to={ROUTES.LOGIN} style={{ color: "var(--color-primary)", fontWeight: 600 }}>← Back to Sign In</Link>
        </p>
      </div>
    </div>
  );
}
