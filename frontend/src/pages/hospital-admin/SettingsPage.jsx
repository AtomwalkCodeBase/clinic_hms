/**
 * pages/hospital-admin/SettingsPage.jsx
 * Hospital admin: account info + clinical configuration (fee ownership).
 */
import { useState, useEffect } from "react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useAuth }   from "../../hooks/useAuth";
import { useToast }  from "../../hooks/useToast";
import apiClient     from "../../services/api.client";

const labelStyle = { display: "block", fontSize: 13, fontWeight: 600, marginBottom: 6 };

function InfoRow({ label, value, mono }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 0", borderBottom: "1px solid var(--color-border)" }}>
      <span style={{ fontSize: 13, color: "var(--color-text-muted)", fontWeight: 600 }}>{label}</span>
      <span style={{ fontSize: 14, fontFamily: mono ? "monospace" : "inherit" }}>{value || "—"}</span>
    </div>
  );
}

// Toggle switch component
function Toggle({ checked, onChange, disabled }) {
  return (
    <button
      type="button"
      onClick={() => !disabled && onChange(!checked)}
      style={{
        position: "relative", width: 44, height: 24, borderRadius: 12, border: "none",
        background: checked ? "var(--color-primary)" : "var(--color-border)",
        cursor: disabled ? "not-allowed" : "pointer",
        transition: "background 0.2s", flexShrink: 0,
        opacity: disabled ? 0.6 : 1,
      }}
      aria-checked={checked}
      role="switch"
    >
      <span style={{
        position: "absolute", top: 3, left: checked ? 23 : 3,
        width: 18, height: 18, borderRadius: "50%", background: "#fff",
        boxShadow: "0 1px 4px rgba(0,0,0,0.2)",
        transition: "left 0.2s",
      }} />
    </button>
  );
}

export default function SettingsPage() {
  const { user, logout }           = useAuth();
  const { toastSuccess, toastApiError } = useToast();

  const [settings, setSettings]   = useState(null);   // { fee_ownership }
  const [saving,   setSaving]      = useState(false);

  useEffect(() => {
    apiClient.get("/org/settings/")
      .then(r => setSettings(r.data?.data ?? r.data))
      .catch(() => {});   // non-fatal; section stays hidden
  }, []);

  async function saveFeeOwnership(newValue) {
    setSaving(true);
    try {
      const r = await apiClient.patch("/org/settings/", { fee_ownership: newValue });
      setSettings(r.data?.data ?? r.data);
      toastSuccess("Fee configuration saved.");
    } catch (e) {
      toastApiError(e);
    } finally {
      setSaving(false);
    }
  }

  const hospitalControls = settings?.fee_ownership === "hospital";

  return (
    <AppShell>
      <PageShell title="Settings">
        <div style={{ maxWidth: 620 }}>

          {/* ── Account info ──────────────────────────────────────── */}
          <div className="card" style={{ padding: 28, marginBottom: 20 }}>
            <h2 style={{ fontSize: 16, fontWeight: 700, marginBottom: 20 }}>Account</h2>
            <InfoRow label="Email"     value={user?.email} />
            <InfoRow label="Role"      value="Hospital Admin" />
            <InfoRow label="Hospital Code" value={settings?.subdomain} mono />
            <InfoRow label="Tenant ID" value={user?.tenant_id} />
            <InfoRow label="Database"  value={user?.db_name} mono />
            <InfoRow label="Plan"      value={user?.license_tier} />
          </div>

          {/* ── Clinical configuration ────────────────────────────── */}
          {settings && (
            <div className="card" style={{ padding: 28, marginBottom: 20 }}>
              <h2 style={{ fontSize: 16, fontWeight: 700, marginBottom: 4 }}>Clinical Configuration</h2>
              <p style={{ fontSize: 13, color: "var(--color-text-muted)", marginBottom: 24 }}>
                These settings apply across your entire hospital.
              </p>

              {/* Fee ownership toggle */}
              <div style={{
                borderRadius: 14, border: "1.5px solid var(--color-border)",
                overflow: "hidden",
              }}>
                <div style={{
                  padding: "14px 18px", background: "var(--color-table-header)",
                  borderBottom: "1px solid var(--color-border)",
                  display: "flex", alignItems: "center", gap: 8,
                }}>
                  <span style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--color-text-muted)" }}>
                    Consultation Fee Ownership
                  </span>
                </div>

                {/* Option A — doctor self-configures */}
                <div
                  onClick={() => !saving && saveFeeOwnership("doctor")}
                  style={{
                    padding: "16px 18px", cursor: saving ? "not-allowed" : "pointer",
                    display: "flex", alignItems: "flex-start", gap: 14,
                    background: !hospitalControls ? "var(--color-primary-light)" : "var(--color-surface)",
                    borderBottom: "1px solid var(--color-border)",
                    transition: "background 0.15s",
                  }}
                >
                  <div style={{
                    width: 18, height: 18, borderRadius: "50%", flexShrink: 0, marginTop: 1,
                    border: `2px solid ${!hospitalControls ? "var(--color-primary)" : "var(--color-border)"}`,
                    background: !hospitalControls ? "var(--color-primary)" : "transparent",
                    display: "flex", alignItems: "center", justifyContent: "center",
                  }}>
                    {!hospitalControls && <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#fff", display: "block" }} />}
                  </div>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: "var(--color-text)", marginBottom: 2 }}>
                      Doctor self-configures
                    </div>
                    <div style={{ fontSize: 12, color: "var(--color-text-muted)", lineHeight: 1.5 }}>
                      Each doctor sets their own consultation fee from their profile after login. The fee they set is shown to patients on the booking page.
                    </div>
                  </div>
                </div>

                {/* Option B — hospital controls */}
                <div
                  onClick={() => !saving && saveFeeOwnership("hospital")}
                  style={{
                    padding: "16px 18px", cursor: saving ? "not-allowed" : "pointer",
                    display: "flex", alignItems: "flex-start", gap: 14,
                    background: hospitalControls ? "var(--color-primary-light)" : "var(--color-surface)",
                    transition: "background 0.15s",
                  }}
                >
                  <div style={{
                    width: 18, height: 18, borderRadius: "50%", flexShrink: 0, marginTop: 1,
                    border: `2px solid ${hospitalControls ? "var(--color-primary)" : "var(--color-border)"}`,
                    background: hospitalControls ? "var(--color-primary)" : "transparent",
                    display: "flex", alignItems: "center", justifyContent: "center",
                  }}>
                    {hospitalControls && <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#fff", display: "block" }} />}
                  </div>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: "var(--color-text)", marginBottom: 2 }}>
                      Hospital controls
                    </div>
                    <div style={{ fontSize: 12, color: "var(--color-text-muted)", lineHeight: 1.5 }}>
                      The hospital admin sets the consultation fee when registering a doctor and can edit it anytime. The fee field is read-only for doctors.
                    </div>
                  </div>
                </div>
              </div>

              {saving && (
                <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 10 }}>Saving…</div>
              )}
            </div>
          )}

          {/* ── Session ───────────────────────────────────────────── */}
          <div className="card" style={{ padding: 28 }}>
            <h2 style={{ fontSize: 16, fontWeight: 700, marginBottom: 12 }}>Session</h2>
            <p style={{ fontSize: 14, color: "var(--color-text-muted)", marginBottom: 16 }}>
              Signing out will clear your session and return you to the login page.
            </p>
            <button onClick={logout} style={{
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
