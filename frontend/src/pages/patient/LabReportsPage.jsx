/**
 * pages/patient/LabReportsPage.jsx
 * ----------------------------------
 * Every test a doctor has ordered, each as its own card — no retyping the
 * test name or guessing the type, it's already known from the order. Patient
 * picks in-house (see price/turnaround, pick how to pay) or outside (upload
 * the report once they have it). A generic "Attach a report" card stays
 * below for anything not tied to a specific order (old records, scans,
 * prescriptions from elsewhere).
 */
import { useState, useRef } from "react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { usePaginatedList } from "../../hooks/usePaginatedList";
import { useToast }  from "../../hooks/useToast";
import apiClient      from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";

const DOC_TYPES = [
  { value: "lab_report",        label: "Lab Report" },
  { value: "prescription",      label: "Prescription" },
  { value: "scan",              label: "Scan / Imaging" },
  { value: "discharge_summary", label: "Discharge Summary" },
  { value: "other",             label: "Other" },
];

const MAX_FILE_BYTES = 5 * 1024 * 1024; // 5MB — matches the backend's base64 guard

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload  = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function estimatedReady(orderedAt, turnaroundHours) {
  if (!orderedAt || !turnaroundHours) return null;
  const ready = new Date(new Date(orderedAt).getTime() + turnaroundHours * 3600 * 1000);
  return ready.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

// Same statuses the doctor and nurse already see for this order — the
// patient was only ever shown a generic "In progress", which hid real
// progress (sample collected, being processed, etc.).
const LAB_STATUS_BADGE = {
  ordered:    { label: "Order placed",      bg: "var(--color-border)", color: "var(--color-text-muted)" },
  collected:  { label: "Sample collected",  bg: "#DBEAFE", color: "#1E40AF" },
  processing: { label: "Processing",        bg: "#FEF3C7", color: "#92400E" },
  completed:  { label: "Finalizing",        bg: "#FEF3C7", color: "#92400E" },
  cancelled:  { label: "Cancelled",         bg: "#FEE2E2", color: "#991B1B" },
};

// Plain-language line shown in the body — the badge alone is easy to miss,
// and "completed" is deliberately NOT called "done" here: the status can
// reach completed a moment before the report itself is released, so calling
// it "Completed" with no result to show is what confused this exact case.
const LAB_PROGRESS_MESSAGE = {
  ordered:    "Awaiting sample collection at the lab.",
  collected:  "Sample collected — awaiting processing.",
  processing: "Your sample is being processed.",
  completed:  "Processing is complete — your result will appear here shortly.",
  cancelled:  "This test was cancelled.",
};

const PAY_PREF_LABEL = { pay_at_lab: "Pay at the lab", pay_online: "Pay online (coming soon)" };

// Payment can only be picked/changed while the test is still just an order —
// once the lab has actually collected the sample, switching "how I'll pay"
// no longer makes operational sense, so it locks (matches the same
// confirm-then-lock pattern used on the nurse's Tasks page).
function InHouseBody({ order, saving, chooseAndSave }) {
  const [editingPayment, setEditingPayment] = useState(!order.payment_preference);
  const canEditPayment = order.status === "ordered";
  const progress = LAB_PROGRESS_MESSAGE[order.status] || LAB_PROGRESS_MESSAGE.ordered;

  return (
    <div style={{ background: "var(--color-warning-light)", border: "1px solid var(--color-warning)", borderRadius: 10, padding: "12px 16px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 8 }}>
        <span>{order.price != null ? `₹${order.price}` : "Price not set"}</span>
        {order.turnaround_hours && (
          <span style={{ color: "var(--color-text-muted)" }}>
            Est. ready {estimatedReady(order.ordered_at, order.turnaround_hours)}
          </span>
        )}
      </div>
      <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 10 }}>
        Visit the laboratory at {order.hospital} with your token.
      </div>

      {/* Single clear line for what's happening right now — replaces the
          separate status text + still-open payment box that made this
          confusing (e.g. "Completed" showing up with nothing to see). */}
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10 }}>
        {progress}
      </div>

      {canEditPayment && editingPayment ? (
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <span style={{ fontSize: 12, fontWeight: 600 }}>Payment:</span>
          <button
            className={order.payment_preference === "pay_at_lab" ? "btn-primary" : "btn-outline"}
            style={{ fontSize: 12, padding: "5px 12px" }}
            disabled={saving}
            onClick={() => { chooseAndSave("in_house", "pay_at_lab"); setEditingPayment(false); }}
          >
            Pay at the lab
          </button>
          <button
            className={order.payment_preference === "pay_online" ? "btn-primary" : "btn-outline"}
            style={{ fontSize: 12, padding: "5px 12px" }}
            disabled={saving}
            title="Online payment is coming soon — this just lets the lab know your preference."
            onClick={() => { chooseAndSave("in_house", "pay_online"); setEditingPayment(false); }}
          >
            Pay online (coming soon)
          </button>
        </div>
      ) : (
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
          <span style={{ fontWeight: 600 }}>Payment:</span>
          <span>{order.payment_preference ? PAY_PREF_LABEL[order.payment_preference] : "Not set"}</span>
          {order.payment_preference && (
            <span style={{ color: "#166534" }}>✓</span>
          )}
          {canEditPayment && (
            <button
              type="button"
              onClick={() => setEditingPayment(true)}
              style={{ background: "none", border: "none", color: "var(--color-primary)", fontSize: 11, cursor: "pointer", padding: 0, marginLeft: "auto" }}
            >
              Change
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// Fetches the actual file for a delivered in-house report on demand and
// opens it in a new tab — the list endpoint only ever sends has_file (a
// boolean) to keep the payload light, same pattern as the doctor/nurse
// document viewers.
function ViewInHouseReportButton({ tenantDb, requestId }) {
  const { toastApiError } = useToast();
  const [loading, setLoading] = useState(false);

  async function open() {
    setLoading(true);
    try {
      const res = await apiClient.get(API_ENDPOINTS.PORTAL.LAB_REPORT_FILE(tenantDb, requestId));
      const data = res.data?.data || res.data;
      if (data?.file_data) {
        const win = window.open();
        if (win) win.location.href = data.file_data;
      }
    } catch (err) {
      toastApiError(err, "Could not load the report.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <button className="btn-outline" style={{ fontSize: 12, padding: "5px 14px" }} disabled={loading} onClick={open}>
      {loading ? "Loading…" : "View Report"}
    </button>
  );
}

// ─── One ordered test, self-contained: choice -> (price/pay | upload) -> result ──
function LabOrderCard({ order, onChanged }) {
  const { toastSuccess, toastApiError, toastError } = useToast();
  const fileRef = useRef(null);
  const [saving, setSaving] = useState(false);
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);

  async function chooseAndSave(choice, paymentPreference) {
    setSaving(true);
    try {
      await apiClient.post(API_ENDPOINTS.PORTAL.LAB_ORDER_CHOICE, {
        tenant_db: order.tenant_db, request_id: order.id,
        patient_choice: choice, payment_preference: paymentPreference || "",
      });
      toastSuccess(choice === "in_house" ? "Got it — see you at the lab." : "Okay — upload the report once you have it.");
      onChanged?.();
    } catch (err) {
      toastApiError(err, "Could not save your choice.");
    } finally {
      setSaving(false);
    }
  }

  async function uploadOutsideReport() {
    if (!file) { toastError("Choose a file first."); return; }
    if (file.size > MAX_FILE_BYTES) { toastError("File is too large — please attach something under 5MB."); return; }
    setUploading(true);
    try {
      const dataUrl = await fileToDataUrl(file);
      await apiClient.post(API_ENDPOINTS.PORTAL.DOCUMENTS, {
        title: order.test_name, doc_type: "lab_report",
        file_data: dataUrl, file_name: file.name, mime_type: file.type,
        source_ref: order.source_ref,
      });
      toastSuccess("Report attached — your doctor will be able to see it.");
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
      onChanged?.();
    } catch (err) {
      toastApiError(err, "Could not upload the report.");
    } finally {
      setUploading(false);
    }
  }

  const delivered = order.report?.status === "delivered";

  return (
    <div className="card" style={{ padding: "16px 20px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
        <span style={{ fontFamily: "var(--font-display)", fontWeight: 600, fontSize: 16 }}>{order.test_name}</span>
        {delivered ? (
          <span className="badge badge--success">Ready</span>
        ) : order.patient_choice === "pending" ? (
          <span className="badge badge--warning">Choose an option</span>
        ) : (
          (() => {
            const s = LAB_STATUS_BADGE[order.status] || LAB_STATUS_BADGE.ordered;
            return (
              <span style={{ padding: "3px 10px", borderRadius: 12, fontSize: 11, fontWeight: 700, background: s.bg, color: s.color }}>
                {s.label}
              </span>
            );
          })()
        )}
      </div>
      <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 12 }}>
        {order.hospital} · ordered {order.ordered_at ? new Date(order.ordered_at).toLocaleDateString("en-IN") : ""}
      </div>

      {/* Result delivered — show it and stop, regardless of path taken */}
      {delivered ? (
        <div style={{ background: "#F0FDF4", border: "1px solid #BBF7D0", borderRadius: 10, padding: "12px 16px" }}>
          <div style={{ fontWeight: 700, fontSize: 13, color: "#166534", marginBottom: 4 }}>✓ Result</div>
          <div style={{ fontSize: 13, color: "var(--color-text-secondary)", marginBottom: order.report.has_file ? 10 : 0 }}>
            {order.report.result_summary || "Report released — ask your hospital for the full file."}
          </div>
          {order.report.has_file && (
            <ViewInHouseReportButton tenantDb={order.tenant_db} requestId={order.id} />
          )}
        </div>

      /* Pending choice — patient hasn't decided yet */
      ) : order.patient_choice === "pending" ? (
        <div style={{ display: "flex", gap: 10 }}>
          <button className="btn-primary" disabled={saving} style={{ flex: 1 }}
            onClick={() => chooseAndSave("in_house", "pay_at_lab")}>
            {order.hospital ? `Conduct at ${order.hospital}` : "Conduct at this hospital"}
          </button>
          <button className="btn-outline" disabled={saving} style={{ flex: 1 }}
            onClick={() => chooseAndSave("outside", "")}>
            Conduct at an external facility
          </button>
        </div>

      /* In-house, awaiting the lab */
      ) : order.patient_choice === "in_house" ? (
        <InHouseBody order={order} saving={saving} chooseAndSave={chooseAndSave} />


      /* Outside — upload once they have the report */
      ) : (
        <div>
          {order.attached_document ? (
            <div style={{ background: "#F0FDF4", border: "1px solid #BBF7D0", borderRadius: 10, padding: "10px 14px", fontSize: 13, color: "#166534" }}>
              ✓ Report attached — {order.attached_document.title}
              {order.attached_document.created_at && ` (${new Date(order.attached_document.created_at).toLocaleDateString("en-IN")})`}
            </div>
          ) : (
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <input ref={fileRef} type="file" accept=".pdf,image/*" className="form-input" style={{ flex: 1, minWidth: 180 }}
                onChange={e => setFile(e.target.files?.[0] || null)} />
              <button className="btn-primary" disabled={uploading} style={{ fontSize: 12, padding: "7px 16px" }}
                onClick={uploadOutsideReport}>
                {uploading ? "Uploading…" : "Upload report"}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function UploadReportCard({ onUploaded }) {
  const { toastSuccess, toastApiError, toastError } = useToast();
  const fileRef = useRef(null);
  const [title, setTitle] = useState("");
  const [docType, setDocType] = useState("lab_report");
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);

  async function submit(e) {
    e.preventDefault();
    if (!title.trim()) { toastError("Give the report a title."); return; }
    if (!file) { toastError("Choose a file to attach."); return; }
    if (file.size > MAX_FILE_BYTES) { toastError("File is too large — please attach something under 5MB."); return; }

    setUploading(true);
    try {
      const dataUrl = await fileToDataUrl(file);
      await apiClient.post(API_ENDPOINTS.PORTAL.DOCUMENTS, {
        title: title.trim(),
        doc_type: docType,
        file_data: dataUrl,
        file_name: file.name,
        mime_type: file.type,
      });
      toastSuccess("Report attached.");
      setTitle("");
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
      onUploaded?.();
    } catch (err) {
      toastApiError(err, "Could not upload the report.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <form onSubmit={submit} className="card" style={{ padding: "16px 20px", marginBottom: 18 }}>
      <div style={{ fontFamily: "var(--font-display)", fontWeight: 600, fontSize: 15, marginBottom: 4 }}>
        Attach something else
      </div>
      <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 14 }}>
        For anything not listed above — an old report, scan, or prescription from elsewhere.
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr 1.4fr auto", gap: 10, alignItems: "end" }}>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>TITLE</label>
          <input className="form-input" value={title} onChange={e => setTitle(e.target.value)} placeholder="e.g. CBC report, Jan 2026" />
        </div>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>TYPE</label>
          <select className="form-input" value={docType} onChange={e => setDocType(e.target.value)}>
            {DOC_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </div>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>FILE</label>
          <input ref={fileRef} type="file" accept=".pdf,image/*" className="form-input"
            onChange={e => setFile(e.target.files?.[0] || null)} />
        </div>
        <button type="submit" disabled={uploading} className="btn-primary" style={{ height: 38, whiteSpace: "nowrap" }}>
          {uploading ? "Uploading…" : "+ Attach"}
        </button>
      </div>
    </form>
  );
}

function MyDocumentsList({ docs, isLoading }) {
  if (isLoading || docs.length === 0) return null;
  return (
    <div className="card" style={{ padding: "16px 20px", marginBottom: 18 }}>
      <div style={{ fontFamily: "var(--font-display)", fontWeight: 600, fontSize: 15, marginBottom: 10 }}>
        Your attached reports
      </div>
      <div style={{ display: "grid", gap: 8 }}>
        {docs.map(d => (
          <div key={d.id} style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "8px 12px", background: "var(--color-bg)", borderRadius: 8, fontSize: 13,
          }}>
            <div>
              <span style={{ fontWeight: 600 }}>{d.title}</span>
              <span style={{ color: "var(--color-text-muted)", marginLeft: 8, fontSize: 11 }}>
                {DOC_TYPES.find(t => t.value === d.doc_type)?.label || d.doc_type}
                {d.created_at && ` · ${new Date(d.created_at).toLocaleDateString("en-IN")}`}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function PatientLabReportsPage() {
  const { items: orders, isLoading: ordersLoading, refetch: refetchOrders } =
    usePaginatedList(API_ENDPOINTS.PORTAL.LAB_ORDERS, { pageSize: 20 });
  const { items: docs, isLoading: docsLoading, refetch: refetchDocs } =
    usePaginatedList(API_ENDPOINTS.PORTAL.DOCUMENTS, { pageSize: 20 });

  return (
    <AppShell>
      <PageShell title="Lab Tests & Reports">
        {ordersLoading ? (
          <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)", marginBottom: 18 }}>
            Loading…
          </div>
        ) : orders.length === 0 ? (
          <div className="card" style={{ padding: 32, textAlign: "center", marginBottom: 18 }}>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>No tests ordered yet</div>
            <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
              When your doctor orders lab work, it'll appear here.
            </div>
          </div>
        ) : (
          <div style={{ display: "grid", gap: 14, marginBottom: 18 }}>
            {orders.map(o => (
              <LabOrderCard key={`${o.tenant_db}-${o.id}`} order={o} onChanged={() => { refetchOrders(); refetchDocs(); }} />
            ))}
          </div>
        )}

        <UploadReportCard onUploaded={refetchDocs} />
        <MyDocumentsList docs={docs} isLoading={docsLoading} />
      </PageShell>
    </AppShell>
  );
}
