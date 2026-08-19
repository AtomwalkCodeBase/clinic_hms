/**
 * components/auth/PatientRegisterFlow.jsx
 * ------------------------------------------
 * Patient self-registration — Details -> Code -> Password. Replaces the
 * old single-step inline form (which created an account with no proof any
 * contact detail was reachable). The EMAIL address is verified via OTP
 * before the account is ever created — see
 * apps/patients/portal_views.py::PortalRegisterView, which takes the email
 * from the verified action_token, not from this form's own input, so a
 * verified-then-swapped address can't slip through. Email-based for now —
 * verifying via mobile requires a paid SMS gateway that isn't wired up yet
 * (see core/sms.py). The mobile number is still collected and required
 * (it's the primary login identifier) but isn't OTP-verified here.
 */

import { useState } from "react";
import { publicClient } from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import { sanitizeMobileInput, isValidMobile } from "../../utils/validation";
import NewPasswordFields from "./NewPasswordFields";
import AutofillDecoy from "./AutofillDecoy";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const labelStyle = {
  display: "block", fontSize: 11, fontWeight: 700, letterSpacing: "0.06em",
  textTransform: "uppercase", marginBottom: 7, color: "var(--color-text-secondary)",
};
const fieldWrap = (hasError) => ({
  display: "flex", alignItems: "center", gap: 10,
  border: `1.5px solid ${hasError ? "var(--color-error)" : "var(--color-border)"}`,
  borderRadius: "var(--radius-input)", padding: "0 14px", background: "var(--color-bg)",
});
const bareInput = {
  outline: "none", border: "none", background: "transparent", padding: "11px 0",
  fontSize: 14, width: "100%", color: "var(--color-text)", fontFamily: "inherit",
};

