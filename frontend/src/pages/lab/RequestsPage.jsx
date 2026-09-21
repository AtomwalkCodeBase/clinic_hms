/**
 * pages/lab/RequestsPage.jsx
 * ----------------------------
 * Lab tech's working queue — in-house tests only (outside ones are the
 * patient's own responsibility to get done and attach). Move a sample
 * through ordered -> collected -> processing, then upload the result
 * (summary + optional file) and deliver it in one step. Delivering fires
 * the existing HIE signal, so it shows up on the doctor's and nurse's
 * views automatically without anything extra on their end.
 */
import { useState, useMemo } from "react";
import { Filter, X, Baby, Plus } from "lucide-react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useApi }    from "../../hooks/useApi";
import { useToast }  from "../../hooks/useToast";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import { formatYearsMonths } from "../../utils/age";

const STATUS_BADGE = {
  ordered:    { label: "Ordered",    bg: "var(--color-border)", color: "var(--color-text-muted)" },
  collected:  { label: "Collected",  bg: "#DBEAFE", color: "#1E40AF" },
  processing: { label: "Processing", bg: "#FEF3C7", color: "#92400E" },
  completed:  { label: "Completed",  bg: "#D1FAE5", color: "#065F46" },
  cancelled:  { label: "Cancelled",  bg: "#FEE2E2", color: "#991B1B" },
};

const NEXT_STATUS = { ordered: "collected", collected: "processing" };
const NEXT_LABEL   = { ordered: "Mark Collected", collected: "Start Processing" };

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload  = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

const EMPTY_ITEM = { parameter_name: "", result_value: "", unit: "", reference_range: "", is_abnormal: false };

