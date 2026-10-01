/**
 * components/auth/NewPasswordFields.jsx
 * ---------------------------------------
 * Shared "choose a new password" pair — used everywhere a password is set
 * or reset: OTP-based forgot-password (staff + patient), patient
 * registration, staff first-login setup, and voluntary password change
 * from Settings. Each password field has its own show/hide toggle, and a
 * live match indicator appears under Confirm as soon as both fields have
 * content — so a typo is caught before submit instead of after a 400.
 *
 * Controlled component — parent owns the state:
 *   <NewPasswordFields
 *     password={password} onPasswordChange={setPassword}
 *     confirmPassword={confirm} onConfirmPasswordChange={setConfirm}
 *     errors={fieldErrors}
 *   />
 */

import { useState } from "react";
import { authBareInput as bareInput, authFieldWrap as fieldWrap, authLabelStyle as labelStyle } from "../../styles/formStyles";
import { IconEyeOff, IconEye, IconLock } from "./authIcons";




const IconCheck = (props) => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M20 6 9 17l-5-5" />
  </svg>
);
const IconX = (props) => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M18 6 6 18M6 6l12 12" />
  </svg>
);





function PwField({ value, onChange, placeholder, error, minLength, autoComplete }) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="aw-field" style={fieldWrap(!!error)}>
      <IconLock style={{ color: "var(--color-text-muted)", flexShrink: 0 }} />
      <input
        style={bareInput} type={visible ? "text" : "password"} value={value}
        onChange={onChange} placeholder={placeholder} minLength={minLength}
        autoComplete={autoComplete} required
      />
      <button type="button" onClick={() => setVisible(v => !v)}
        aria-label={visible ? "Hide password" : "Show password"}
        style={{ background: "none", border: "none", padding: 4, cursor: "pointer", color: "var(--color-text-muted)", display: "flex", alignItems: "center", flexShrink: 0 }}>
        {visible ? <IconEyeOff /> : <IconEye />}
      </button>
    </div>
  );
}

export default function NewPasswordFields({
  password, onPasswordChange,
  confirmPassword, onConfirmPasswordChange,
  errors = {},
}) {
  const showMatch = password.length > 0 && confirmPassword.length > 0;
  const matches = password === confirmPassword;

  return (
    <>
      <div style={{ marginBottom: 16 }}>
        <label style={labelStyle}>New Password</label>
        <PwField value={password} onChange={onPasswordChange} placeholder="Minimum 8 characters"
          minLength={8} autoComplete="new-password" error={errors.new_password} />
        {errors.new_password && (
          <div style={{ color: "var(--color-error)", fontSize: 12, marginTop: 5 }}>{errors.new_password}</div>
        )}
      </div>
      <div style={{ marginBottom: 16 }}>
        <label style={labelStyle}>Confirm New Password</label>
        <PwField value={confirmPassword} onChange={onConfirmPasswordChange} placeholder="Repeat your new password"
          autoComplete="new-password" error={errors.confirm_password} />
        {showMatch && (
          <div style={{
            display: "flex", alignItems: "center", gap: 5, marginTop: 6, fontSize: 12,
            color: matches ? "var(--color-success, #2e7d32)" : "var(--color-error)",
          }}>
            {matches ? <IconCheck /> : <IconX />}
            {matches ? "Passwords match" : "Passwords don't match"}
          </div>
        )}
        {errors.confirm_password && !showMatch && (
          <div style={{ color: "var(--color-error)", fontSize: 12, marginTop: 5 }}>{errors.confirm_password}</div>
        )}
      </div>
    </>
  );
}