export default function PatientRegisterFlow({ onDone, onCancel, toastSuccess, toastApiError }) {
  const [step, setStep] = useState("details"); // details -> code -> password
  const [loading, setLoading] = useState(false);
  const [fieldErrors, setFieldErrors] = useState({});
  const [resendIn, setResendIn] = useState(0);

  const [form, setForm] = useState({ full_name: "", mobile: "", email: "", date_of_birth: "" });
  const [code, setCode] = useState("");
  const [actionToken, setActionToken] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  function startResendTimer() {
    setResendIn(60);
    const t = setInterval(() => setResendIn(s => (s <= 1 ? (clearInterval(t), 0) : s - 1)), 1000);
  }

  async function requestCode(e) {
    e.preventDefault();
    const errs = {};
    if (!EMAIL_RE.test(form.email.trim())) errs.email = "Enter a valid email address.";
    if (!isValidMobile(form.mobile)) errs.mobile = "Enter a valid 10-digit mobile number.";
    if (Object.keys(errs).length) {
      setFieldErrors(errs);
      return;
    }
    setLoading(true);
    setFieldErrors({});
    try {
      const { data } = await publicClient.post(API_ENDPOINTS.AUTH.OTP_REQUEST, {
        purpose: "registration_patient", identifier: form.email.trim().toLowerCase(),
      });
      setStep("code");
      startResendTimer();
      toastSuccess(data.message || "Verification code sent.");
    } catch (err) {
      if (err?.errors) setFieldErrors(err.errors);
      toastApiError(err, "Couldn't send a verification code.");
    } finally {
      setLoading(false);
    }
  }

  async function verifyCode(e) {
    e.preventDefault();
    if (code.length < 6) return;
    setLoading(true);
    try {
      const { data } = await publicClient.post(API_ENDPOINTS.AUTH.OTP_VERIFY, {
        purpose: "registration_patient", identifier: form.email.trim().toLowerCase(), code,
      });
      setActionToken(data.data.action_token);
      setStep("password");
    } catch (err) {
      toastApiError(err, "That code didn't work.");
    } finally {
      setLoading(false);
    }
  }

  async function createAccount(e) {
    e.preventDefault();
    setFieldErrors({});
    if (password !== confirmPassword) {
      setFieldErrors({ confirm_password: "Passwords do not match." });
      return;
    }
    setLoading(true);
    try {
      await publicClient.post(API_ENDPOINTS.PORTAL.REGISTER, {
        action_token: actionToken,
        full_name: form.full_name,
        mobile: form.mobile,
        date_of_birth: form.date_of_birth,
        password,
      });
      toastSuccess("Account created! Sign in with your mobile number and password.");
      onDone?.(form.mobile);
    } catch (err) {
      if (err?.errors) setFieldErrors(err.errors);
      toastApiError(err, "Could not create account.");
    } finally {
      setLoading(false);
    }
  }

  if (step === "details") {
    return (
      <form onSubmit={requestCode}>
        <AutofillDecoy />
        <label style={labelStyle}>Full name</label>
        <div className="aw-field" style={{ ...fieldWrap(false), marginBottom: 16 }}>
          <input style={bareInput} value={form.full_name}
            onChange={e => setForm(f => ({ ...f, full_name: e.target.value }))}
            placeholder="e.g. Rohan Sharma" required />
        </div>

        <label style={labelStyle}>Email</label>
        <div className="aw-field" style={{ ...fieldWrap(!!fieldErrors.email), marginBottom: 16 }}>
          <input style={bareInput} type="email" value={form.email}
            onChange={e => { setForm(f => ({ ...f, email: e.target.value })); if (fieldErrors.email) setFieldErrors(er => ({ ...er, email: undefined })); }}
            placeholder="you@example.com" required />
        </div>
        {fieldErrors.email && <div style={{ color: "var(--color-error)", fontSize: 12, marginTop: -12, marginBottom: 12 }}>{fieldErrors.email}</div>}
        <p style={{ marginTop: -12, marginBottom: 16, fontSize: 12, color: "var(--color-text-muted)" }}>
          We'll send a verification code here.
        </p>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 16 }}>
          <div>
            <label style={labelStyle}>Mobile Number</label>
            <div className="aw-field" style={fieldWrap(!!fieldErrors.mobile)}>
              <input style={bareInput} type="tel" inputMode="numeric" maxLength={10} value={form.mobile}
                onChange={e => { setForm(f => ({ ...f, mobile: sanitizeMobileInput(e.target.value) })); if (fieldErrors.mobile) setFieldErrors(er => ({ ...er, mobile: undefined })); }}
                placeholder="98xxxxxxxx" required />
            </div>
            {fieldErrors.mobile && <div style={{ color: "var(--color-error)", fontSize: 12, marginTop: 5 }}>{fieldErrors.mobile}</div>}
          </div>
          <div>
            <label style={labelStyle}>Date of birth</label>
            <div className="aw-field" style={fieldWrap(false)}>
              <input style={bareInput} type="date" value={form.date_of_birth}
                onChange={e => setForm(f => ({ ...f, date_of_birth: e.target.value }))} />
            </div>
          </div>
        </div>

        <button className="btn-primary aw-submit-btn" type="submit" disabled={loading}
          style={{ width: "100%", marginTop: 6, padding: "12px 0", fontSize: 14, fontWeight: 700 }}>
          {loading ? "Sending code…" : "Send verification code"}
        </button>

        <p style={{ marginTop: 18, textAlign: "center", fontSize: 13, color: "var(--color-text-muted)" }}>
          Already registered?{" "}
          <button type="button" className="aw-link-btn" onClick={onCancel}
            style={{ background: "none", border: "none", color: "var(--color-primary)", fontWeight: 700, cursor: "pointer", fontSize: "inherit" }}>
            Sign in
          </button>
        </p>
      </form>
    );
  }

  if (step === "code") {
    return (
      <form onSubmit={verifyCode}>
        <p style={{ fontSize: 13.5, color: "var(--color-text)", marginBottom: 18 }}>
          Enter the 6-digit code we sent to <strong>{form.email}</strong>.
        </p>
        <label style={labelStyle}>Verification Code</label>
        <div className="aw-field" style={{ ...fieldWrap(false), marginBottom: 16 }}>
          <input style={{ ...bareInput, letterSpacing: "0.3em", fontSize: 20, textAlign: "center" }}
            value={code} onChange={e => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
            inputMode="numeric" maxLength={6} placeholder="••••••" required autoFocus />
        </div>
        <button className="btn-primary aw-submit-btn" type="submit" disabled={loading || code.length < 6}
          style={{ width: "100%", padding: "12px 0", fontSize: 14, fontWeight: 700 }}>
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
    );
  }

  // step === "password"
  return (
    <form onSubmit={createAccount}>
      <AutofillDecoy />
      <NewPasswordFields
        password={password} onPasswordChange={e => setPassword(e.target.value)}
        confirmPassword={confirmPassword} onConfirmPasswordChange={e => setConfirmPassword(e.target.value)}
        errors={fieldErrors}
      />
      <button className="btn-primary aw-submit-btn" type="submit" disabled={loading}
        style={{ width: "100%", marginTop: 6, padding: "12px 0", fontSize: 14, fontWeight: 700 }}>
        {loading ? "Creating account…" : "Create Account"}
      </button>
    </form>
  );
}
