/**
 * pages/lab/CatalogPage.jsx
 * ---------------------------
 * Lab tech manages the test catalog — name, sample type, price, turnaround
 * time. This is what powers the dropdown doctors order from, what patients
 * see priced on their portal, and what nurses see when setting a patient's
 * in-house/outside choice. Nothing else in the lab-ordering flow works
 * until tests exist here.
 */
import { useState } from "react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useApi }    from "../../hooks/useApi";
import { useToast }  from "../../hooks/useToast";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";

const SAMPLE_TYPES = [
  { value: "blood",  label: "Blood" },
  { value: "urine",  label: "Urine" },
  { value: "stool",  label: "Stool" },
  { value: "sputum", label: "Sputum" },
  { value: "swab",   label: "Swab" },
  { value: "other",  label: "Other" },
];

const EMPTY_FORM = { name: "", code: "", sample_type: "blood", price: "", turnaround_hours: "24", description: "" };

function TestForm({ initial, onSave, onCancel, saving }) {
  const [form, setForm] = useState(initial || EMPTY_FORM);
  function upd(k, v) { setForm(f => ({ ...f, [k]: v })); }

  function submit(e) {
    e.preventDefault();
    if (!form.name.trim()) return;
    onSave({
      ...form,
      price: form.price === "" ? null : parseFloat(form.price),
      turnaround_hours: form.turnaround_hours === "" ? 24 : parseInt(form.turnaround_hours),
    });
  }

  return (
    <form onSubmit={submit} style={{ background: "#FBF9F5", borderRadius: 10, padding: 16, border: "1px dashed var(--color-primary)", marginBottom: 16 }}>
      <div style={{ display: "grid", gridTemplateColumns: "1.6fr 1fr 1fr", gap: 10, marginBottom: 10 }}>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>TEST NAME *</label>
          <input className="form-input" value={form.name} onChange={e => upd("name", e.target.value)} placeholder="e.g. CBC (Complete Blood Count)" required />
        </div>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>CODE</label>
          <input className="form-input" value={form.code || "Auto-assigned"} disabled
            style={{ color: "var(--color-text-muted)", background: "#F3F1EC", cursor: "not-allowed" }} />
        </div>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>SAMPLE TYPE</label>
          <select className="form-input" value={form.sample_type} onChange={e => upd("sample_type", e.target.value)}>
            {SAMPLE_TYPES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 2fr", gap: 10, marginBottom: 14 }}>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>PRICE (₹)</label>
          <input className="form-input" type="number" min="0" step="0.01" value={form.price} onChange={e => upd("price", e.target.value)} placeholder="e.g. 350" />
        </div>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>TURNAROUND (hours)</label>
          <input className="form-input" type="number" min="1" value={form.turnaround_hours} onChange={e => upd("turnaround_hours", e.target.value)} placeholder="24" />
        </div>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>NOTES (optional)</label>
          <input className="form-input" value={form.description} onChange={e => upd("description", e.target.value)} placeholder="e.g. Fasting not required" />
        </div>
      </div>
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <button type="button" className="btn-outline" style={{ fontSize: 12, padding: "6px 14px" }} onClick={onCancel}>Cancel</button>
        <button type="submit" className="btn-primary" style={{ fontSize: 12, padding: "6px 16px" }} disabled={saving || !form.name.trim()}>
          {saving ? "Saving…" : "Save Test"}
        </button>
      </div>
    </form>
  );
}

export default function CatalogPage() {
  const { toastSuccess, toastApiError } = useToast();
  const { data, isLoading, refetch } = useApi(API_ENDPOINTS.LAB.CATALOG, { params: { include_inactive: 1 } });
  const tests = data || [];

  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [saving, setSaving] = useState(false);

  async function createTest(payload) {
    setSaving(true);
    try {
      await apiClient.post(API_ENDPOINTS.LAB.CATALOG, payload);
      toastSuccess("Test added.");
      setAdding(false);
      refetch();
    } catch (err) {
      toastApiError(err, "Could not add the test.");
    } finally {
      setSaving(false);
    }
  }

  async function updateTest(id, payload) {
    setSaving(true);
    try {
      await apiClient.patch(API_ENDPOINTS.LAB.CATALOG_ITEM(id), payload);
      toastSuccess("Test updated.");
      setEditingId(null);
      refetch();
    } catch (err) {
      toastApiError(err, "Could not update the test.");
    } finally {
      setSaving(false);
    }
  }

  async function toggleActive(test) {
    try {
      await apiClient.patch(API_ENDPOINTS.LAB.CATALOG_ITEM(test.id), { is_active: !test.is_active });
      toastSuccess(test.is_active ? "Test deactivated." : "Test reactivated.");
      refetch();
    } catch (err) {
      toastApiError(err, "Could not update the test.");
    }
  }

  return (
    <AppShell>
      <PageShell title="Test Catalog">
        {!adding && editingId === null && (
          <button className="btn-primary" style={{ fontSize: 13, padding: "8px 18px", marginBottom: 16 }}
            onClick={() => setAdding(true)}>
            + Add Test
          </button>
        )}

        {adding && (
          <TestForm onSave={createTest} onCancel={() => setAdding(false)} saving={saving} />
        )}

        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--color-border)" }}>
            <span className="dot-label dot-label--green">Tests ({tests.length})</span>
          </div>
          {isLoading ? (
            <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
          ) : tests.length === 0 ? (
            <div style={{ padding: 48, textAlign: "center", color: "var(--color-text-muted)" }}>
              No tests in the catalog yet — add the first one above.
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Sample</th>
                  <th>Price</th>
                  <th>Turnaround</th>
                  <th>Status</th>
                  <th style={{ width: 160 }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {tests.map(t => (
                  editingId === t.id ? (
                    <tr key={t.id}>
                      <td colSpan={6}>
                        <TestForm
                          initial={{ ...t, price: t.price ?? "", turnaround_hours: String(t.turnaround_hours) }}
                          onSave={payload => updateTest(t.id, payload)}
                          onCancel={() => setEditingId(null)}
                          saving={saving}
                        />
                      </td>
                    </tr>
                  ) : (
                    <tr key={t.id} style={{ opacity: t.is_active ? 1 : 0.5 }}>
                      <td style={{ fontWeight: 600, fontSize: 13 }}>{t.name}{t.code && <span style={{ color: "var(--color-text-muted)", fontWeight: 400 }}> ({t.code})</span>}</td>
                      <td style={{ fontSize: 12, textTransform: "capitalize" }}>{t.sample_type}</td>
                      <td style={{ fontSize: 13 }}>{t.price != null ? `₹${t.price}` : "—"}</td>
                      <td style={{ fontSize: 12 }}>{t.turnaround_hours}h</td>
                      <td>
                        <span className={`badge ${t.is_active ? "badge--success" : "badge--neutral"}`}>
                          {t.is_active ? "Active" : "Inactive"}
                        </span>
                      </td>
                      <td>
                        <div style={{ display: "flex", gap: 6 }}>
                          <button className="btn-outline" style={{ fontSize: 11, padding: "4px 10px" }} onClick={() => setEditingId(t.id)}>
                            Edit
                          </button>
                          <button className="btn-outline" style={{ fontSize: 11, padding: "4px 10px" }} onClick={() => toggleActive(t)}>
                            {t.is_active ? "Deactivate" : "Reactivate"}
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
