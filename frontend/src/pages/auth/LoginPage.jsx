/**
 * pages/auth/LoginPage.jsx
 * -------------------------
 * Unified login page with three tabs:
 *   - Staff Login    (email + password + hospital subdomain)
 *   - Platform Admin (username + password, no subdomain)
 *   - Patient Login  (AWPID + password)
 *
 * Premium split-screen layout: dark hero brand panel on the left,
 * sign-in card on the right. Matches the app-wide "Private Practice"
 * theme (deep green + cream + gold, Fraunces serif display type).
 */

import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useAuth }    from "../../hooks/useAuth";
import { useToast }   from "../../hooks/useToast";
import { ROLES }      from "../../constants/roles";
import APP_CONFIG     from "../../config/app.config";
import API_ENDPOINTS  from "../../config/api.config";
import { ROUTES }     from "../../config/routes.config";
import { sanitizeMobileInput, isValidMobile } from "../../utils/validation";
import { getThemeById } from "../../config/themes.config";
import { deriveThemeVars } from "../../utils/theme";

// The login screen is shared brand identity, shown before any user is
// signed in — it must always render in "Emerald Glass", never whatever
// in-app theme a previous user on this browser last picked. ThemeProvider
// applies the active theme's CSS vars globally on <html>, so we re-pin them
// back to Emerald Glass right here on the root wrapper; CSS custom
// properties cascade, so this override wins for this whole subtree without
// touching ThemeProvider or any other page.
const FIXED_BRAND_VARS = deriveThemeVars(getThemeById("emerald"));

const TABS = [
  { key: "staff",    label: "Staff" },
  { key: "platform", label: "Atomwalk Admin" },
  { key: "patient",  label: "Patient" },
];

function getDefaultRoute(role) {
  const map = {
    [ROLES.PLATFORM_ADMIN]: "/platform/dashboard",
    [ROLES.HOSPITAL_ADMIN]: "/admin/dashboard",
    [ROLES.DOCTOR]:         "/doctor/dashboard",
    [ROLES.NURSE]:          "/nurse/dashboard",
    [ROLES.FRONT_DESK]:     "/front-desk/dashboard",
    [ROLES.LAB_TECH]:       "/lab/dashboard",
    [ROLES.PHARMACIST]:     "/pharmacist/dashboard",
    [ROLES.PATIENT]:        "/patient/dashboard",
  };
  return map[role] || "/";
}

// Small inline icons (no extra dependency) ----------------------------------
const IconMail = (props) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <rect x="2" y="4" width="20" height="16" rx="2" />
    <path d="m2 7 10 6 10-6" />
  </svg>
);
const IconLock = (props) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <rect x="4" y="11" width="16" height="10" rx="2" />
    <path d="M8 11V7a4 4 0 0 1 8 0v4" />
  </svg>
);
const IconUser = (props) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <circle cx="12" cy="8" r="4" />
    <path d="M4 21v-1a8 8 0 0 1 16 0v1" />
  </svg>
);
const IconBadge = (props) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M12 2 3 6v6c0 5 4 8.5 9 10 5-1.5 9-5 9-10V6l-9-4Z" />
  </svg>
);
const IconEye = (props) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8Z" />
    <circle cx="12" cy="12" r="3" />
  </svg>
);
const IconEyeOff = (props) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-3.16 4.19M6.5 6.61C3.9 8.36 1 12 1 12s4 8 11 8a9.4 9.4 0 0 0 4.24-1M14.12 14.12A3 3 0 1 1 9.88 9.88" />
    <path d="M1 1l22 22" />
  </svg>
);
const IconPhone = (props) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <rect x="6" y="2" width="12" height="20" rx="2" />
    <path d="M11 18h2" />
  </svg>
);
const IconCalendar = (props) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <rect x="3" y="4" width="18" height="18" rx="2" />
    <path d="M16 2v4M8 2v4M3 10h18" />
  </svg>
);

