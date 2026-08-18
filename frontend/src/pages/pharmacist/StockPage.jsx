/**
 * pages/pharmacist/StockPage.jsx
 * -------------------------------
 * Pharmacist's inventory — current batches on hand, low-stock flagged in
 * red, and a "Receive Stock" form to log a new delivery (or top up an
 * existing batch of the same drug/branch/batch number). Modeled after
 * lab/CatalogPage.jsx's inline add-form pattern.
 */
import { useState, useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useApi }    from "../../hooks/useApi";
import { useAuth }   from "../../hooks/useAuth";
import { useToast }  from "../../hooks/useToast";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import PaginationControls from "../../components/common/PaginationControls";

const EMPTY_FORM = {
  drug: null, drug_label: "", batch_number: "", expiry_date: "",
  quantity: "", reorder_level: "10", unit_cost: "", mrp: "",
};

function DrugPicker({ value, onChange }) {
  const [q, setQ] = useState(value);
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const timer = useRef(null);

  useEffect(() => setQ(value), [value]);

  function onType(text) {
    setQ(text);
    onChange(null, text); // clear any prior selection while typing
    clearTimeout(timer.current);
    if (text.trim().length < 2) { setResults([]); return; }
    timer.current = setTimeout(async () => {
      try {
        const { data } = await apiClient.get(API_ENDPOINTS.PRESCRIPTIONS.DRUG_SEARCH, { params: { q: text.trim() } });
        setResults(data?.data ?? data ?? []);
        setOpen(true);
      } catch {
        setResults([]);
      }
    }, 300);
  }

  return (
    <div style={{ position: "relative" }}>
      <input className="form-input" value={q}
        onChange={e => onType(e.target.value)}
        onFocus={() => results.length && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder="Type at least 2 letters…" autoComplete="off" />
      {open && results.length > 0 && (
        <div style={{ position: "absolute", top: "100%", left: 0, right: 0, zIndex: 20, background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: 8, marginTop: 4, maxHeight: 220, overflowY: "auto", boxShadow: "0 8px 24px rgba(0,0,0,0.12)" }}>
          {results.map(d => (
            <div key={d.id} onMouseDown={() => { onChange(d.id, `${d.name}${d.strength ? " " + d.strength : ""}`, d.default_mrp); setOpen(false); }}
              style={{ padding: "8px 12px", fontSize: 13, cursor: "pointer", borderBottom: "1px solid var(--color-border)" }}>
              <div style={{ fontWeight: 600 }}>{d.name} {d.strength}</div>
              <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
                {d.form}{d.generic_name ? ` · ${d.generic_name}` : ""}{d.default_mrp != null ? ` · ₹${d.default_mrp}` : ""}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ReceiveForm({ onSave, onCancel, saving }) {
  const [form, setForm] = useState(EMPTY_FORM);
  function upd(k, v) { setForm(f => ({ ...f, [k]: v })); }

  function submit(e) {
    e.preventDefault();
    if (!form.drug || !form.quantity) return;
    onSave({
      drug: form.drug,
      batch_number: form.batch_number,
      expiry_date: form.expiry_date || null,
      quantity: parseInt(form.quantity, 10),
      reorder_level: form.reorder_level === "" ? 10 : parseInt(form.reorder_level, 10),
      unit_cost: form.unit_cost === "" ? null : parseFloat(form.unit_cost),
      mrp: form.mrp === "" ? null : parseFloat(form.mrp),
    });
  }

  return (
    <form onSubmit={submit} style={{ background: "#FBF9F5", borderRadius: 10, padding: 16, border: "1px dashed var(--color-primary)", marginBottom: 16 }}>
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: 10, marginBottom: 10 }}>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>DRUG *</label>
          <DrugPicker value={form.drug_label} onChange={(id, label, defaultMrp) => setForm(f => ({
            ...f, drug: id, drug_label: label,
            // Prefill from the catalog's reference price so it's never
            // silently blank at billing time — still freely editable per
            // batch (a fresh delivery can legitimately cost more or less).
            mrp: (id != null && f.mrp === "" && defaultMrp != null) ? String(defaultMrp) : f.mrp,
          }))} />
        </div>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>BATCH NUMBER</label>
          <input className="form-input" value={form.batch_number} onChange={e => upd("batch_number", e.target.value)} placeholder="e.g. B24-1187" />
        </div>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>EXPIRY DATE</label>
          <input className="form-input" type="date" value={form.expiry_date} onChange={e => upd("expiry_date", e.target.value)} />
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 10, marginBottom: 14 }}>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>QUANTITY RECEIVED *</label>
          <input className="form-input" type="number" min="1" value={form.quantity} onChange={e => upd("quantity", e.target.value)} placeholder="e.g. 200" required />
        </div>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>REORDER LEVEL</label>
          <input className="form-input" type="number" min="0" value={form.reorder_level} onChange={e => upd("reorder_level", e.target.value)} placeholder="10" />
        </div>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>UNIT COST (₹)</label>
          <input className="form-input" type="number" min="0" step="0.01" value={form.unit_cost} onChange={e => upd("unit_cost", e.target.value)} placeholder="optional" />
        </div>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>MRP (₹)</label>
          <input className="form-input" type="number" min="0" step="0.01" value={form.mrp} onChange={e => upd("mrp", e.target.value)} placeholder="optional" />
        </div>
      </div>
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <button type="button" className="btn-outline" style={{ fontSize: 12, padding: "6px 14px" }} onClick={onCancel}>Cancel</button>
        <button type="submit" className="btn-primary" style={{ fontSize: 12, padding: "6px 16px" }} disabled={saving || !form.drug || !form.quantity}>
          {saving ? "Saving…" : "Receive Stock"}
        </button>
      </div>
    </form>
  );
}

export default function StockPage() {
  const { user } = useAuth();
  const location = useLocation();
  const { toastSuccess, toastApiError } = useToast();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [lowOnly, setLowOnly] = useState(() => !!location.state?.lowOnly);
  const { data, isLoading, refetch } = useApi(API_ENDPOINTS.PHARMACY.STOCK, {
    params: { page, page_size: pageSize, ...(lowOnly ? { low_only: 1 } : {}) },
  });
  const stock = data?.results || [];
  const pagination = data?.pagination || null;
  // Separate lightweight call for the low-stock badge — now that the main
  // list is paginated, counting `stock.filter(s => s.is_low)` would only
  // reflect whatever's on the current page instead of the whole inventory.
  const { data: lowData, refetch: refetchLow } = useApi(API_ENDPOINTS.PHARMACY.STOCK, {
    params: { low_only: 1, page: 1, page_size: 1 },
  });
  const lowCount = lowData?.pagination?.total_count ?? 0;

  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState(false);

  async function receiveStock(payload) {
    if (!user?.branch_id) {
      toastApiError(null, "Your account isn't assigned to a branch — ask an admin to set one before receiving stock.");
      return;
    }
    setSaving(true);
    try {
      await apiClient.post(API_ENDPOINTS.PHARMACY.STOCK, { ...payload, branch: user.branch_id });
      toastSuccess("Stock received.");
      setAdding(false);
      refetch();
      refetchLow();
    } catch (err) {
      toastApiError(err, "Could not receive stock.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <AppShell>
      <PageShell title="Stock">
        {!adding && (
          <button className="btn-primary" style={{ fontSize: 13, padding: "8px 18px", marginBottom: 16 }}
            onClick={() => setAdding(true)}>
            + Receive Stock
          </button>
        )}

        {adding && (
          <ReceiveForm onSave={receiveStock} onCancel={() => setAdding(false)} saving={saving} />
        )}

        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 20px", borderBottom: "1px solid var(--color-border)" }}>
            <span className="dot-label dot-label--green">Batches ({pagination ? pagination.total_count : stock.length})</span>
            <div style={{ display: "flex", gap: 6 }}>
              {[[false, "All"], [true, `Low stock${lowCount > 0 ? ` (${lowCount})` : ""}`]].map(([val, label]) => (
                <button key={String(val)} type="button"
                  className={lowOnly === val ? "btn-primary" : "btn-outline"}
                  style={{ fontSize: 11.5, padding: "5px 12px" }}
                  onClick={() => { setLowOnly(val); setPage(1); }}>
                  {label}
                </button>
              ))}
            </div>
          </div>
          {isLoading ? (
            <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
          ) : stock.length === 0 ? (
            <div style={{ padding: 48, textAlign: "center", color: "var(--color-text-muted)" }}>
              {lowOnly ? "Nothing running low right now." : "No stock on hand yet — receive the first batch above."}
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Drug</th>
                  <th>Batch</th>
                  <th>Expiry</th>
                  <th>Quantity</th>
                  <th>MRP</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {stock.map(s => (
                  <tr key={s.id} style={s.is_low ? { background: "#FEF2F2" } : undefined}>
                    <td style={{ fontWeight: 600, fontSize: 13 }}>{s.drug_name}</td>
                    <td style={{ fontSize: 12 }}>{s.batch_number || "—"}</td>
                    <td style={{ fontSize: 12 }}>{s.expiry_date || "—"}</td>
                    <td style={{ fontSize: 13, fontWeight: s.is_low ? 700 : 400, color: s.is_low ? "#991B1B" : undefined }}>{s.quantity}</td>
                    <td style={{ fontSize: 13 }}>{s.mrp != null ? `₹${s.mrp}` : "—"}</td>
                    <td>
                      <span className={`badge ${s.is_low ? "badge--error" : "badge--success"}`}>
                        {s.is_low ? "Low" : "OK"}
                      </span>
                    </td>
                  </tr>
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
