/**
 * pages/pharmacist/DrugFormSetupPage.jsx
 * ---------------------------------------
 * Pharmacist manages the list of drug forms (Tablet, Capsule, Syrup, ...)
 * that populate the "Drug Form" dropdown on the Drug Catalog Setup page.
 * Was previously a hardcoded list — this makes it fully configurable per
 * hospital. Modeled after CatalogPage.jsx's inline add/edit pattern, just
 * with a single field (name) instead of a full drug record.
 */
import { useState } from "react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useApi }    from "../../hooks/useApi";
import { useToast }  from "../../hooks/useToast";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";

function DrugFormEntryForm({ initial, onSave, onCancel, saving }) {
  const [name, setName] = useState(initial?.name || "");

  function submit(e) {
    e.preventDefault();
    if (!name.trim()) return;
    onSave({ name: name.trim() });
  }

  return (
    <form onSubmit={submit} style={{ background: "#FBF9F5", borderRadius: 10, padding: 16, border: "1px dashed var(--color-primary)", marginBottom: 16 }}>
      <div style={{ display: "flex", gap: 10, alignItems: "flex-end" }}>
        <div style={{ flex: 1 }}>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>DRUG FORM NAME *</label>
          <input className="form-input" value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Suppository" required autoFocus />
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button type="button" className="btn-outline" style={{ fontSize: 12, padding: "6px 14px" }} onClick={onCancel}>Cancel</button>
          <button type="submit" className="btn-primary" style={{ fontSize: 12, padding: "6px 16px" }} disabled={saving || !name.trim()}>
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </form>
  );
}

export default function DrugFormSetupPage() {
  const { toastSuccess, toastApiError } = useToast();
  const { data, isLoading, refetch } = useApi(API_ENDPOINTS.PRESCRIPTIONS.DRUG_FORMS, { params: { include_inactive: 1 } });
  const forms = data || [];

  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [saving, setSaving] = useState(false);

  async function createForm(payload) {
    setSaving(true);
    try {
      await apiClient.post(API_ENDPOINTS.PRESCRIPTIONS.DRUG_FORMS, payload);
      toastSuccess("Drug form added.");
      setAdding(false);
      refetch();
    } catch (err) {
      toastApiError(err, "Could not add the drug form.");
    } finally {
      setSaving(false);
    }
  }

  async function updateForm(id, payload) {
    setSaving(true);
    try {
      await apiClient.patch(API_ENDPOINTS.PRESCRIPTIONS.DRUG_FORM_ITEM(id), payload);
      toastSuccess("Drug form updated.");
      setEditingId(null);
      refetch();
    } catch (err) {
      toastApiError(err, "Could not update the drug form.");
    } finally {
      setSaving(false);
    }
  }

  async function toggleActive(f) {
    try {
      await apiClient.patch(API_ENDPOINTS.PRESCRIPTIONS.DRUG_FORM_ITEM(f.id), { is_active: !f.is_active });
      toastSuccess(f.is_active ? "Drug form deactivated." : "Drug form reactivated.");
      refetch();
    } catch (err) {
      toastApiError(err, "Could not update the drug form.");
    }
  }

  return (
    <AppShell>
      <PageShell title="Drug Form Setup">
        {!adding && editingId === null && (
          <button className="btn-primary" style={{ fontSize: 13, padding: "8px 18px", marginBottom: 16 }}
            onClick={() => setAdding(true)}>
            + Add Drug Form
          </button>
        )}

        {adding && (
          <DrugFormEntryForm onSave={createForm} onCancel={() => setAdding(false)} saving={saving} />
        )}

        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--color-border)" }}>
            <span className="dot-label dot-label--green">Drug Forms ({forms.length})</span>
          </div>
          {isLoading ? (
            <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
          ) : forms.length === 0 ? (
            <div style={{ padding: 48, textAlign: "center", color: "var(--color-text-muted)" }}>
              No drug forms set up yet — add the first one above.
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Status</th>
                  <th style={{ width: 160 }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {forms.map(f => (
                  editingId === f.id ? (
                    <tr key={f.id}>
                      <td colSpan={3}>
                        <DrugFormEntryForm
                          initial={f}
                          onSave={payload => updateForm(f.id, payload)}
                          onCancel={() => setEditingId(null)}
                          saving={saving}
                        />
                      </td>
                    </tr>
                  ) : (
                    <tr key={f.id} style={{ opacity: f.is_active ? 1 : 0.5 }}>
                      <td style={{ fontWeight: 600, fontSize: 13 }}>{f.name}</td>
                      <td>
                        <span className={`badge ${f.is_active ? "badge--success" : "badge--neutral"}`}>
                          {f.is_active ? "Active" : "Inactive"}
                        </span>
                      </td>
                      <td>
                        <div style={{ display: "flex", gap: 6 }}>
                          <button className="btn-outline" style={{ fontSize: 11, padding: "4px 10px" }} onClick={() => setEditingId(f.id)}>
                            Edit
                          </button>
                          <button className="btn-outline" style={{ fontSize: 11, padding: "4px 10px" }} onClick={() => toggleActive(f)}>
                            {f.is_active ? "Deactivate" : "Reactivate"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                ))}
              </tbody>
            </table>
          )}
        </div>
      </PageShell>
    </AppShell>
  );
}