// Shared field wrapper — MUST live at module scope, not inside LoginPage.
// A component defined inside another component's body gets a fresh function
// reference on every render, so React treats it as a brand-new component type
// each time and remounts its DOM (including the <input>) on every keystroke —
// that's what was causing focus to drop after every character.
const fieldWrap = (hasError) => ({
  display: "flex",
  alignItems: "center",
  gap: 10,
  border: `1.5px solid ${hasError ? "var(--color-error)" : "var(--color-border)"}`,
  borderRadius: "var(--radius-input)",
  padding: "0 14px",
  background: "var(--color-bg)",
  transition: "border-color 160ms ease, box-shadow 160ms ease, background 160ms ease",
});

// Same reasoning as fieldWrap above — must live at module scope so
// PasswordField (also module-scope) can see it, and so it isn't recreated
// (and inputs remounted) on every LoginPage render.
const bareInput = {
  outline: "none",
  border: "none",
  background: "transparent",
  padding: "11px 0",
  fontSize: 14,
  width: "100%",
  color: "var(--color-text)",
  fontFamily: "inherit",
};

function Field({ icon: Icon, error, children }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div className="aw-field" style={fieldWrap(!!error)}>
        <Icon style={{ color: "var(--color-text-muted)", flexShrink: 0 }} />
        {children}
      </div>
      {error && (
        <div style={{ color: "var(--color-error)", fontSize: 12, marginTop: 5 }}>{error}</div>
      )}
    </div>
  );
}

/**
 * Password input with a show/hide toggle — lets people check exactly what
 * they've typed (autofill, caps lock, stray spaces, etc.) before submitting,
 * instead of guessing from a row of dots.
 */
function PasswordField({ value, onChange, error, placeholder = "••••••••", ...rest }) {
  const [visible, setVisible] = useState(false);
  return (
    <div style={{ marginBottom: 16 }}>
      <div className="aw-field" style={fieldWrap(!!error)}>
        <IconLock style={{ color: "var(--color-text-muted)", flexShrink: 0 }} />
        <input
          style={bareInput} type={visible ? "text" : "password"} value={value}
          onChange={onChange} placeholder={placeholder} {...rest}
        />
        <button
          type="button"
          onClick={() => setVisible(v => !v)}
          aria-label={visible ? "Hide password" : "Show password"}
          title={visible ? "Hide password" : "Show password"}
          style={{
            background: "none", border: "none", padding: 4, cursor: "pointer",
            color: "var(--color-text-muted)", display: "flex", alignItems: "center", flexShrink: 0,
          }}
        >
          {visible ? <IconEyeOff /> : <IconEye />}
        </button>
      </div>
      {error && (
        <div style={{ color: "var(--color-error)", fontSize: 12, marginTop: 5 }}>{error}</div>
      )}
    </div>
  );
}

