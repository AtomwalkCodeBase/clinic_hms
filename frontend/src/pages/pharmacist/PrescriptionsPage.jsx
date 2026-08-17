/**
 * pages/pharmacist/PrescriptionsPage.jsx
 * ----------------------------------------
 * Pharmacist's dispensing queue — finalized prescriptions waiting to be
 * filled. Each drug line is dispensed against a specific stock batch (FEFO
 * isn't enforced — pharmacist picks the batch); once every line on a
 * prescription has at least one dispense, it drops off this list.
 *
 * Note: doctors currently free-type drug names on a prescription (drug_name
 * is a denormalized text field; the drug FK is optional and usually empty —
 * see doctor/EncounterPage.jsx's DrugForm), so a prescription line can't
 * always be linked to a catalog Drug automatically. The stock picker below
 * is pre-filtered by name match where possible and otherwise shows the full
 * batch list so the pharmacist can pick the right one by eye.
 */
import { useMemo, useState } from "react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useApi }    from "../../hooks/useApi";
import { useToast }  from "../../hooks/useToast";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import PaginationControls from "../../components/common/PaginationControls";

function DispenseModal({ item, rx, stock, onClose, onDone }) {
  const { toastSuccess, toastApiError } = useToast();
  const nameWords = item.drug_name.toLowerCase().split(/\s+/).filter(Boolean);
  const matches = stock.filter(s => s.quantity > 0 &&
    nameWords.some(w => w.length > 2 && s.drug_name.toLowerCase().includes(w)));
  const candidates = matches.length ? matches : stock.filter(s => s.quantity > 0);

  const [stockId, setStockId] = useState(candidates[0]?.id || "");
  const [qty, setQty] = useState("1");
  const [saving, setSaving] = useState(false);
  const selected = stock.find(s => s.id === Number(stockId));

  async function submit(e) {
    e.preventDefault();
    if (!stockId || !qty) return;
    setSaving(true);
    try {
      await apiClient.post(API_ENDPOINTS.PHARMACY.DISPENSE, {
        prescription_item: item.id, stock: Number(stockId), quantity: parseInt(qty, 10),
      });
      toastSuccess("Dispensed.");
      onDone();
      onClose();
    } catch (err) {
      toastApiError(err, "Could not dispense this item.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(0,0,0,0.45)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <form onSubmit={submit} style={{ background: "var(--color-surface)", borderRadius: 16, width: "100%", maxWidth: 460, padding: 28, boxShadow: "0 20px 60px rgba(0,0,0,0.3)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
          <h2 style={{ margin: 0, fontSize: 17 }}>{item.drug_name}</h2>
          <button type="button" onClick={onClose} style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer" }}>✕</button>
        </div>
        <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 4 }}>
          {rx.patient_name} · {rx.patient_uhid}
        </div>
        <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 18 }}>
          {item.dose}{item.unit} · {item.frequency} · {item.route}{item.duration_days ? ` × ${item.duration_days}d` : ""}
          {item.instructions ? ` — ${item.instructions}` : ""}
        </div>

        <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>STOCK BATCH *</label>
        {candidates.length === 0 ? (
          <div style={{ fontSize: 13, color: "#991B1B", marginBottom: 14 }}>No stock with quantity on hand. Receive stock first.</div>
        ) : (
          <select className="form-input" value={stockId} onChange={e => setStockId(e.target.value)}
            style={{ width: "100%", boxSizing: "border-box", marginBottom: 14 }}>
            {candidates.map(s => (
              <option key={s.id} value={s.id}>
                {s.drug_name}{s.batch_number ? ` — Batch ${s.batch_number}` : ""} ({s.quantity} available)
              </option>
            ))}
          </select>
        )}

        <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>QUANTITY TO DISPENSE *</label>
        <input className="form-input" type="number" min="1" max={selected?.quantity || undefined} value={qty}
          onChange={e => setQty(e.target.value)} style={{ width: "100%", boxSizing: "border-box", marginBottom: 6 }} required />
        {selected && Number(qty) > selected.quantity && (
          <div style={{ fontSize: 11, color: "#991B1B", marginBottom: 8 }}>Only {selected.quantity} available in this batch.</div>
        )}

        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 14 }}>
          <button type="button" className="btn-outline" disabled={saving} onClick={onClose} style={{ padding: "9px 16px" }}>Cancel</button>
          <button type="submit" className="btn-primary" style={{ padding: "9px 16px" }}
            disabled={saving || !stockId || !qty || (selected && Number(qty) > selected.quantity)}>
            {saving ? "Dispensing…" : "Dispense"}
          </button>
        </div>
      </form>
    </div>
  );
}

