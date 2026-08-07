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
import { useState } from "react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useApi }    from "../../hooks/useApi";
import { useToast }  from "../../hooks/useToast";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";

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

function UploadModal({ order, onClose, onDone }) {
  const { toastSuccess, toastApiError } = useToast();
  const [summary, setSummary] = useState("");
  const [file, setFile] = useState(null);
  const [saving, setSaving] = useState(false);

  async function submit(deliver) {
    setSaving(true);
    try {
      const body = { result_summary: summary, deliver };
      if (file) {
        body.file_data = await fileToDataUrl(file);
        body.file_name = file.name;
        body.mime_type = file.type;
      }
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
      <div style={{ background: "var(--color-surface)", borderRadius: 16, width: "100%", maxWidth: 480, padding: 28, boxShadow: "0 20px 60px rgba(0,0,0,0.3)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
          <h2 style={{ margin: 0, fontSize: 17 }}>{order.test_name}</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer" }}>✕</button>
        </div>
        <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 18 }}>
          {order.patient_name} · {order.patient_uhid}
        </div>

        <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>RESULT SUMMARY (optional)</label>
        <textarea className="form-input" rows={4} value={summary} onChange={e => setSummary(e.target.value)}
          placeholder="e.g. Hb 13.2 g/dL, WBC 7200/µL, Platelets 250,000/µL — all within normal range."
          style={{ width: "100%", boxSizing: "border-box", marginBottom: 14, resize: "vertical" }} />

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

export default function RequestsPage() {
  const { toastSuccess, toastApiError } = useToast();
  const [uploadOrder, setUploadOrder] = useState(null);
  const [busy, setBusy] = useState(null);

  const { data, isLoading, refetch } = useApi(API_ENDPOINTS.LAB.REQUESTS, { params: { page_size: 100 } });
  const orders = (data?.results || []).filter(o =>
    o.patient_choice === "in_house" && o.status !== "cancelled"
  );

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
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 20px", borderBottom: "1px solid var(--color-border)" }}>
            <span className="dot-label dot-label--green">In-house test queue</span>
            <button className="btn-outline" style={{ fontSize: 12, padding: "5px 14px" }} onClick={refetch}>Refresh</button>
          </div>

          {isLoading ? (
            <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
          ) : orders.length === 0 ? (
            <div style={{ padding: 48, textAlign: "center", color: "var(--color-text-muted)" }}>
              No in-house tests waiting right now.
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
                {orders.map(o => {
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
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {uploadOrder && (
          <UploadModal order={uploadOrder} onClose={() => setUploadOrder(null)} onDone={refetch} />
        )}
      </PageShell>
    </AppShell>
  );
}