export default function LoginPage() {
  const navigate = useNavigate();
  const { loginStaff, loginPatient, loginPlatform } = useAuth();
  const { toastSuccess, toastApiError } = useToast();

  const [tab,         setTab]         = useState("staff");
  const [loading,     setLoading]     = useState(false);
  const [fieldErrors, setFieldErrors] = useState({});

  // Staff
  const [mobile,   setMobile]   = useState("");
  const [password, setPassword] = useState("");
  // Employee-ID login (enterprise hospitals with an HR/payroll ID scheme) —
  // needs the hospital's subdomain too, since employee IDs aren't globally
  // unique the way mobile numbers are. See docs/onboarding_auth_rbac_architecture.md 3.1.2.
  const [useEmployeeId, setUseEmployeeId] = useState(false);
  const [subdomain,     setSubdomain]     = useState("");
  const [employeeId,    setEmployeeId]    = useState("");

  // Platform admin
  const [platUsername, setPlatUsername] = useState("");
  const [platPassword, setPlatPassword] = useState("");

  // Patient
  const [awpid,       setAwpid]       = useState("");
  const [patientPass, setPatientPass] = useState("");
  const [showRegister, setShowRegister] = useState(false);
  const [regForm, setRegForm] = useState({
    full_name: "", mobile: "", email: "", date_of_birth: "", password: "",
  });

  function switchTab(key) {
    setTab(key);
    setFieldErrors({});
  }

  async function handleStaffLogin(e) {
    e.preventDefault();
    setFieldErrors({});
    setLoading(true);
    try {
      const credentials = useEmployeeId ? { subdomain, employeeId } : mobile;
      const result = await loginStaff(credentials, password);
      toastSuccess("Signed in successfully.");
      if (result.must_change_password) {
        navigate("/change-password");
      } else {
        navigate("/");
      }
    } catch (err) {
      if (err?.errors) setFieldErrors(err.errors);
      toastApiError(err, "Invalid credentials.");
    } finally {
      setLoading(false);
    }
  }

  async function handlePlatformLogin(e) {
    e.preventDefault();
    setFieldErrors({});
    setLoading(true);
    try {
      await loginPlatform(platUsername, platPassword);
      toastSuccess("Signed in as platform admin.");
      navigate("/platform/dashboard");
    } catch (err) {
      if (err?.errors) setFieldErrors(err.errors);
      toastApiError(err, "Invalid credentials.");
    } finally {
      setLoading(false);
    }
  }

  async function handlePatientRegister(e) {
    e.preventDefault();
    if (!isValidMobile(regForm.mobile)) {
      setFieldErrors({ mobile: "Enter a valid 10-digit mobile number." });
      return;
    }
    setLoading(true);
    try {
      const { publicClient } = await import("../../services/api.client");
      await publicClient.post(API_ENDPOINTS.PORTAL.REGISTER, regForm);
      toastSuccess("Account created! Sign in with your mobile number and password.");
      setAwpid(regForm.mobile);
      setShowRegister(false);
    } catch (err) {
      toastApiError(err, "Could not create account.");
    } finally {
      setLoading(false);
    }
  }

  async function handlePatientLogin(e) {
    e.preventDefault();
    setFieldErrors({});
    setLoading(true);
    try {
      await loginPatient(awpid, patientPass);
      toastSuccess("Signed in successfully.");
      navigate("/");
    } catch (err) {
      if (err?.errors) setFieldErrors(err.errors);
      toastApiError(err, "Invalid credentials.");
    } finally {
      setLoading(false);
    }
  }

  // ---- shared field styles --------------------------------------------
  const labelStyle = {
    display: "block",
    fontSize: 11,
    fontWeight: 700,
    letterSpacing: "0.06em",
    textTransform: "uppercase",
    marginBottom: 7,
    color: "var(--color-text-secondary)",
  };

  return (
    <div style={{ minHeight: "100vh", display: "flex", background: "var(--color-bg)", ...FIXED_BRAND_VARS }}>
      <style>{`
        .aw-field:focus-within {
          border-color: var(--color-primary) !important;
          background: var(--color-surface) !important;
          box-shadow: 0 0 0 3px var(--color-primary-light);
        }
        .aw-tab-btn { transition: all 160ms ease; }
        .aw-submit-btn {
          transition: transform 140ms ease, box-shadow 140ms ease, opacity 140ms ease;
          box-shadow: 0 10px 24px rgba(12, 42, 31, 0.22);
        }
        .aw-submit-btn:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 14px 30px rgba(12, 42, 31, 0.30); }
        .aw-submit-btn:active:not(:disabled) { transform: translateY(0); }
        .aw-link-btn { position: relative; }
        .aw-link-btn::after {
          content: ""; position: absolute; left: 0; right: 0; bottom: -2px; height: 1px;
          background: var(--color-primary); transform: scaleX(0); transform-origin: left;
          transition: transform 160ms ease;
        }
        .aw-link-btn:hover::after { transform: scaleX(1); }
        @media (max-width: 880px) {
          .aw-hero-panel { display: none !important; }
        }
      `}</style>

      {/* ============ LEFT — brand hero panel ============ */}
      <div className="aw-hero-panel" style={{
        flex: "0 0 42%",
        position: "relative",
        overflow: "hidden",
        background: "radial-gradient(circle at 18% 14%, var(--color-hero-2) 0%, var(--color-hero) 48%, color-mix(in srgb, var(--color-hero) 65%, black 35%) 100%)",
        color: "var(--color-hero-text)",
        padding: "64px 56px",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
      }}>
        {/* faint grain / dot texture */}
        <div style={{
          position: "absolute", inset: 0, opacity: 0.06, pointerEvents: "none",
          backgroundImage: "radial-gradient(rgba(255,255,255,.6) 1px, transparent 1px)",
          backgroundSize: "3px 3px",
        }} />
        {/* soft gold glow accent */}
        <div style={{
          position: "absolute", width: 420, height: 420, borderRadius: "50%",
          background: "radial-gradient(circle, color-mix(in srgb, var(--color-accent) 16%, transparent) 0%, transparent 70%)",
          top: -120, right: -140, pointerEvents: "none",
        }} />

        <div style={{ position: "relative" }}>
          <img src="/branding/atomwalk-full.png" alt="Atomwalk Technologies"
            style={{ height: 40, width: "auto", objectFit: "contain", display: "block" }} />
          <div style={{ marginTop: 14 }}>
            <div style={{ fontFamily: "var(--font-display)", fontSize: 19, fontWeight: 600 }}>
              {APP_CONFIG.APP_NAME}
            </div>
            <div style={{ fontSize: 10.5, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--color-hero-muted)", marginTop: 2 }}>
              Hospital Management System
            </div>
          </div>
        </div>

        <div style={{ position: "relative" }}>
          <div style={{
            fontSize: 11, fontWeight: 700, letterSpacing: "0.14em", textTransform: "uppercase",
            color: "var(--color-accent)", marginBottom: 16,
          }}>
            Cared, coordinated
          </div>
          <h1 style={{
            fontFamily: "var(--font-display)", fontWeight: 600, fontSize: 38,
            lineHeight: 1.15, margin: 0, maxWidth: 420,
          }}>
            One system for every step of the patient journey.
          </h1>
          <p style={{
            fontSize: 14.5, color: "color-mix(in srgb, var(--color-hero-text) 55%, var(--color-hero-muted) 45%)", lineHeight: 1.65, marginTop: 18, maxWidth: 380,
          }}>
            From booking to consultation to prescription — front desk, nurses, doctors
            and patients, all working off the same live record.
          </p>

          <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 30 }}>
            {[
              "Real-time queues across every branch",
              "Voice-assisted consultation notes",
              "A patient portal your patients actually use",
            ].map((line) => (
              <div key={line} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--color-accent)", flexShrink: 0 }} />
                <span style={{ fontSize: 13.5, color: "color-mix(in srgb, var(--color-hero-text) 70%, var(--color-hero-muted) 30%)" }}>{line}</span>
              </div>
            ))}
          </div>
        </div>

        <div style={{
          position: "relative", borderTop: "1px solid rgba(255,255,255,.14)",
          paddingTop: 20, fontSize: 12, color: "var(--color-hero-muted)",
        }}>
          Need help? <span style={{ color: "#fff" }}>{APP_CONFIG.SUPPORT_EMAIL}</span>
        </div>
      </div>

      {/* ============ RIGHT — sign-in card ============ */}
      <div style={{
        flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
        padding: 24,
      }}>
        <div style={{ width: "100%", maxWidth: 400 }}>

          {/* Mobile-only compact brand row (hero panel hides under 880px) */}
          <div className="aw-hero-panel" style={{ display: "none" }} />

          <div style={{ marginBottom: 30 }}>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--color-accent)" }}>
              Welcome back
            </div>
            <h2 style={{ fontFamily: "var(--font-display)", fontWeight: 600, fontSize: 26, margin: "6px 0 0", color: "var(--color-text)" }}>
              Sign in to your workspace
            </h2>
            <p style={{ fontSize: 13, color: "var(--color-text-muted)", marginTop: 6 }}>
              Choose your account type below to continue.
            </p>
          </div>

          {/* Card */}
          <div style={{
            background: "var(--color-surface)", borderRadius: "var(--radius-card)",
            border: "1px solid var(--color-border)", boxShadow: "var(--shadow-card)",
            padding: 30,
          }}>

            {/* Tabs */}
            <div style={{
              display: "flex", background: "var(--color-bg)",
              borderRadius: "var(--radius-button)", padding: 4, marginBottom: 26, gap: 2,
            }}>
              {TABS.map(t => (
                <button key={t.key} className="aw-tab-btn" onClick={() => switchTab(t.key)}
                  style={{
                    flex: 1, padding: "8px 4px",
                    border: "none", borderRadius: "var(--radius-button)",
                    background: tab === t.key ? "var(--color-surface)" : "transparent",
                    color: tab === t.key ? "var(--color-primary)" : "var(--color-text-muted)",
                    fontWeight: tab === t.key ? 700 : 500,
                    fontSize: 12,
                    boxShadow: tab === t.key ? "var(--shadow-card)" : "none",
                    cursor: "pointer",
                    whiteSpace: "nowrap",
                  }}>{t.label}</button>
              ))}
            </div>

            {/* Staff Login */}
            {tab === "staff" && (
              <form onSubmit={handleStaffLogin}>
                {useEmployeeId ? (
                  <>
                    <label style={labelStyle}>Hospital Code</label>
                    <Field icon={IconBadge} error={fieldErrors.subdomain}>
                      <input style={bareInput} value={subdomain}
                        onChange={e => setSubdomain(e.target.value)}
                        placeholder="e.g. apollo-delhi" required />
                    </Field>

                    <label style={labelStyle}>Employee ID</label>
                    <Field icon={IconUser} error={fieldErrors.employee_id}>
                      <input style={bareInput} value={employeeId}
                        onChange={e => setEmployeeId(e.target.value)}
                        placeholder="e.g. EMP-045" required />
                    </Field>
                  </>
                ) : (
                  <>
                    <label style={labelStyle}>Mobile Number</label>
                    <Field icon={IconPhone} error={fieldErrors.mobile}>
                      <input style={bareInput} type="tel" value={mobile}
                        onChange={e => setMobile(e.target.value)}
                        placeholder="98xxxxxxxx" required />
                    </Field>
                  </>
                )}

                <label style={labelStyle}>Password</label>
                <PasswordField value={password} error={fieldErrors.password}
                  onChange={e => setPassword(e.target.value)} required />

                <p style={{ marginTop: -8, marginBottom: 16 }}>
                  <button type="button" className="aw-link-btn"
                    onClick={() => setUseEmployeeId(v => !v)}
                    style={{ background: "none", border: "none", padding: 0, fontSize: 12.5, color: "var(--color-text-muted)", fontWeight: 600, cursor: "pointer" }}>
                    {useEmployeeId ? "Sign in with mobile number instead" : "Sign in with employee ID instead"}
                  </button>
                </p>

                <p style={{ textAlign: "right", marginTop: -8, marginBottom: 16 }}>
                  <Link to={ROUTES.FORGOT_PASSWORD} className="aw-link-btn"
                    style={{ fontSize: 12.5, color: "var(--color-text-muted)", fontWeight: 600 }}>
                    Forgot password?
                  </Link>
                </p>

                <button className="btn-primary aw-submit-btn" type="submit" disabled={loading}
                  style={{ width: "100%", marginTop: 6, padding: "12px 0", fontSize: 14, fontWeight: 700 }}>
                  {loading ? "Signing in…" : "Sign In"}
                </button>
              </form>
            )}

            {/* Platform Admin Login */}
            {tab === "platform" && (
              <form onSubmit={handlePlatformLogin}>
                <div style={{
                  background: "var(--color-accent-light)", borderRadius: 10, padding: "11px 14px",
                  marginBottom: 20, fontSize: 12.5, color: "var(--color-text-secondary)",
                  borderLeft: "3px solid var(--color-accent)",
                }}>
                  Atomwalk platform administrators only. Use your superuser credentials.
                </div>

                <label style={labelStyle}>Username or Email</label>
                <Field icon={IconUser} error={fieldErrors.username}>
                  <input style={bareInput} value={platUsername}
                    onChange={e => setPlatUsername(e.target.value)}
                    placeholder="admin or admin@example.com" required autoComplete="username" />
                </Field>

                <label style={labelStyle}>Password</label>
                <PasswordField value={platPassword}
                  onChange={e => setPlatPassword(e.target.value)}
                  required autoComplete="current-password" />

                <button className="btn-primary aw-submit-btn" type="submit" disabled={loading}
                  style={{ width: "100%", marginTop: 6, padding: "12px 0", fontSize: 14, fontWeight: 700 }}>
                  {loading ? "Signing in…" : "Sign In as Platform Admin"}
                </button>
              </form>
            )}

            {/* Patient Login */}
            {tab === "patient" && !showRegister && (
              <form onSubmit={handlePatientLogin}>
                <label style={labelStyle}>Mobile Number or Patient ID (AWPID)</label>
                <Field icon={IconBadge}>
                  <input style={bareInput} value={awpid}
                    onChange={e => setAwpid(e.target.value)}
                    placeholder="98xxxxxxxx" required />
                </Field>

                <label style={labelStyle}>Password</label>
                <PasswordField value={patientPass}
                  onChange={e => setPatientPass(e.target.value)} required />

                <p style={{ textAlign: "right", marginTop: -8, marginBottom: 16 }}>
                  <Link to={ROUTES.FORGOT_PASSWORD} className="aw-link-btn"
                    style={{ fontSize: 12.5, color: "var(--color-text-muted)", fontWeight: 600 }}>
                    Forgot password?
                  </Link>
                </p>

                <button className="btn-primary aw-submit-btn" type="submit" disabled={loading}
                  style={{ width: "100%", marginTop: 6, padding: "12px 0", fontSize: 14, fontWeight: 700 }}>
                  {loading ? "Signing in…" : "Sign In"}
                </button>

                <p style={{ marginTop: 18, textAlign: "center", fontSize: 13, color: "var(--color-text-muted)" }}>
                  New patient?{" "}
                  <button type="button" className="aw-link-btn" onClick={() => setShowRegister(true)}
                    style={{ background: "none", border: "none", color: "var(--color-primary)", fontWeight: 700, cursor: "pointer", fontSize: "inherit" }}>
                    Create an account
                  </button>
                </p>
              </form>
            )}

            {/* Patient Register */}
            {tab === "patient" && showRegister && (
              <form onSubmit={handlePatientRegister}>
                <label style={labelStyle}>Full name</label>
                <Field icon={IconUser}>
                  <input style={bareInput} value={regForm.full_name}
                    onChange={e => setRegForm(f => ({ ...f, full_name: e.target.value }))}
                    placeholder="e.g. Rohan Sharma" required />
                </Field>

                <label style={labelStyle}>Mobile Number</label>
                <Field icon={IconPhone} error={fieldErrors.mobile}>
                  <input style={bareInput} type="tel" inputMode="numeric" maxLength={10} value={regForm.mobile}
                    onChange={e => { setRegForm(f => ({ ...f, mobile: sanitizeMobileInput(e.target.value) })); if (fieldErrors.mobile) setFieldErrors(er => ({ ...er, mobile: undefined })); }}
                    placeholder="98xxxxxxxx" required />
                </Field>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                  <div>
                    <label style={labelStyle}>Email (optional)</label>
                    <Field icon={IconMail}>
                      <input style={bareInput} type="email" value={regForm.email}
                        onChange={e => setRegForm(f => ({ ...f, email: e.target.value }))}
                        placeholder="you@example.com" />
                    </Field>
                  </div>
                  <div>
                    <label style={labelStyle}>Date of birth</label>
                    <Field icon={IconCalendar}>
                      <input style={bareInput} type="date" value={regForm.date_of_birth}
                        onChange={e => setRegForm(f => ({ ...f, date_of_birth: e.target.value }))} />
                    </Field>
                  </div>
                </div>

                <label style={labelStyle}>Password</label>
                <PasswordField value={regForm.password}
                  onChange={e => setRegForm(f => ({ ...f, password: e.target.value }))}
                  placeholder="Choose a password" required minLength={6} />

                <button className="btn-primary aw-submit-btn" type="submit" disabled={loading}
                  style={{ width: "100%", marginTop: 6, padding: "12px 0", fontSize: 14, fontWeight: 700 }}>
                  {loading ? "Creating account…" : "Create Account"}
                </button>

                <p style={{ marginTop: 18, textAlign: "center", fontSize: 13, color: "var(--color-text-muted)" }}>
                  Already registered?{" "}
                  <button type="button" className="aw-link-btn" onClick={() => setShowRegister(false)}
                    style={{ background: "none", border: "none", color: "var(--color-primary)", fontWeight: 700, cursor: "pointer", fontSize: "inherit" }}>
                    Sign in
                  </button>
                </p>
              </form>
            )}

          </div>

          <p style={{ textAlign: "center", marginTop: 22, fontSize: 12.5, color: "var(--color-text-muted)" }}>
            Need help? {APP_CONFIG.SUPPORT_EMAIL}
          </p>
        </div>
      </div>
    </div>
  );
}
