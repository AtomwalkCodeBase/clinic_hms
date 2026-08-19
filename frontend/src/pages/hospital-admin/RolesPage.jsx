/**
 * pages/hospital-admin/RolesPage.jsx
 * -----------------------------------
 * Hospital admin: view the 6 system roles (read-only, back the hardcoded
 * per-endpoint checks) and — on the enterprise tier — define custom roles
 * with a hand-picked set of permissions. See apps/org/rbac.py and
 * docs/onboarding_auth_rbac_architecture.md section 4.3.
 *
 * Staff-level role assignment is deliberately NOT here — a person's primary
 * role stays a field on the invite/edit forms in StaffPage.jsx. This page is
 * only about defining what a role (system or custom) grants.
 */

import { useState, useEffect, useCallback } from "react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import apiClient      from "../../services/api.client";
import { useToast }   from "../../hooks/useToast";
import { usePermissions } from "../../hooks/usePermissions";
import API_ENDPOINTS  from "../../config/api.config";

function Modal({ title, children, onClose }) {
  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 1000,
      background: "rgba(0,0,0,0.45)",
      display: "flex", alignItems: "center", justifyContent: "center", padding: 24,
    }}>
      <div style={{
        background: "var(--color-surface)", borderRadius: 16,
        width: "100%", maxWidth: 560, maxHeight: "88vh", overflowY: "auto",
        padding: 32, boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
      }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
          <h2 style={{ margin: 0, fontSize: 18 }}>{title}</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer", color: "var(--color-text-muted)" }}>✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

// Which system-role identities a custom role can claim — see
// apps.org.rbac.ACTS_AS_CHOICES on the backend (kept in sync manually;
// these are deploy-time constants, not something either side needs to
// fetch from the other).
const ACTS_AS_OPTIONS = [
  { key: "doctor",         label: "Doctor" },
  { key: "nurse",          label: "Nurse" },
  { key: "front_desk",     label: "Front Desk" },
  { key: "lab_tech",       label: "Lab Technician" },
  { key: "pharmacist",     label: "Pharmacist" },
  { key: "hospital_admin", label: "Hospital Admin" },
];

function RoleForm({ initial, permissions, onSave, onCancel, saving }) {
  const [name, setName] = useState(initial?.name || "");
  const [description, setDescription] = useState(initial?.description || "");
  const [codes, setCodes] = useState(new Set(initial?.permission_codes || []));
  const [actsAs, setActsAs] = useState(new Set(initial?.acts_as || []));

  function toggle(code) {
    setCodes(prev => {
      const next = new Set(prev);
      next.has(code) ? next.delete(code) : next.add(code);
      return next;
    });
  }

  function toggleActsAs(key) {
    setActsAs(prev => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  }

  const inputStyle = {
    width: "100%", boxSizing: "border-box",
    border: "1.5px solid var(--color-border)", borderRadius: 8,
    padding: "9px 12px", fontSize: 14,
    background: "var(--color-surface)", color: "var(--color-text)", outline: "none",
  };
  const labelStyle = { display: "block", fontSize: 13, fontWeight: 600, marginBottom: 5 };

  return (
    <form onSubmit={e => { e.preventDefault(); onSave({ name, description, permission_codes: Array.from(codes), acts_as: Array.from(actsAs) }); }}>
      <div style={{ display: "grid", gap: 14, marginBottom: 16 }}>
        <div>
          <label style={labelStyle}>Role Name *</label>
          <input style={inputStyle} value={name} onChange={e => setName(e.target.value)}
            placeholder="e.g. Senior Nurse" required />
        </div>
        <div>
          <label style={labelStyle}>Description</label>
          <input style={inputStyle} value={description} onChange={e => setDescription(e.target.value)}
            placeholder="What this role is for" />
        </div>
      </div>

      <label style={labelStyle}>Acts as</label>
      <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 8 }}>
        Staff invited under this role also show up wherever the app looks for these
        roles specifically — e.g. checking "Doctor" gets them booking-dropdown/working-hours
        treatment like a real doctor, on top of whatever permissions you grant below.
      </div>
      <div style={{
        display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 20,
      }}>
        {ACTS_AS_OPTIONS.map(opt => (
          <label key={opt.key} style={{
            display: "flex", alignItems: "center", gap: 6, cursor: "pointer",
            padding: "6px 12px", borderRadius: 20, fontSize: 13,
            border: `1.5px solid ${actsAs.has(opt.key) ? "var(--color-primary)" : "var(--color-border)"}`,
            background: actsAs.has(opt.key) ? "var(--color-primary-light, var(--color-bg))" : "transparent",
            fontWeight: actsAs.has(opt.key) ? 700 : 500,
          }}>
            <input type="checkbox" checked={actsAs.has(opt.key)} onChange={() => toggleActsAs(opt.key)}
              style={{ margin: 0 }} />
            {opt.label}
          </label>
        ))}
      </div>

      <label style={labelStyle}>Permissions</label>
      <div style={{
        border: "1.5px solid var(--color-border)", borderRadius: 8, padding: "10px 14px",
        maxHeight: 260, overflowY: "auto", display: "grid", gap: 8,
      }}>
        {permissions.map(p => (
          <label key={p.code} style={{ display: "flex", alignItems: "flex-start", gap: 8, fontSize: 13, cursor: "pointer" }}>
            <input type="checkbox" checked={codes.has(p.code)} onChange={() => toggle(p.code)} style={{ marginTop: 2 }} />
            <span>
              <div style={{ fontWeight: 600 }}>{p.code}</div>
              {p.description && <div style={{ color: "var(--color-text-muted)", fontSize: 12 }}>{p.description}</div>}
            </span>
          </label>
        ))}
      </div>

      <div style={{ display: "flex", gap: 10, marginTop: 20 }}>
        <button type="button" onClick={onCancel}
          style={{ flex: 1, padding: "9px 0", borderRadius: 8, border: "1.5px solid var(--color-border)", background: "none", cursor: "pointer", fontSize: 14, fontWeight: 600 }}>
          Cancel
        </button>
        <button type="submit" disabled={saving} className="btn-primary" style={{ flex: 2 }}>
          {saving ? "Saving…" : (initial ? "Save Changes" : "Create Role")}
        </button>
      </div>
    </form>
  );
}

