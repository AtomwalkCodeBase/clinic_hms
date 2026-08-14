/**
 * pages/pharmacist/CatalogPage.jsx
 * ---------------------------------
 * Pharmacist manages the drug catalog — name, form, strength/dosage. This is
 * what powers the dropdown doctors prescribe from (see EncounterPage.jsx's
 * DrugForm) and what pharmacy's "Receive Stock" picker searches against.
 * Modeled directly after lab/CatalogPage.jsx's inline add/edit pattern.
 */
import { useState } from "react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useApi }    from "../../hooks/useApi";
import { useToast }  from "../../hooks/useToast";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import PaginationControls from "../../components/common/PaginationControls";

const EMPTY_FORM = { name: "", generic_name: "", drug_code: "", form: "", strength: "" };

function DrugForm({ initial, drugForms, onSave, onCancel, saving }) {
  const [form, setForm] = useState(() => initial || { ...EMPTY_FORM, form: drugForms[0]?.name || "" });
  function upd(k, v) { setForm(f => ({ ...f, [k]: v })); }

  function submit(e) {
    e.preventDefault();
    if (!form.name.trim()) return;
    onSave({ ...form });
  }

  return (
    <form onSubmit={submit} style={{ background: "#FBF9F5", borderRadius: 10, padding: 16, border: "1px dashed var(--color-primary)", marginBottom: 16 }}>
      <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1.4fr 1fr", gap: 10, marginBottom: 10 }}>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>DRUG NAME *</label>
          <input className="form-input" value={form.name} onChange={e => upd("name", e.target.value)} placeholder="e.g. Amoxicillin" required />
        </div>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>GENERIC NAME</label>
          <input className="form-input" value={form.generic_name} onChange={e => upd("generic_name", e.target.value)} placeholder="e.g. Amoxicillin trihydrate" />
        </div>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>CODE</label>
          <input className="form-input" value={form.drug_code || "Auto-assigned"} disabled
            style={{ color: "var(--color-text-muted)", background: "#F3F1EC", cursor: "not-allowed" }} />
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 14 }}>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>DRUG FORM</label>
          <select className="form-input" value={form.form} onChange={e => upd("form", e.target.value)}>
            {drugForms.length === 0 && <option value="">No drug forms set up yet</option>}
            {drugForms.map(f => <option key={f.id} value={f.name}>{f.name}</option>)}
          </select>
        </div>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>STRENGTH / DOSAGE</label>
          <input className="form-input" value={form.strength} onChange={e => upd("strength", e.target.value)} placeholder="e.g. 500mg" />
        </div>
      </div>
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <button type="button" className="btn-outline" style={{ fontSize: 12, padding: "6px 14px" }} onClick={onCancel}>Cancel</button>
        <button type="submit" className="btn-primary" style={{ fontSize: 12, padding: "6px 16px" }} disabled={saving || !form.name.trim()}>
          {saving ? "Saving…" : "Save Drug"}
        </button>
      </div>
    </form>
  );
}

export default function CatalogPage() {
  const { toastSuccess, toastApiError } = useToast();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const { data, isLoading, refetch } = useApi(API_ENDPOINTS.PRESCRIPTIONS.DRUGS, {
    params: { include_inactive: 1, page, page_size: pageSize },
  });
  const drugs = data?.results || [];
  const pagination = data?.pagination || null;
  // Drug-form dropdown needs every active form regardless of page — no
  // ?page= passed here, so this stays the plain unpaginated list.
  const { data: formsData } = useApi(API_ENDPOINTS.PRESCRIPTIONS.DRUG_FORMS);
  const drugForms = formsData || [];

  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [saving, setSaving] = useState(false);

  async function createDrug(payload) {
    setSaving(true);
    try {
      await apiClient.post(API_ENDPOINTS.PRESCRIPTIONS.DRUGS, payload);
      toastSuccess("Drug added.");
      setAdding(false);
      refetch();
    } catch (err) {
      toastApiError(err, "Could not add the drug.");
    } finally {
      setSaving(false);
    }
  }

  async function updateDrug(id, payload) {
    setSaving(true);
    try {
      await apiClient.patch(API_ENDPOINTS.PRESCRIPTIONS.DRUG_ITEM(id), payload);
      toastSuccess("Drug updated.");
      setEditingId(null);
      refetch();
    } catch (err) {
      toastApiError(err, "Could not update the drug.");
    } finally {
      setSaving(false);
    }
  }

  async function toggleActive(drug) {
    try {
      await apiClient.patch(API_ENDPOINTS.PRESCRIPTIONS.DRUG_ITEM(drug.id), { is_active: !drug.is_active });
      toastSuccess(drug.is_active ? "Drug deactivated." : "Drug reactivated.");
      refetch();
    } catch (err) {
      toastApiError(err, "Could not update the drug.");
    }
  }

  return (
    <AppShell>
      <PageShell title="Drug Catalog Setup">
        {!adding && editingId === null && (
          <button className="btn-primary" style={{ fontSize: 13, padding: "8px 18px", marginBottom: 16 }}
            onClick={() => setAdding(true)}>
            + Add Drug
          </button>
        )}

        {adding && (
          <DrugForm drugForms={drugForms} onSave={createDrug} onCancel={() => setAdding(false)} saving={saving} />
        )}

        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--color-border)" }}>
            <span className="dot-label dot-label--green">Drugs ({pagination ? pagination.total_count : drugs.length})</span>
          </div>
          {isLoading ? (
            <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
          ) : drugs.length === 0 ? (
            <div style={{ padding: 48, textAlign: "center", color: "var(--color-text-muted)" }}>
              No drugs in the catalog yet — add the first one above.
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Generic</th>
                  <th>Form</th>
                  <th>Dosage</th>
                  <th>Status</th>
                  <th style={{ width: 160 }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {drugs.map(d => (
                  editingId === d.id ? (
                    <tr key={d.id}>
                      <td colSpan={6}>
                        <DrugForm
                          initial={{ ...d }}
                          drugForms={drugForms}
                          onSave={payload => updateDrug(d.id, payload)}
                          onCancel={() => setEditingId(null)}
                          saving={saving}
                        />
                      </td>
                    </tr>
                  ) : (
                    <tr key={d.id} style={{ opacity: d.is_active ? 1 : 0.5 }}>
                      <td style={{ fontWeight: 600, fontSize: 13 }}>{d.name}{d.drug_code && <span style={{ color: "var(--color-text-muted)", fontWeight: 400 }}> ({d.drug_code})</span>}</td>
                      <td style={{ fontSize: 12 }}>{d.generic_name || "—"}</td>
                      <td style={{ fontSize: 12 }}>{d.form}</td>
                      <td style={{ fontSize: 13 }}>{d.strength || "—"}</td>
                      <td>
                        <span className={`badge ${d.is_active ? "badge--success" : "badge--neutral"}`}>
                          {d.is_active ? "Active" : "Inactive"}
                        </span>
                      </td>
                      <td>
                        <div style={{ display: "flex", gap: 6 }}>
                          <button className="btn-outline" style={{ fontSize: 11, padding: "4px 10px" }} onClick={() => setEditingId(d.id)}>
                            Edit
                          </button>
                          <button className="btn-outline" style={{ fontSize: 11, padding: "4px 10px" }} onClick={() => toggleActive(d)}>
                            {d.is_active ? "Deactivate" : "Reactivate"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                ))}
              </tbody>
            </table>
          )}
          <PaginationControls
            pagination={pagination}
            page={page} pageSize={pageSize}
            onPageChange={setPage} onPageSizeChange={setPageSize}
          />
        </div>
      </PageShell>
    </AppShell>
  );
}