const RX_CHOICE_BADGE = {
  pending:  { label: "Awaiting patient choice", bg: "var(--color-border)", color: "var(--color-text-muted)" },
  in_house: { label: "Confirmed — in-house",    bg: "#DBEAFE", color: "#1E40AF" },
  outside:  { label: "Getting it elsewhere",    bg: "#FEE2E2", color: "#991B1B" },
};
const RX_PAY_BADGE = {
  unpaid:         { label: "Unpaid",  color: "var(--color-text-muted)" },
  pending_online: { label: "Payment pending online", color: "var(--color-warning)" },
  paid:           { label: "Paid",    color: "var(--color-success)" },
};

// The counter workflow: a patient walks up and quotes their Rx number
// (shown to them in the portal once they choose in-house). This looks it
// up directly — regardless of the active/dispensed tab or pagination —
// and pops up the full prescription with patient details, same idea as a
// lab tech searching by report number.
function RxLookupBar({ onFound }) {
  const { toastApiError, toastError } = useToast();
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);

  async function search(e) {
    e.preventDefault();
    if (!q.trim()) { toastError("Enter the Rx number the patient quoted."); return; }
    setLoading(true);
    try {
      const { data: res } = await apiClient.get(API_ENDPOINTS.PHARMACY.PRESCRIPTION_LOOKUP, {
        params: { rx_number: q.trim() },
      });
      onFound(res.data);
    } catch (err) {
      toastApiError(err, "No prescription found for that number.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={search} className="card" style={{ padding: "14px 20px", marginBottom: 16, display: "flex", gap: 10, alignItems: "center" }}>
      <span style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text-muted)", whiteSpace: "nowrap" }}>PATIENT QUOTED A NUMBER?</span>
      <input className="form-input" value={q} onChange={e => setQ(e.target.value)}
        placeholder="e.g. RX-000123" style={{ flex: 1, maxWidth: 220 }} />
      <button type="submit" className="btn-primary" style={{ fontSize: 12, padding: "7px 16px" }} disabled={loading}>
        {loading ? "Looking up…" : "Find"}
      </button>
    </form>
  );
}