function UploadModal({ order, onClose, onDone }) {
  const { toastSuccess, toastApiError } = useToast();
  const [summary, setSummary] = useState("");
  const [file, setFile] = useState(null);
  const [saving, setSaving] = useState(false);
  // Structured per-parameter results — optional, additive to the summary
  // text + file above. Each row becomes a LabReportItem (see
  // apps.lab.models) with its own reference_range, so the doctor/patient
  // portal can show "13.2 g/dL (12.0–15.5)" per value instead of only a
  // free-text summary paragraph.
  const [items, setItems] = useState([]);

  const isMinor = order.patient_age != null && order.patient_age < 18;
  const ageLabel = isMinor ? (formatYearsMonths(order.patient_age, order.patient_age_months) || `${order.patient_age}y`) : "";

  function addItem() {
    setItems(prev => [...prev, { ...EMPTY_ITEM }]);
  }
  function updateItem(i, field, value) {
    setItems(prev => prev.map((it, idx) => idx === i ? { ...it, [field]: value } : it));
  }
  function removeItem(i) {
    setItems(prev => prev.filter((_, idx) => idx !== i));
  }

  async function submit(deliver) {
    setSaving(true);
    try {
      const body = { result_summary: summary, deliver };
      if (file) {
        body.file_data = await fileToDataUrl(file);
        body.file_name = file.name;
        body.mime_type = file.type;
      }
      const cleanItems = items
        .filter(it => it.parameter_name.trim() && it.result_value.trim())
        .map(it => ({ ...it, parameter_name: it.parameter_name.trim(), result_value: it.result_value.trim() }));
      if (cleanItems.length) body.items = cleanItems;
      await apiClient.post(API_ENDPOINTS.LAB.REQUEST_REPORT(order.id), body);
      toastSuccess(deliver ? "Report delivered." : "Draft saved.");
      onDone();
      onClose();
    } catch (err) {
      toastApiError(err, "Could not save the report.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(0,0,0,0.45)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div style={{ background: "var(--color-surface)", borderRadius: 16, width: "100%", maxWidth: 560, padding: 28, boxShadow: "0 20px 60px rgba(0,0,0,0.3)", maxHeight: "90vh", overflowY: "auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
          <h2 style={{ margin: 0, fontSize: 17 }}>{order.test_name}</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer" }}>✕</button>
        </div>
        <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 12 }}>
          {order.patient_name} · {order.patient_uhid}
        </div>

        {isMinor && (
          <div style={{
            display: "flex", alignItems: "flex-start", gap: 8, fontSize: 12, padding: "9px 12px",
            borderRadius: 8, background: "#F1E9FA", color: "#6B3FA0", marginBottom: 16,
          }}>
            <Baby size={14} style={{ marginTop: 1, flexShrink: 0 }} />
            <span>
              Pediatric patient ({ageLabel}) — normal reference ranges differ from adult defaults and
              vary by test/analyzer. Enter the age-appropriate range for each result below rather than
              a default adult range.
            </span>
          </div>
        )}

        <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>RESULT SUMMARY (optional)</label>
        <textarea className="form-input" rows={3} value={summary} onChange={e => setSummary(e.target.value)}
          placeholder="e.g. Hb 13.2 g/dL, WBC 7200/µL, Platelets 250,000/µL — all within normal range."
          style={{ width: "100%", boxSizing: "border-box", marginBottom: 14, resize: "vertical" }} />

        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)" }}>STRUCTURED RESULTS (optional)</label>
          <button type="button" onClick={addItem} className="btn-outline"
            style={{ fontSize: 11, padding: "4px 10px", display: "inline-flex", alignItems: "center", gap: 4 }}>
            <Plus size={12} /> Add parameter
          </button>
        </div>
        {items.length > 0 && (
          <div style={{ display: "grid", gap: 8, marginBottom: 14 }}>
            {items.map((it, i) => (
              <div key={i} style={{ border: "1px solid var(--color-border)", borderRadius: 8, padding: 10, display: "grid", gap: 6 }}>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
                  <input className="form-input" placeholder="Parameter (e.g. Hemoglobin)" value={it.parameter_name}
                    onChange={e => updateItem(i, "parameter_name", e.target.value)} style={{ fontSize: 12 }} />
                  <div style={{ display: "flex", gap: 6 }}>
                    <input className="form-input" placeholder="Value" value={it.result_value}
                      onChange={e => updateItem(i, "result_value", e.target.value)} style={{ fontSize: 12, flex: 1 }} />
                    <input className="form-input" placeholder="Unit" value={it.unit}
                      onChange={e => updateItem(i, "unit", e.target.value)} style={{ fontSize: 12, width: 70 }} />
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  <input className="form-input" placeholder={isMinor ? "Age-appropriate reference range" : "Reference range"}
                    value={it.reference_range} onChange={e => updateItem(i, "reference_range", e.target.value)}
                    style={{ fontSize: 12, flex: 1 }} />
                  <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, whiteSpace: "nowrap" }}>
                    <input type="checkbox" checked={it.is_abnormal}
                      onChange={e => updateItem(i, "is_abnormal", e.target.checked)} />
                    Abnormal
                  </label>
                  <button type="button" onClick={() => removeItem(i)}
                    style={{ background: "none", border: "none", cursor: "pointer", color: "var(--color-danger, #b91c1c)", fontSize: 15, lineHeight: 1 }}>
                    ✕
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>REPORT FILE *</label>
        <input type="file" accept=".pdf,image/*" className="form-input" style={{ width: "100%", boxSizing: "border-box", marginBottom: 6 }}
          onChange={e => setFile(e.target.files?.[0] || null)} />
        <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginBottom: 20 }}>
          Required — this is what the patient, nurse, and doctor will actually open.
        </div>

        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <button className="btn-outline" disabled={saving} onClick={() => submit(false)} style={{ padding: "9px 16px" }}>
            {saving ? "Saving…" : "Save Draft"}
          </button>
          <button className="btn-primary" disabled={saving || !file} onClick={() => submit(true)} style={{ padding: "9px 16px" }}
            title={!file ? "Attach a file to deliver this report" : undefined}>
            {saving ? "Delivering…" : "Upload & Deliver"}
          </button>
        </div>
      </div>
    </div>
  );
}

// The counter workflow: a patient walks up and quotes their request number
// (shown to them in the portal once they choose in-house). This looks it
// up directly — regardless of the queue's own filters/pagination — and
// pops up the full request with patient details, same idea as the
// pharmacist's Rx-number search bar.
function RequestLookupBar({ onFound }) {
  const { toastApiError, toastError } = useToast();
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);

  async function search(e) {
    e.preventDefault();
    if (!q.trim()) { toastError("Enter the request number the patient quoted."); return; }
    setLoading(true);
    try {
      const { data: res } = await apiClient.get(API_ENDPOINTS.LAB.REQUEST_LOOKUP, {
        params: { request_number: q.trim() },
      });
      onFound(res.data);
    } catch (err) {
      toastApiError(err, "No lab request found for that number.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={search} className="card" style={{ padding: "14px 20px", marginBottom: 16, display: "flex", gap: 10, alignItems: "center" }}>
      <span style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text-muted)", whiteSpace: "nowrap" }}>PATIENT QUOTED A NUMBER?</span>
      <input className="form-input" value={q} onChange={e => setQ(e.target.value)}
        placeholder="e.g. LR-000123" style={{ flex: 1, maxWidth: 220 }} />
      <button type="submit" className="btn-primary" style={{ fontSize: 12, padding: "7px 16px" }} disabled={loading}>
        {loading ? "Looking up…" : "Find"}
      </button>
    </form>
  );
}

