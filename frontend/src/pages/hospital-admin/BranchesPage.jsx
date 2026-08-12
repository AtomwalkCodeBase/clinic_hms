/**
 * pages/hospital-admin/BranchesPage.jsx
 * ----------------------------------------
 * Hospital admin: create and manage branches + departments.
 */

import { useState, useEffect, useCallback } from "react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import apiClient     from "../../services/api.client";
import { useToast }  from "../../hooks/useToast";
import { usePermissions } from "../../hooks/usePermissions";
import API_ENDPOINTS from "../../config/api.config";
import { sanitizeMobileInput, mobileError } from "../../utils/validation";

const EMPTY_BRANCH = { name: "", address: "", city: "", state: "", pincode: "", phone: "" };

function Modal({ title, children, onClose }) {
  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 1000,
      background: "rgba(0,0,0,0.45)",
      display: "flex", alignItems: "center", justifyContent: "center", padding: 24,
    }}>
      <div style={{
        background: "var(--color-surface)", borderRadius: 16,
        width: "100%", maxWidth: 520, padding: 32,
        boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
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

function Field({ label, value, onChange, placeholder, required, error, ...inputProps }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <label style={{ display: "block", fontSize: 13, fontWeight: 600, marginBottom: 5 }}>{label}</label>
      <input
        value={value} onChange={e => onChange(e.target.value)}
        placeholder={placeholder} required={required}
        style={{
          width: "100%", boxSizing: "border-box",
          border: `1.5px solid ${error ? "var(--color-error)" : "var(--color-border)"}`, borderRadius: 8,
          padding: "9px 12px", fontSize: 14,
          background: "var(--color-surface)", color: "var(--color-text)", outline: "none",
        }}
        {...inputProps}
      />
      {error && <div style={{ color: "var(--color-error)", fontSize: 12, marginTop: 4 }}>{error}</div>}
    </div>
  );
}

function BranchForm({ initial, onSave, onCancel, saving }) {
  const [form, setForm] = useState(initial || EMPTY_BRANCH);
  const set = (k) => (v) => setForm(f => ({ ...f, [k]: v }));
  const phoneErr = mobileError(form.phone);

  function submit(e) {
    e.preventDefault();
    if (phoneErr) return;
    onSave(form);
  }

  return (
    <form onSubmit={submit}>
      <Field label="Branch Name *" value={form.name} onChange={set("name")} placeholder="Main Hospital" required />
      <Field label="Address" value={form.address} onChange={set("address")} placeholder="123 Main Street" />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <Field label="City" value={form.city} onChange={set("city")} placeholder="Mumbai" />
        <Field label="State" value={form.state} onChange={set("state")} placeholder="Maharashtra" />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <Field label="Pincode" value={form.pincode} onChange={set("pincode")} placeholder="400001" />
        <Field label="Phone" value={form.phone} onChange={v => set("phone")(sanitizeMobileInput(v))}
          placeholder="98xxxxxxxx" error={phoneErr} maxLength={10} inputMode="numeric" />
      </div>
      <div style={{ display: "flex", gap: 10, marginTop: 8 }}>
        <button type="button" onClick={onCancel}
          style={{ flex: 1, padding: "9px 0", borderRadius: 8, border: "1.5px solid var(--color-border)", background: "none", cursor: "pointer", fontSize: 14, fontWeight: 600 }}>
          Cancel
        </button>
        <button type="submit" disabled={saving || !!phoneErr} className="btn-primary" style={{ flex: 2 }}>
          {saving ? "Saving…" : (initial ? "Update Branch" : "Create Branch")}
        </button>
      </div>
    </form>
  );
}

function DeptList({ branchId }) {
  const api = apiClient;
  const { toastSuccess, toastApiError } = useToast();
  const [depts,   setDepts]   = useState([]);
  const [loading, setLoading] = useState(true);
  const [adding,  setAdding]  = useState(false);
  const [newName, setNewName] = useState("");
  const [saving,  setSaving]  = useState(false);

  const fetchDepts = useCallback(async () => {
    setLoading(true);
    try {
      const { data: res } = await api.get(`${API_ENDPOINTS.ORG.DEPARTMENTS}?branch_id=${branchId}`);
      setDepts(res.data || []);
    } catch { setDepts([]); }
    finally { setLoading(false); }
  }, [api, branchId]);

  useEffect(() => { fetchDepts(); }, [fetchDepts]);

  async function addDept(e) {
    e.preventDefault();
    if (!newName.trim()) return;
    setSaving(true);
    try {
      await api.post(API_ENDPOINTS.ORG.DEPARTMENTS, { branch: branchId, name: newName.trim() });
      toastSuccess(`Department "${newName}" added.`);
      setNewName(""); setAdding(false);
      fetchDepts();
    } catch (err) { toastApiError(err, "Failed to add department."); }
    finally { setSaving(false); }
  }

  return (
    <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--color-border)" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text-muted)", letterSpacing: "0.05em" }}>DEPARTMENTS</span>
        <button onClick={() => setAdding(!adding)}
          style={{ fontSize: 12, padding: "4px 10px", borderRadius: 6, border: "1.5px solid var(--color-primary)", background: "none", color: "var(--color-primary)", cursor: "pointer", fontWeight: 600 }}>
          + Add
        </button>
      </div>
      {adding && (
        <form onSubmit={addDept} style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          <input value={newName} onChange={e => setNewName(e.target.value)}
            placeholder="e.g. Cardiology" required
            style={{ flex: 1, padding: "7px 10px", borderRadius: 7, border: "1.5px solid var(--color-border)", background: "var(--color-bg)", fontSize: 13, outline: "none" }} />
          <button type="submit" disabled={saving} className="btn-primary" style={{ padding: "7px 14px", fontSize: 13 }}>
            {saving ? "…" : "Add"}
          </button>
          <button type="button" onClick={() => { setAdding(false); setNewName(""); }}
            style={{ padding: "7px 10px", borderRadius: 7, border: "1.5px solid var(--color-border)", background: "none", cursor: "pointer", fontSize: 13 }}>✕</button>
        </form>
      )}
      {loading ? (
        <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>Loading…</div>
      ) : depts.length === 0 ? (
        <div style={{ fontSize: 13, color: "var(--color-text-muted)", fontStyle: "italic" }}>No departments yet.</div>
      ) : (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {depts.map(d => (
            <span key={d.id} style={{
              padding: "4px 12px", borderRadius: 20,
              background: "var(--color-bg)", border: "1px solid var(--color-border)", fontSize: 13,
            }}>{d.name}</span>
          ))}
        </div>
      )}
    </div>
  );
}

