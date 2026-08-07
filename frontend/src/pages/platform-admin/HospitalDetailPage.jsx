/**
 * pages/platform-admin/HospitalDetailPage.jsx
 * ------------------------------------------------
 * Full profile view for one hospital — Overview / Users & Roles /
 * Subscription / Audit Log tabs. Reached by clicking a hospital on the
 * Hospitals table or Dashboard card list.
 */
import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, Building2, Users, KeyRound, Ban, CheckCircle2 } from "lucide-react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import apiClient     from "../../services/api.client";
import { useToast }  from "../../hooks/useToast";
import API_ENDPOINTS from "../../config/api.config";
import {
  TIERS, TIER_LABEL, SUB_STATUS_META,
  StatusBadge, SubStatusBadge, TierBadge, UsageBar, AuditLogTrail, fetchAuditLog,
} from "./shared";

const TABS = ["Overview", "Users & Roles", "Subscription", "Audit Log"];

const ROLE_LABELS = {
  hospital_admin: "Hospital Admin", doctor: "Doctor", nurse: "Nurse",
  front_desk: "Front Desk", lab_tech: "Lab Technician", pharmacist: "Pharmacist",
};

function OverviewTab({ tenant, overview, onChanged }) {
  const api = apiClient;
  const { toastSuccess, toastApiError } = useToast();
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({
    name: tenant.name || "", city: tenant.city || "", state: tenant.state || "",
    gstin: tenant.gstin || "", accreditations: tenant.accreditations || "", about: tenant.about || "",
  });
  const [saving, setSaving] = useState(false);

  function set(field, value) { setForm(f => ({ ...f, [field]: value })); }

  async function save() {
    setSaving(true);
    try {
      await api.patch(API_ENDPOINTS.PLATFORM.TENANT(tenant.id), form);
      toastSuccess("Hospital profile updated.");
      setEditing(false);
      onChanged();
    } catch (err) {
      toastApiError(err, "Failed to update profile.");
    } finally {
      setSaving(false);
    }
  }

  const inputStyle = {
    width: "100%", boxSizing: "border-box", padding: "8px 12px", borderRadius: 8,
    fontSize: 13.5, border: "1.5px solid var(--color-border)", background: "var(--color-surface)",
    color: "var(--color-text)", outline: "none",
  };
  const labelStyle = { display: "block", fontSize: 12, fontWeight: 600, marginBottom: 4, color: "var(--color-text-muted)" };

  if (!overview) return <div style={{ color: "var(--color-text-muted)", fontSize: 13.5 }}>Loading…</div>;
  const tiles = [
    { label: "Branches", value: overview.branches },
    { label: "Doctors", value: overview.doctors },
    { label: "Staff", value: overview.staff },
    { label: "Patients", value: overview.patients },
    { label: "Appointments Today", value: overview.appointments_today },
  ];
  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 14, marginBottom: 24 }}>
        {tiles.map(({ label, value }) => (
          <div key={label} className="card" style={{ padding: "16px 18px" }}>
            <div style={{ fontSize: 26, fontWeight: 800, color: "var(--color-primary)" }}>{value}</div>
            <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 2 }}>{label}</div>
          </div>
        ))}
      </div>

      <div className="card" style={{ padding: 20 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: editing ? 16 : 0 }}>
          <div className="dot-label">Hospital profile</div>
          {!editing && (
            <button onClick={() => setEditing(true)} className="btn-outline" style={{ fontSize: 12, padding: "6px 14px" }}>
              Edit
            </button>
          )}
        </div>

        {editing ? (
          <div style={{ display: "grid", gap: 14 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              <div>
                <label style={labelStyle}>Name</label>
                <input style={inputStyle} value={form.name} onChange={e => set("name", e.target.value)} />
              </div>
              <div>
                <label style={labelStyle}>GSTIN</label>
                <input style={inputStyle} value={form.gstin} onChange={e => set("gstin", e.target.value)} />
              </div>
              <div>
                <label style={labelStyle}>City</label>
                <input style={inputStyle} value={form.city} onChange={e => set("city", e.target.value)} />
              </div>
              <div>
                <label style={labelStyle}>State</label>
                <input style={inputStyle} value={form.state} onChange={e => set("state", e.target.value)} />
              </div>
            </div>
            <div>
              <label style={labelStyle}>Accreditations (comma-separated)</label>
              <input style={inputStyle} value={form.accreditations} onChange={e => set("accreditations", e.target.value)} placeholder="NABH, ISO 9001" />
            </div>
            <div>
              <label style={labelStyle}>About</label>
              <textarea style={{ ...inputStyle, minHeight: 70, resize: "vertical" }} value={form.about} onChange={e => set("about", e.target.value)} />
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button onClick={save} disabled={saving} className="btn-primary" style={{ fontSize: 13, padding: "8px 18px" }}>
                {saving ? "Saving…" : "Save"}
              </button>
              <button onClick={() => { setEditing(false); setForm({ name: tenant.name, city: tenant.city, state: tenant.state, gstin: tenant.gstin, accreditations: tenant.accreditations, about: tenant.about }); }}
                style={{ fontSize: 13, padding: "8px 18px", borderRadius: 8, border: "1.5px solid var(--color-border)", background: "none", cursor: "pointer" }}>
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 12, fontSize: 13.5 }}>
            <div><div className="stat-label">GSTIN</div><div style={{ marginTop: 2 }}>{tenant.gstin || "—"}</div></div>
            <div><div className="stat-label">Accreditations</div><div style={{ marginTop: 2 }}>{tenant.accreditations || "—"}</div></div>
            <div style={{ gridColumn: "1 / -1" }}><div className="stat-label">About</div><div style={{ marginTop: 2 }}>{tenant.about || "—"}</div></div>
          </div>
        )}
      </div>
    </div>
  );
}

