/**
 * pages/public/ViewReportPage.jsx
 * --------------------------------
 * What opens when the QR printed on a prescription/lab report is scanned by
 * anything other than the patient app itself — Google Lens, any other
 * camera app, a second phone. The app's own capture screen never lands
 * here: it decodes the same QR and posts straight to the My Reports upload
 * pipeline (apps/patients/portal_views.py) instead of opening a link.
 *
 * Deliberately outside AppShell/ProtectedRoute — the person opening this
 * may have no Atomwalk login at all. Deliberately does NOT fetch or show
 * anything until the patient explicitly taps "Yes, view it" — a bare
 * "Do you want to view this report?" prompt is the only thing rendered on
 * load, so nobody's name/diagnosis/file is exposed to whoever merely
 * pointed a camera at the page. See apps/patients/document_view_views.py
 * for the backend half and core/qr_token.py for how the token in the URL
 * is verified.
 */
import { useState } from "react";
import { useParams } from "react-router-dom";
import { publicClient } from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import { FileText, AlertTriangle, ExternalLink } from "lucide-react";

const DOC_TYPE_LABEL = {
  prescription: "Prescription",
  lab_report: "Lab Report",
  scan: "Scan / Imaging",
  discharge_summary: "Discharge Summary",
  other: "Document",
};

function fmtDate(d) {
  if (!d) return "";
  return new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

export default function ViewReportPage() {
  const { token } = useParams();
  // idle -> confirming -> ready | error
  const [state, setState] = useState({ phase: "idle", doc: null, error: null });

  const handleConfirm = () => {
    setState({ phase: "confirming", doc: null, error: null });
    publicClient.get(API_ENDPOINTS.VIEW_REPORT.RESOLVE(token))
      .then(({ data: res }) => setState({ phase: "ready", doc: res.data, error: null }))
      .catch((err) => setState({
        phase: "error", doc: null,
        error: err.message || "This code is invalid or the document is no longer available.",
      }));
  };

  return (
    <div style={{
      minHeight: "100vh", background: "#f4f6f5", display: "flex", justifyContent: "center",
      alignItems: state.phase === "idle" ? "center" : "flex-start",
      padding: "20px 12px", fontFamily: "system-ui, -apple-system, sans-serif",
    }}>
      <div style={{ width: "100%", maxWidth: 420 }}>
        {state.phase === "idle" && (
          <div style={{ background: "#fff", borderRadius: 12, padding: 28, textAlign: "center", boxShadow: "0 1px 3px rgba(0,0,0,0.08)" }}>
            <FileText size={30} color="#1B5E43" style={{ marginBottom: 12 }} />
            <div style={{ fontWeight: 800, fontSize: 16, marginBottom: 6 }}>Do you want to view this report?</div>
            <div style={{ fontSize: 13, color: "#666", marginBottom: 20 }}>
              This link opens a medical document. Only continue if you're the patient or someone they've shared this printout with.
            </div>
            <button
              onClick={handleConfirm}
              style={{
                background: "#1B5E43", color: "#fff", border: "none", borderRadius: 8,
                padding: "11px 24px", fontSize: 14, fontWeight: 700, cursor: "pointer", width: "100%",
              }}
            >
              Yes, view it
            </button>
          </div>
        )}

        {state.phase === "confirming" && (
          <div style={{ background: "#fff", borderRadius: 12, padding: 30, textAlign: "center", color: "#666", fontSize: 13 }}>
            Loading…
          </div>
        )}

        {state.phase === "error" && (
          <div style={{ background: "#fff", borderRadius: 12, padding: 24, textAlign: "center" }}>
            <AlertTriangle size={28} color="#b91c1c" style={{ marginBottom: 10 }} />
            <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 4 }}>Can't open this document</div>
            <div style={{ fontSize: 13, color: "#666" }}>{state.error}</div>
          </div>
        )}

        {state.phase === "ready" && state.doc && (
          <div style={{ background: "#fff", borderRadius: 12, padding: 24, textAlign: "center", boxShadow: "0 1px 3px rgba(0,0,0,0.08)" }}>
            <FileText size={28} color="#1B5E43" style={{ marginBottom: 10 }} />
            <div style={{ fontWeight: 800, fontSize: 15, marginBottom: 2 }}>
              {DOC_TYPE_LABEL[state.doc.doc_type] || state.doc.title}
            </div>
            {state.doc.document_date && (
              <div style={{ fontSize: 12.5, color: "#999", marginBottom: 18 }}>{fmtDate(state.doc.document_date)}</div>
            )}
            <a
              href={state.doc.file_url} target="_blank" rel="noopener noreferrer"
              style={{
                display: "inline-flex", alignItems: "center", gap: 6, background: "#1B5E43", color: "#fff",
                borderRadius: 8, padding: "11px 24px", fontSize: 14, fontWeight: 700, textDecoration: "none",
              }}
            >
              <ExternalLink size={15} /> Open document
            </a>
          </div>
        )}
      </div>
    </div>
  );
}