export default function BranchesPage() {
  const api = apiClient;
  const { toastSuccess, toastApiError } = useToast();
  const { permissions, atCapacity, remaining, refresh: refreshPermissions } = usePermissions();
  const [branches, setBranches] = useState([]);
  const [loading,  setLoading]  = useState(true);
  const [modal,    setModal]    = useState(null);
  const [editing,  setEditing]  = useState(null);
  const [saving,   setSaving]   = useState(false);
  const [expanded, setExpanded] = useState({});

  const branchCap = atCapacity("branches");
  const maxBranches = permissions?.max_branches;

  const fetchBranches = useCallback(async () => {
    setLoading(true);
    try {
      const { data: res } = await api.get(API_ENDPOINTS.ORG.BRANCHES);
      setBranches(res.data || []);
    } catch { setBranches([]); }
    finally { setLoading(false); }
  }, [api]);

  useEffect(() => { fetchBranches(); }, [fetchBranches]);

  async function handleCreate(form) {
    setSaving(true);
    try {
      await api.post(API_ENDPOINTS.ORG.BRANCHES, form);
      toastSuccess(`Branch "${form.name}" created.`);
      setModal(null); fetchBranches(); refreshPermissions();
    } catch (err) { toastApiError(err, "Failed to create branch."); }
    finally { setSaving(false); }
  }

  async function handleUpdate(form) {
    setSaving(true);
    try {
      await api.patch(API_ENDPOINTS.ORG.BRANCH(editing.id), form);
      toastSuccess("Branch updated.");
      setModal(null); setEditing(null); fetchBranches();
    } catch (err) { toastApiError(err, "Failed to update branch."); }
    finally { setSaving(false); }
  }

  async function handleDeactivate(branch) {
    if (!confirm(`Deactivate branch "${branch.name}"?`)) return;
    try {
      await api.delete(API_ENDPOINTS.ORG.BRANCH(branch.id));
      toastSuccess("Branch deactivated.");
      fetchBranches(); refreshPermissions();
    } catch (err) { toastApiError(err, "Failed to deactivate."); }
  }

  return (
    <AppShell>
      <PageShell title="Branches">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20, gap: 12, flexWrap: "wrap" }}>
          {maxBranches > 0 && (
            <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
              {branches.length} of {maxBranches} branch{maxBranches === 1 ? "" : "es"} used
              {branchCap && <span style={{ color: "var(--color-error)", fontWeight: 600 }}> — limit reached</span>}
            </div>
          )}
          <button className="btn-primary" onClick={() => setModal("create")} disabled={branchCap}
            title={branchCap ? `Branch limit reached (${maxBranches} on your current plan). Upgrade to add more.` : undefined}
            style={branchCap ? { opacity: 0.5, cursor: "not-allowed" } : undefined}>
            + Add Branch
          </button>
        </div>

        {branchCap && (
          <div style={{
            display: "flex", alignItems: "center", gap: 10, padding: "12px 18px", borderRadius: 12,
            background: "var(--color-warning-light)", color: "var(--color-warning)", marginBottom: 20, fontSize: 13.5, fontWeight: 600,
          }}>
            You've reached your plan's branch limit ({maxBranches}). Upgrade your plan to add more branches.
          </div>
        )}

        {loading ? (
          <div style={{ textAlign: "center", padding: 60, color: "var(--color-text-muted)" }}>Loading…</div>
        ) : branches.length === 0 ? (
          <div className="card" style={{ textAlign: "center", padding: 60 }}>
            <div style={{ fontSize: 40, marginBottom: 12 }}>🏥</div>
            <div style={{ fontWeight: 600, fontSize: 16, marginBottom: 8 }}>No branches yet</div>
            <div style={{ color: "var(--color-text-muted)", marginBottom: 20 }}>Add your first branch to begin setup.</div>
            <button className="btn-primary" onClick={() => setModal("create")} disabled={branchCap}
              style={branchCap ? { opacity: 0.5, cursor: "not-allowed" } : undefined}>
              Add First Branch
            </button>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {branches.map(branch => (
              <div key={branch.id} className="card" style={{ padding: 0, overflow: "hidden" }}>
                <div style={{ padding: "16px 20px", display: "flex", alignItems: "center", gap: 12 }}>
                  <div style={{ flex: 1, cursor: "pointer" }} onClick={() => setExpanded(e => ({ ...e, [branch.id]: !e[branch.id] }))}>
                    <div style={{ fontWeight: 700, fontSize: 16 }}>{branch.name}</div>
                    <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginTop: 3 }}>
                      {[branch.city, branch.state].filter(Boolean).join(", ") || "No location set"}
                      {branch.phone && ` · ${branch.phone}`}
                    </div>
                  </div>
                  <button onClick={() => { setEditing(branch); setModal("edit"); }}
                    style={{ padding: "6px 14px", borderRadius: 8, border: "1.5px solid var(--color-border)", background: "none", cursor: "pointer", fontSize: 13, fontWeight: 600 }}>
                    Edit
                  </button>
                  <button onClick={() => handleDeactivate(branch)}
                    style={{ padding: "6px 14px", borderRadius: 8, border: "1.5px solid var(--color-error)", background: "none", cursor: "pointer", fontSize: 13, fontWeight: 600, color: "var(--color-error)" }}>
                    Remove
                  </button>
                  <span style={{ cursor: "pointer", color: "var(--color-text-muted)" }}
                    onClick={() => setExpanded(e => ({ ...e, [branch.id]: !e[branch.id] }))}>
                    {expanded[branch.id] ? "▾" : "▸"}
                  </span>
                </div>
                {expanded[branch.id] && (
                  <div style={{ padding: "0 20px 20px" }}>
                    <DeptList branchId={branch.id} />
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {modal === "create" && (
          <Modal title="Add Branch" onClose={() => setModal(null)}>
            <BranchForm onSave={handleCreate} onCancel={() => setModal(null)} saving={saving} />
          </Modal>
        )}
        {modal === "edit" && editing && (
          <Modal title="Edit Branch" onClose={() => { setModal(null); setEditing(null); }}>
            <BranchForm initial={editing} onSave={handleUpdate} onCancel={() => { setModal(null); setEditing(null); }} saving={saving} />
          </Modal>
        )}
      </PageShell>
    </AppShell>
  );
}