export default function RolesPage() {
  const api = apiClient;
  const { toastSuccess, toastApiError } = useToast();
  const { permissions: subPermissions } = usePermissions();
  const canCustomRoles = !!subPermissions?.feat_custom_roles;

  const [roles, setRoles] = useState([]);
  const [catalog, setCatalog] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [editing, setEditing] = useState(null);
  const [saving, setSaving] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [rolesRes, permsRes] = await Promise.all([
        api.get(API_ENDPOINTS.ORG.ROLES),
        api.get(API_ENDPOINTS.ORG.PERMISSIONS),
      ]);
      setRoles(rolesRes.data?.data || []);
      setCatalog(permsRes.data?.data || []);
    } catch { setRoles([]); setCatalog([]); }
    finally { setLoading(false); }
  }, [api]);

  useEffect(() => { fetchData(); }, [fetchData]);

  async function handleCreate(form) {
    setSaving(true);
    try {
      await api.post(API_ENDPOINTS.ORG.ROLES, form);
      toastSuccess(`Role "${form.name}" created.`);
      setModal(null); fetchData();
    } catch (err) { toastApiError(err, "Failed to create role."); }
    finally { setSaving(false); }
  }

  async function handleUpdate(form) {
    setSaving(true);
    try {
      await api.patch(API_ENDPOINTS.ORG.ROLE(editing.id), form);
      toastSuccess("Role updated.");
      setModal(null); setEditing(null); fetchData();
    } catch (err) { toastApiError(err, "Failed to update role."); }
    finally { setSaving(false); }
  }

  async function handleDelete(role) {
    if (!confirm(`Delete role "${role.name}"? Anyone holding it loses this extra permission set (their primary role is unaffected).`)) return;
    try {
      await api.delete(API_ENDPOINTS.ORG.ROLE(role.id));
      toastSuccess("Role deleted.");
      fetchData();
    } catch (err) { toastApiError(err, "Failed to delete role."); }
  }

  const systemRoles = roles.filter(r => r.is_system_role);
  const customRoles = roles.filter(r => !r.is_system_role);

  return (
    <AppShell>
      <PageShell title="Roles & Permissions">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20, gap: 12, flexWrap: "wrap" }}>
          <div style={{ fontSize: 13, color: "var(--color-text-muted)", maxWidth: 520 }}>
            Every hospital gets the 6 default roles below. On the enterprise plan you can also
            define custom roles with your own permission mix.
          </div>
          <button className="btn-primary" onClick={() => setModal("create")} disabled={!canCustomRoles}
            title={!canCustomRoles ? "Custom roles require the enterprise plan. Upgrade to add one." : undefined}
            style={!canCustomRoles ? { opacity: 0.5, cursor: "not-allowed" } : undefined}>
            + Add Custom Role
          </button>
        </div>

        {!canCustomRoles && (
          <div style={{
            display: "flex", alignItems: "center", gap: 10, padding: "12px 18px", borderRadius: 12,
            background: "var(--color-warning-light)", color: "var(--color-warning)", marginBottom: 20, fontSize: 13.5, fontWeight: 600,
          }}>
            Custom roles aren't included on your current plan. Upgrade to enterprise to define roles beyond the 6 defaults.
          </div>
        )}

        {loading ? (
          <div style={{ textAlign: "center", padding: 60, color: "var(--color-text-muted)" }}>Loading…</div>
        ) : (
          <>
            <div style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 10 }}>
              System Roles
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 12, marginBottom: 28 }}>
              {systemRoles.map(role => (
                <div key={role.id} className="card" style={{ padding: "16px 20px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                    <div style={{ fontWeight: 700, fontSize: 15 }}>{role.name}</div>
                    <span style={{
                      fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 12,
                      background: "var(--color-bg)", color: "var(--color-text-muted)", border: "1px solid var(--color-border)",
                    }}>SYSTEM — READ ONLY</span>
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {role.permission_codes.map(code => (
                      <span key={code} style={{
                        padding: "3px 10px", borderRadius: 20, fontSize: 12,
                        background: "var(--color-bg)", border: "1px solid var(--color-border)",
                      }}>{code}</span>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            <div style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 10 }}>
              Custom Roles
            </div>
            {customRoles.length === 0 ? (
              <div className="card" style={{ textAlign: "center", padding: 40 }}>
                <div style={{ color: "var(--color-text-muted)" }}>
                  {canCustomRoles ? "No custom roles yet." : "Custom roles require the enterprise plan."}
                </div>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {customRoles.map(role => (
                  <div key={role.id} className="card" style={{ padding: "16px 20px" }}>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 8 }}>
                      <div>
                        <div style={{ fontWeight: 700, fontSize: 15 }}>{role.name}</div>
                        {role.description && <div style={{ fontSize: 12.5, color: "var(--color-text-muted)" }}>{role.description}</div>}
                        {role.acts_as?.length > 0 && (
                          <div style={{ fontSize: 12, color: "var(--color-primary)", fontWeight: 600, marginTop: 4 }}>
                            Acts as: {role.acts_as.map(k => ACTS_AS_OPTIONS.find(o => o.key === k)?.label || k).join(", ")}
                          </div>
                        )}
                      </div>
                      <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
                        <button onClick={() => { setEditing(role); setModal("edit"); }}
                          style={{ padding: "6px 14px", borderRadius: 8, border: "1.5px solid var(--color-border)", background: "none", cursor: "pointer", fontSize: 13, fontWeight: 600 }}>
                          Edit
                        </button>
                        <button onClick={() => handleDelete(role)}
                          style={{ padding: "6px 14px", borderRadius: 8, border: "1.5px solid var(--color-error)", background: "none", cursor: "pointer", fontSize: 13, fontWeight: 600, color: "var(--color-error)" }}>
                          Delete
                        </button>
                      </div>
                    </div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                      {role.permission_codes.length === 0 ? (
                        <span style={{ fontSize: 12, color: "var(--color-text-muted)", fontStyle: "italic" }}>No permissions granted yet.</span>
                      ) : role.permission_codes.map(code => (
                        <span key={code} style={{
                          padding: "3px 10px", borderRadius: 20, fontSize: 12,
                          background: "var(--color-bg)", border: "1px solid var(--color-border)",
                        }}>{code}</span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {modal === "create" && (
          <Modal title="Add Custom Role" onClose={() => setModal(null)}>
            <RoleForm permissions={catalog} onSave={handleCreate} onCancel={() => setModal(null)} saving={saving} />
          </Modal>
        )}
        {modal === "edit" && editing && (
          <Modal title={`Edit — ${editing.name}`} onClose={() => { setModal(null); setEditing(null); }}>
            <RoleForm initial={editing} permissions={catalog} onSave={handleUpdate}
              onCancel={() => { setModal(null); setEditing(null); }} saving={saving} />
          </Modal>
        )}
      </PageShell>
    </AppShell>
  );
}