function RequestLookupModal({ order, onClose, onUpload }) {
  const status = STATUS_BADGE[order.status] || STATUS_BADGE.ordered;
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(0,0,0,0.45)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div style={{ background: "var(--color-surface)", borderRadius: 16, width: "100%", maxWidth: 460, padding: 28, boxShadow: "0 20px 60px rgba(0,0,0,0.3)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 4 }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 18 }}>{order.request_number}</h2>
            <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 2 }}>{order.test_name}</div>
          </div>
          <button type="button" onClick={onClose} style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer" }}>✕</button>
        </div>

        <span style={{ display: "inline-block", margin: "10px 0 16px", padding: "3px 10px", borderRadius: 12, fontSize: 11, fontWeight: 700, background: status.bg, color: status.color }}>
          {status.label}
        </span>

        <div style={{ background: "var(--color-bg)", borderRadius: 10, padding: "12px 16px", marginBottom: 16 }}>
          <div style={{ fontWeight: 700, fontSize: 14 }}>{order.patient_name}</div>
          <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
            {order.patient_uhid}{order.patient_phone ? ` · ${order.patient_phone}` : ""}
          </div>
        </div>

        {order.patient_choice !== "in_house" ? (
          <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
            This patient chose to get the test done elsewhere — nothing to process here.
          </div>
        ) : order.status === "completed" ? (
          <div>
            <div style={{ fontSize: 12, color: "var(--color-success)", marginBottom: 8 }}>
              Report already delivered.
            </div>
            {order.report?.file_data && (
              <button className="btn-outline" style={{ fontSize: 12, padding: "7px 16px" }}
                onClick={() => window.open(order.report.file_data, "_blank", "noopener")}>
                View Report
              </button>
            )}
          </div>
        ) : (order.status === "processing" || order.status === "collected") ? (
          <button className="btn-primary" style={{ fontSize: 12, padding: "7px 16px" }} onClick={() => onUpload(order)}>
            Upload Result
          </button>
        ) : (
          <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
            Waiting on sample collection — advance it from the main queue first.
          </div>
        )}
      </div>
    </div>
  );
}