function UsersTab({ tenantId }) {
  const api = apiClient;
  const { toastSuccess, toastApiError } = useToast();
  const [staff, setStaff] = useState(null);
  const [busyId, setBusyId] = useState(null);

  const fetchStaff = useCallback(async () => {
    try {
      const { data: res } = await api.get(API_ENDPOINTS.PLATFORM.TENANT_STAFF(tenantId));
      setStaff(res.data || []);
    } catch {
      setStaff([]);
    }
  }, [api, tenantId]);

  useEffect(() => { fetchStaff(); }, [fetchStaff]);

  async function toggleActive(s) {
    setBusyId(s.id);
    try {
      await api.patch(API_ENDPOINTS.PLATFORM.TENANT_STAFF_DETAIL(tenantId, s.id), { is_active: !s.is_active });
      toastSuccess(`${s.full_name} ${s.is_active ? "deactivated" : "reactivated"}.`);
      fetchStaff();
    } catch (err) {
      toastApiError(err, "Failed to update.");
    } finally {
      setBusyId(null);
    }
  }

  async function resetPassword(s) {
    setBusyId(s.id);
    try {
      const { data: res } = await api.post(API_ENDPOINTS.PLATFORM.TENANT_STAFF_RESET_PASSWORD(tenantId, s.id));
      navigator.clipboard?.writeText(res.data.temp_password).catch(() => {});
      toastSuccess(`Temp password for ${s.email || s.phone}: ${res.data.temp_password} (copied to clipboard)`, { duration: 15000 });
    } catch (err) {
      toastApiError(err, "Failed to reset password.");
    } finally {
      setBusyId(null);
    }
  }

  async function changeRole(s, newRole) {
    if (newRole === s.role) return;
    setBusyId(s.id);
    try {
      await api.patch(API_ENDPOINTS.PLATFORM.TENANT_STAFF_DETAIL(tenantId, s.id), { role: newRole });
      toastSuccess(`${s.full_name}'s role changed to ${ROLE_LABELS[newRole] || newRole}.`);
      fetchStaff();
    } catch (err) {
      toastApiError(err, "Failed to change role.");
    } finally {
      setBusyId(null);
    }
  }

  if (staff === null) return <div style={{ color: "var(--color-text-muted)", fontSize: 13.5 }}>Loading…</div>;
  if (staff.length === 0) return <div style={{ color: "var(--color-text-muted)", fontSize: 13.5 }}>No staff yet.</div>;

  return (
    <div className="card" style={{ padding: 0, overflow: "hidden" }}>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              {["Name", "Role", "Contact", "Status", "Last Login", "Actions"].map(h => (
                <th key={h} style={{ textAlign: "left", padding: "10px 14px", fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-text-muted)" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {staff.map(s => (
              <tr key={s.id} style={{ borderTop: "1px solid var(--color-border)" }}>
                <td style={{ padding: "10px 14px", fontSize: 13.5, fontWeight: 600 }}>{s.full_name}</td>
                <td style={{ padding: "10px 14px" }}>
                  <select value={s.role} disabled={busyId === s.id}
                    onChange={e => changeRole(s, e.target.value)}
                    style={{ padding: "5px 8px", borderRadius: 6, fontSize: 12.5, border: "1.5px solid var(--color-border)", background: "var(--color-surface)", color: "var(--color-text)" }}>
                    {Object.entries(ROLE_LABELS).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                  </select>
                </td>
                <td style={{ padding: "10px 14px", fontSize: 13.5, color: "var(--color-text-muted)" }}>{s.email || s.phone}</td>
                <td style={{ padding: "10px 14px" }}>
                  <span className={`badge badge--${s.is_active ? "success" : "error"}`}>{s.is_active ? "Active" : "Inactive"}</span>
                </td>
                <td style={{ padding: "10px 14px", fontSize: 12.5, color: "var(--color-text-muted)" }}>
                  {s.last_login ? new Date(s.last_login).toLocaleDateString() : "Never"}
                </td>
                <td style={{ padding: "10px 14px" }}>
                  <div style={{ display: "flex", gap: 6 }}>
                    <button onClick={() => resetPassword(s)} disabled={busyId === s.id}
                      title="Reset password"
                      style={{ background: "none", border: "1.5px solid var(--color-border)", borderRadius: 6, padding: "4px 8px", cursor: "pointer" }}>
                      <KeyRound size={13} />
                    </button>
                    <button onClick={() => toggleActive(s)} disabled={busyId === s.id}
                      title={s.is_active ? "Deactivate" : "Reactivate"}
                      style={{
                        background: "none", borderRadius: 6, padding: "4px 8px", cursor: "pointer",
                        border: `1.5px solid ${s.is_active ? "var(--color-error)" : "var(--color-success)"}`,
                        color: s.is_active ? "var(--color-error)" : "var(--color-success)",
                      }}>
                      {s.is_active ? <Ban size={13} /> : <CheckCircle2 size={13} />}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SubscriptionTab({ tenant, onChanged }) {
  const api = apiClient;
  const { toastSuccess, toastApiError } = useToast();
  const [tierPick, setTierPick] = useState(tenant.subscription?.license_tier || "starter");
  const [statusPick, setStatusPick] = useState(tenant.subscription?.status || "trial");
  const [saving, setSaving] = useState(false);
  const usage = tenant.usage || {};

  const selectStyle = {
    padding: "7px 10px", borderRadius: 8, fontSize: 13,
    border: "1.5px solid var(--color-border)", background: "var(--color-surface)",
    color: "var(--color-text)", outline: "none",
  };

  async function apply() {
    setSaving(true);
    try {
      const payload = {};
      if (tierPick !== tenant.subscription?.license_tier) payload.tier = tierPick;
      if (statusPick !== tenant.subscription?.status) payload.status = statusPick;
      if (Object.keys(payload).length === 0) { setSaving(false); return; }
      await api.patch(API_ENDPOINTS.PLATFORM.TENANT(tenant.id), payload);
      toastSuccess("Subscription updated.");
      onChanged();
    } catch (err) {
      toastApiError(err, "Failed to update subscription.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ display: "grid", gap: 20, maxWidth: 480 }}>
      <div style={{ display: "flex", gap: 24 }}>
        <UsageBar label="Doctors" used={usage.doctors} max={tenant.subscription?.max_doctors} />
        <UsageBar label="Branches" used={usage.branches} max={tenant.subscription?.max_branches} />
      </div>
      <div>
        <div className="stat-label" style={{ marginBottom: 6 }}>Tier</div>
        <select value={tierPick} onChange={e => setTierPick(e.target.value)} style={selectStyle}>
          {TIERS.map(t => <option key={t} value={t}>{TIER_LABEL[t].label}</option>)}
        </select>
      </div>
      <div>
        <div className="stat-label" style={{ marginBottom: 6 }}>Status</div>
        <select value={statusPick} onChange={e => setStatusPick(e.target.value)} style={selectStyle}>
          {Object.keys(SUB_STATUS_META).map(s => <option key={s} value={s}>{SUB_STATUS_META[s].label}</option>)}
        </select>
      </div>
      <button onClick={apply} disabled={saving} className="btn-primary" style={{ width: 140 }}>
        {saving ? "Saving…" : "Save changes"}
      </button>
    </div>
  );
}

function AuditTab({ tenantId }) {
  const [entries, setEntries] = useState(null);
  useEffect(() => { fetchAuditLog(tenantId).then(setEntries).catch(() => setEntries([])); }, [tenantId]);
  if (entries === null) return <div style={{ color: "var(--color-text-muted)", fontSize: 13.5 }}>Loading…</div>;
  return <div className="card" style={{ padding: 18 }}><AuditLogTrail entries={entries} /></div>;
}

export default function HospitalDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const api = apiClient;
  const [tenant, setTenant] = useState(null);
  const [overview, setOverview] = useState(null);
  const [tab, setTab] = useState("Overview");

  const fetchTenant = useCallback(async () => {
    try {
      const { data: res } = await api.get(API_ENDPOINTS.PLATFORM.TENANT(id));
      setTenant(res.data);
    } catch {
      setTenant(false);
    }
  }, [api, id]);

  useEffect(() => { fetchTenant(); }, [fetchTenant]);
  useEffect(() => {
    api.get(API_ENDPOINTS.PLATFORM.TENANT_OVERVIEW(id))
      .then(({ data: res }) => setOverview(res.data))
      .catch(() => setOverview(null));
  }, [api, id]);

  if (tenant === false) {
    return (
      <AppShell>
        <PageShell title="Hospital not found">
          <button onClick={() => navigate(-1)} className="btn-outline">← Back</button>
        </PageShell>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <PageShell title={tenant?.name || "Hospital"}>
        <button onClick={() => navigate(-1)}
          style={{ display: "flex", alignItems: "center", gap: 6, background: "none", border: "none", cursor: "pointer", color: "var(--color-text-muted)", fontSize: 13, marginBottom: 14, padding: 0 }}>
          <ArrowLeft size={14} /> Back
        </button>

        {tenant && (
          <>
            <div className="hero-card" style={{ marginBottom: 22 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                <div style={{ width: 48, height: 48, borderRadius: 12, background: "rgba(255,255,255,0.15)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <Building2 size={22} />
                </div>
                <div>
                  <div style={{ fontFamily: "var(--font-display)", fontSize: 22, fontWeight: 600 }}>{tenant.name}</div>
                  <div className="hero-sub">{tenant.city}{tenant.state ? `, ${tenant.state}` : ""} · Created {new Date(tenant.created_at).toLocaleDateString()}</div>
                </div>
              </div>
              <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
                <StatusBadge isActive={tenant.is_active} />
                <TierBadge tier={tenant.subscription?.license_tier} />
                <SubStatusBadge status={tenant.subscription?.status} />
              </div>
            </div>

            <div style={{ display: "flex", gap: 4, marginBottom: 20, borderBottom: "1.5px solid var(--color-border)" }}>
              {TABS.map(t => (
                <button key={t} onClick={() => setTab(t)}
                  style={{
                    padding: "9px 16px", background: "none", border: "none", cursor: "pointer",
                    fontSize: 13.5, fontWeight: 600,
                    color: tab === t ? "var(--color-primary)" : "var(--color-text-muted)",
                    borderBottom: tab === t ? "2.5px solid var(--color-primary)" : "2.5px solid transparent",
                    marginBottom: -2,
                  }}>
                  {t}
                </button>
              ))}
            </div>

            {tab === "Overview" && <OverviewTab tenant={tenant} overview={overview} onChanged={fetchTenant} />}
            {tab === "Users & Roles" && <UsersTab tenantId={tenant.id} />}
            {tab === "Subscription" && <SubscriptionTab tenant={tenant} onChanged={fetchTenant} />}
            {tab === "Audit Log" && <AuditTab tenantId={tenant.id} />}
          </>
        )}
      </PageShell>
    </AppShell>
  );
}
