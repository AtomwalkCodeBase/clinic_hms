/**
 * pages/hospital-admin/SettingsPage.jsx
 * Hospital admin: view account info. Editing via API TBD.
 */

import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useAuth }   from "../../hooks/useAuth";

export default function SettingsPage() {
  const { user, logout } = useAuth();

  return (
    <AppShell>
      <PageShell title="Settings">
        <div style={{ maxWidth: 600 }}>
          <div className="card" style={{ padding: 28, marginBottom: 20 }}>
            <h2 style={{ fontSize: 16, fontWeight: 700, marginBottom: 20 }}>Account</h2>
            <div style={{ display: "grid", gap: 14 }}>
              {[
                { label: "Email",       value: user?.email },
                { label: "Role",        value: "Hospital Admin" },
                { label: "Tenant ID",   value: user?.tenant_id },
                { label: "Database",    value: user?.db_name },
                { label: "Plan",        value: user?.license_tier || "—" },
              ].map(({ label, value }) => (
                <div key={label} style={{ display: "flex", justifyContent: "space-between", padding: "10px 0", borderBottom: "1px solid var(--color-border)" }}>
                  <span style={{ fontSize: 13, color: "var(--color-text-muted)", fontWeight: 600 }}>{label}</span>
                  <span style={{ fontSize: 14, fontFamily: label === "Database" ? "monospace" : "inherit" }}>{value || "—"}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="card" style={{ padding: 28 }}>
            <h2 style={{ fontSize: 16, fontWeight: 700, marginBottom: 12 }}>Session</h2>
            <p style={{ fontSize: 14, color: "var(--color-text-muted)", marginBottom: 16 }}>
              Signing out will clear your session and return you to the login page.
            </p>
            <button onClick={logout}
              style={{
                padding: "9px 24px", borderRadius: 8,
                border: "1.5px solid var(--color-error)",
                background: "none", color: "var(--color-error)",
                cursor: "pointer", fontSize: 14, fontWeight: 600,
              }}>
              Sign Out
            </button>
          </div>
        </div>
      </PageShell>
    </AppShell>
  );
}