export default function RequestsPage() {
  const { toastSuccess, toastApiError } = useToast();
  const [uploadOrder, setUploadOrder] = useState(null);
  const [lookedUp, setLookedUp] = useState(null);
  const [busy, setBusy] = useState(null);

  const { data, isLoading, refetch } = useApi(API_ENDPOINTS.LAB.REQUESTS, { params: { page_size: 100 }, pollMs: 20000 });
  const orders = (data?.results || [])
    .filter(o => o.patient_choice === "in_house" && o.status !== "cancelled")
    // FIFO — oldest ordered first, so the queue is worked in the order
    // samples actually came in rather than newest-on-top.
    .sort((a, b) => new Date(a.ordered_at) - new Date(b.ordered_at));

  const [showFilters, setShowFilters] = useState(false);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [urgencyFilter, setUrgencyFilter] = useState("");
  const hasActiveFilters = !!(search || statusFilter || urgencyFilter);

  const filteredOrders = useMemo(() => {
    const q = search.trim().toLowerCase();
    return orders.filter(o => {
      if (q && !(
        o.patient_name?.toLowerCase().includes(q) ||
        o.patient_uhid?.toLowerCase().includes(q) ||
        o.test_name?.toLowerCase().includes(q)
      )) return false;
      if (statusFilter && o.status !== statusFilter) return false;
      if (urgencyFilter && (o.urgency || "routine") !== urgencyFilter) return false;
      return true;
    });
  }, [orders, search, statusFilter, urgencyFilter]);

  function clearFilters() {
    setSearch(""); setStatusFilter(""); setUrgencyFilter("");
  }

  async function advance(order) {
    const next = NEXT_STATUS[order.status];
    if (!next) return;
    setBusy(order.id);
    try {
      await apiClient.patch(API_ENDPOINTS.LAB.REQUEST_STATUS(order.id), { status: next });
      toastSuccess(`Marked ${next}.`);
      refetch();
    } catch (err) {
      toastApiError(err, "Could not update status.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <AppShell>
      <PageShell title="Lab Requests">
        <RequestLookupBar onFound={setLookedUp} />

        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 20px", borderBottom: "1px solid var(--color-border)" }}>
            <span className="dot-label dot-label--green">In-house test queue</span>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn-outline" style={{ fontSize: 12, padding: "5px 14px", display: "inline-flex", alignItems: "center", gap: 6 }}
                onClick={() => setShowFilters(s => !s)}>
                <Filter size={13} /> Filters {hasActiveFilters && <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--color-primary)" }} />}
              </button>
              <button className="btn-outline" style={{ fontSize: 12, padding: "5px 14px" }} onClick={refetch}>Refresh</button>
            </div>
          </div>

          {showFilters && (
            <div style={{
              padding: "14px 20px", borderBottom: "1px solid var(--color-border)", background: "#FAFAFA",
              display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px,1fr))", gap: 10,
            }}>
              <input className="form-input" placeholder="Search patient, UHID, or test…"
                value={search} onChange={e => setSearch(e.target.value)} />
              <select className="form-input" value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
                <option value="">All statuses</option>
                {Object.keys(STATUS_BADGE).filter(s => s !== "cancelled").map(s => (
                  <option key={s} value={s}>{STATUS_BADGE[s].label}</option>
                ))}
              </select>
              <select className="form-input" value={urgencyFilter} onChange={e => setUrgencyFilter(e.target.value)}>
                <option value="">All urgencies</option>
                <option value="urgent">Urgent</option>
                <option value="routine">Routine</option>
              </select>
              {hasActiveFilters && (
                <button className="btn-outline" style={{ fontSize: 12, padding: "5px 14px", display: "inline-flex", alignItems: "center", gap: 6, justifySelf: "start" }}
                  onClick={clearFilters}>
                  <X size={13} /> Clear
                </button>
              )}
            </div>
          )}

          {isLoading ? (
            <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
          ) : filteredOrders.length === 0 ? (
            <div style={{ padding: 48, textAlign: "center", color: "var(--color-text-muted)" }}>
              {orders.length === 0 ? "No in-house tests waiting right now." : "No tests match your filters."}
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Patient</th>
                  <th>Test</th>
                  <th>Urgency</th>
                  <th>Status</th>
                  <th style={{ width: 220 }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {filteredOrders.map(o => {
                  const status = STATUS_BADGE[o.status] || STATUS_BADGE.ordered;
                  return (
                    <tr key={o.id}>
                      <td>
                        <div style={{ fontWeight: 600, fontSize: 13 }}>{o.patient_name}</div>
                        <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>{o.patient_uhid}</div>
                      </td>
                      <td style={{ fontSize: 13 }}>{o.test_name}</td>
                      <td>
                        {o.urgency === "urgent" && (
                          <span className="badge badge--error">Urgent</span>
                        )}
                      </td>
                      <td>
                        <span style={{ padding: "2px 10px", borderRadius: 10, fontSize: 11, fontWeight: 700, background: status.bg, color: status.color }}>
                          {status.label}
                        </span>
                      </td>
                      <td>
                        <div style={{ display: "flex", gap: 6 }}>
                          {NEXT_STATUS[o.status] && (
                            <button className="btn-outline" style={{ fontSize: 11, padding: "5px 10px" }}
                              disabled={busy === o.id} onClick={() => advance(o)}>
                              {NEXT_LABEL[o.status]}
                            </button>
                          )}
                          {(o.status === "processing" || o.status === "collected") && (
                            <button className="btn-primary" style={{ fontSize: 11, padding: "5px 10px" }}
                              onClick={() => setUploadOrder(o)}>
                              Upload Result
                            </button>
                          )}
                          {o.status === "completed" && o.report?.file_data && (
                            <button className="btn-outline" style={{ fontSize: 11, padding: "5px 10px" }}
                              onClick={() => window.open(o.report.file_data, "_blank", "noopener")}>
                              View Report
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {lookedUp && !uploadOrder && (
          <RequestLookupModal order={lookedUp} onClose={() => setLookedUp(null)}
            onUpload={setUploadOrder} />
        )}

        {uploadOrder && (
          <UploadModal order={uploadOrder}
            onClose={() => { setUploadOrder(null); if (lookedUp) refetch(); }}
            onDone={() => { refetch(); setLookedUp(null); }} />
        )}
      </PageShell>
    </AppShell>
  );
}
