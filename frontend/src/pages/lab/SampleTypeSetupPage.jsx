/**
 * pages/lab/SampleTypeSetupPage.jsx
 * -------------------------------------
 * Lab tech manages the list of sample types (Blood, Urine, Stool, ...) that
 * populate the "Sample Type" dropdown on the Lab Test Catalog. Was
 * previously a hardcoded list on both the backend (LabTest.sample_type
 * choices=) and the frontend (CatalogPage.jsx's own SAMPLE_TYPES const) —
 * this makes it fully configurable per hospital, backed by
 * billing.OptionList(list_type="sample_type"). Modeled directly on
 * pharmacist/DrugFormSetupPage.jsx's add/edit pattern (the same "domain
 * expert manages their own catalog" shape) rather than the hospital-admin-
 * only DropdownListEditor widget, since apps.lab.views.SampleTypeListCreateView
 * uses ?include_inactive=1 + IsLabTech, not billing's generic ?all=1 +
 * IsHospitalAdmin base classes.
 */
import { useState } from "react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useApi }    from "../../hooks/useApi";
import { useToast }  from "../../hooks/useToast";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";

function SampleTypeEntryForm({ initial, onSave, onCancel, saving }) {
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
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>SAMPLE TYPE NAME *</label>
          <input className="form-input" value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Tissue" required autoFocus />
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

export default function SampleTypeSetupPage() {
  const { toastSuccess, toastApiError } = useToast();
  const { data, isLoading, refetch } = useApi(API_ENDPOINTS.LAB.SAMPLE_TYPES, { params: { include_inactive: 1 } });
  const types = data || [];

  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [saving, setSaving] = useState(false);

  async function createType(payload) {
    setSaving(true);
    try {
      await apiClient.post(API_ENDPOINTS.LAB.SAMPLE_TYPES, payload);
      toastSuccess("Sample type added.");
      setAdding(false);
      refetch();
    } catch (err) {
      toastApiError(err, "Could not add the sample type.");
    } finally {
      setSaving(false);
    }
  }

  async function updateType(id, payload) {
    setSaving(true);
    try {
      await apiClient.patch(API_ENDPOINTS.LAB.SAMPLE_TYPE_ITEM(id), payload);
      toastSuccess("Sample type updated.");
      setEditingId(null);
      refetch();
    } catch (err) {
      toastApiError(err, "Could not update the sample type.");
    } finally {
      setSaving(false);
    }
  }

  async function toggleActive(t) {
    try {
      await apiClient.patch(API_ENDPOINTS.LAB.SAMPLE_TYPE_ITEM(t.id), { is_active: !t.is_active });
      toastSuccess(t.is_active ? "Sample type deactivated." : "Sample type reactivated.");
      refetch();
    } catch (err) {
      toastApiError(err, "Could not update the sample type.");
    }
  }

  return (
    <AppShell>
      <PageShell title="Sample Type Setup">
        {!adding && editingId === null && (
          <button className="btn-primary" style={{ fontSize: 13, padding: "8px 18px", marginBottom: 16 }}
            onClick={() => setAdding(true)}>
            + Add Sample Type
          </button>
        )}

        {adding && (
          <SampleTypeEntryForm onSave={createType} onCancel={() => setAdding(false)} saving={saving} />
        )}

        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--color-border)" }}>
            <span className="dot-label dot-label--green">Sample Types ({types.length})</span>
          </div>
          {isLoading ? (
            <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
          ) : types.length === 0 ? (
            <div style={{ padding: 48, textAlign: "center", color: "var(--color-text-muted)" }}>
              No sample types set up yet — add the first one above.
            </div>
          ) : (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 10, padding: 18 }}>
              {types.map(t => (
                editingId === t.id ? (
                  <div key={t.id} style={{ flex: "1 1 100%" }}>
                    <SampleTypeEntryForm
                      initial={t}
                      onSave={payload => updateType(t.id, payload)}
                      onCancel={() => setEditingId(null)}
                      saving={saving}
                    />
                  </div>
                ) : (
                  <div key={t.id} style={{
                    display: "flex", alignItems: "center", gap: 10,
                    border: "1px solid var(--color-border)", borderRadius: 12,
                    padding: "10px 14px", opacity: t.is_active ? 1 : 0.5,
                    background: "var(--color-surface)",
                  }}>
                    <span style={{ fontWeight: 700, fontSize: 13.5 }}>{t.name}</span>
                    <span className={`badge ${t.is_active ? "badge--success" : "badge--neutral"}`} style={{ fontSize: 10 }}>
                      {t.is_active ? "Active" : "Inactive"}
                    </span>
                    <div style={{ display: "flex", gap: 4, marginLeft: 4 }}>
                      <button className="btn-outline" style={{ fontSize: 10.5, padding: "3px 9px" }} onClick={() => setEditingId(t.id)}>
                        Edit
                      </button>
                      {!t.is_system && (
                        <button className="btn-outline" style={{ fontSize: 10.5, padding: "3px 9px" }} onClick={() => toggleActive(t)}>
                          {t.is_active ? "Deactivate" : "Reactivate"}
                        </button>
                      )}
                    </div>
                  </div>
                )
              ))}
            </div>
          )}
        </div>
      </PageShell>
    </AppShell>
  );
}