// Full-detail popup for a looked-up prescription — patient info up top,
// dispensable items below, reusing the same DispenseModal flow the queue
// list uses.
function RxLookupModal({ rx, stock, onClose, onDone, onDispenseClick }) {
  const choiceBadge = RX_CHOICE_BADGE[rx.patient_choice] || RX_CHOICE_BADGE.pending;
  const payBadge = RX_PAY_BADGE[rx.payment_status] || RX_PAY_BADGE.unpaid;

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(0,0,0,0.45)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div style={{ background: "var(--color-surface)", borderRadius: 16, width: "100%", maxWidth: 560, maxHeight: "85vh", overflowY: "auto", padding: 28, boxShadow: "0 20px 60px rgba(0,0,0,0.3)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 4 }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 18 }}>{rx.rx_number}</h2>
            <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 2 }}>{rx.doctor_name}</div>
          </div>
          <button type="button" onClick={onClose} style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer" }}>✕</button>
        </div>

        <div style={{ display: "flex", gap: 8, margin: "10px 0 16px" }}>
          <span style={{ padding: "3px 10px", borderRadius: 12, fontSize: 11, fontWeight: 700, background: choiceBadge.bg, color: choiceBadge.color }}>
            {choiceBadge.label}
          </span>
          <span style={{ fontSize: 11, fontWeight: 700, color: payBadge.color, alignSelf: "center" }}>{payBadge.label}</span>
        </div>

        <div style={{ background: "var(--color-bg)", borderRadius: 10, padding: "12px 16px", marginBottom: 16 }}>
          <div style={{ fontWeight: 700, fontSize: 14 }}>{rx.patient_name}</div>
          <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
            {rx.patient_uhid}{rx.patient_phone ? ` · ${rx.patient_phone}` : ""}
          </div>
        </div>

        <table className="data-table" style={{ margin: 0 }}>
          <thead>
            <tr><th>Drug</th><th>Dose</th><th>Frequency</th><th>Dispensed</th><th style={{ width: 100 }}>Action</th></tr>
          </thead>
          <tbody>
            {rx.items.map(it => (
              <tr key={it.id}>
                <td style={{ fontSize: 13, fontWeight: 600 }}>{it.drug_name}</td>
                <td style={{ fontSize: 12 }}>{it.dose}{it.unit}</td>
                <td style={{ fontSize: 12 }}>{it.frequency} · {it.route}</td>
                <td style={{ fontSize: 12 }}>
                  {it.dispensed_qty > 0
                    ? <span className="badge badge--success">{it.dispensed_qty} given</span>
                    : <span style={{ color: "var(--color-text-muted)" }}>—</span>}
                </td>
                <td>
                  <button className="btn-primary" style={{ fontSize: 11, padding: "5px 10px" }}
                    onClick={() => onDispenseClick({ item: it, rx })}>
                    Dispense
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function PrescriptionsPage() {
  const [tab, setTab] = useState("active");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const { data, isLoading, refetch } = useApi(API_ENDPOINTS.PHARMACY.PRESCRIPTIONS, { params: { status: tab, page, page_size: pageSize } });
  // Full (unpaginated) batch list — the dispense modal below name-matches
  // against every batch on hand, not just whatever's on the current page of
  // this list, so this stays a plain high-cap fetch rather than a paged one.
  const { data: stockData, refetch: refetchStock } = useApi(API_ENDPOINTS.PHARMACY.STOCK, { params: { page_size: 500 } });
  const stock = stockData?.results || [];
  const prescriptions = data?.results || [];
  const pagination = data?.pagination || null;

  const [target, setTarget] = useState(null); // { item, rx }
  const [lookedUp, setLookedUp] = useState(null); // rx found via the token search bar

  function switchTab(val) { setTab(val); setPage(1); }
  function refreshAll() { refetch(); refetchStock(); }

  return (
    <AppShell>
      <PageShell title="Prescriptions">
        <RxLookupBar onFound={setLookedUp} />

        <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
          {[["active", "Pending"], ["dispensed", "Dispensed"]].map(([val, label]) => (
            <button key={val} className={tab === val ? "btn-primary" : "btn-outline"}
              style={{ fontSize: 12, padding: "6px 16px" }} onClick={() => switchTab(val)}>
              {label}
            </button>
          ))}
        </div>

        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 20px", borderBottom: "1px solid var(--color-border)" }}>
            <span className="dot-label dot-label--green">{tab === "active" ? "Waiting to be dispensed" : "Completed"} ({pagination ? pagination.total_count : prescriptions.length})</span>
            <button className="btn-outline" style={{ fontSize: 12, padding: "5px 14px" }} onClick={refreshAll}>Refresh</button>
          </div>

          {isLoading ? (
            <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
          ) : prescriptions.length === 0 ? (
            <div style={{ padding: 48, textAlign: "center", color: "var(--color-text-muted)" }}>
              {tab === "active" ? "Nothing waiting to be dispensed right now." : "No dispensed prescriptions yet."}
            </div>
          ) : (
            <div>
              {prescriptions.map(rx => (
                <div key={rx.id} style={{ padding: "16px 20px", borderBottom: "1px solid var(--color-border)" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 10 }}>
                    <div>
                      <span style={{ fontWeight: 600, fontSize: 13 }}>{rx.patient_name}</span>
                      <span style={{ fontSize: 11, color: "var(--color-text-muted)", marginLeft: 8 }}>{rx.patient_uhid}</span>
                      {rx.patient_choice && (() => {
                        const b = RX_CHOICE_BADGE[rx.patient_choice] || RX_CHOICE_BADGE.pending;
                        return (
                          <span style={{ marginLeft: 8, padding: "2px 8px", borderRadius: 10, fontSize: 10, fontWeight: 700, background: b.bg, color: b.color }}>
                            {b.label}
                          </span>
                        );
                      })()}
                    </div>
                    <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
                      {rx.rx_number} · {rx.doctor_name}
                    </div>
                  </div>
                  <table className="data-table" style={{ margin: 0 }}>
                    <thead>
                      <tr>
                        <th>Drug</th>
                        <th>Dose</th>
                        <th>Frequency</th>
                        <th>Dispensed</th>
                        {tab === "active" && <th style={{ width: 120 }}>Action</th>}
                      </tr>
                    </thead>
                    <tbody>
                      {rx.items.map(it => (
                        <tr key={it.id}>
                          <td style={{ fontSize: 13, fontWeight: 600 }}>{it.drug_name}</td>
                          <td style={{ fontSize: 12 }}>{it.dose}{it.unit}</td>
                          <td style={{ fontSize: 12 }}>{it.frequency} · {it.route}</td>
                          <td style={{ fontSize: 12 }}>
                            {it.dispensed_qty > 0
                              ? <span className="badge badge--success">{it.dispensed_qty} given</span>
                              : <span style={{ color: "var(--color-text-muted)" }}>—</span>}
                          </td>
                          {tab === "active" && (
                            <td>
                              <button className="btn-primary" style={{ fontSize: 11, padding: "5px 10px" }}
                                onClick={() => setTarget({ item: it, rx })}>
                                Dispense
                              </button>
                            </td>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
            </div>
          )}
          <PaginationControls
            pagination={pagination}
            page={page} pageSize={pageSize}
            onPageChange={setPage} onPageSizeChange={setPageSize}
          />
        </div>

        {lookedUp && !target && (
          <RxLookupModal rx={lookedUp} stock={stock}
            onClose={() => setLookedUp(null)}
            onDone={refreshAll}
            onDispenseClick={setTarget} />
        )}

        {target && (
          <DispenseModal item={target.item} rx={target.rx} stock={stock}
            onClose={() => { setTarget(null); if (lookedUp) refreshAll(); }}
            onDone={() => { refreshAll(); setLookedUp(null); }} />
        )}
      </PageShell>
    </AppShell>
  );
}
