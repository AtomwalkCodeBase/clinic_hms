/**
 * pages/patient/components/HealthTimeline.jsx
 * ---------------------------------------------
 * Unified chronological health feed for the Records page — merges visits,
 * vaccinations, growth checks, lab results, and documents (PORTAL.TIMELINE)
 * into one reverse-chronological list, sitting below the Growth/Vaccinations
 * section already on this page.
 *
 * "View" actions are only wired for entry types that already have a working
 * viewer elsewhere in the portal: vaccination certificates
 * (PortalVaccinationFileView, same as ViewCertificateButton in
 * RecordsPage.jsx) and delivered in-house lab reports
 * (PortalLabReportFileView, same as ViewInHouseReportButton in
 * LabReportsPage.jsx). Documents/visits/growth points have no dedicated
 * single-item viewer on the portal yet, so those just render as text.
 */
import { useState } from "react";
import { Stethoscope, Syringe, TrendingUp, FlaskConical, FileText, CalendarClock } from "lucide-react";
import useApi from "../../../hooks/useApi";
import apiClient from "../../../services/api.client";
import API_ENDPOINTS from "../../../config/api.config";
import { useToast } from "../../../hooks/useToast";
import { openDataUrlInNewTab } from "../../../utils/fileViewer";

const ICON_MAP = {
  stethoscope: Stethoscope,
  syringe: Syringe,
  "trending-up": TrendingUp,
  flask: FlaskConical,
  file: FileText,
};

const ICON_STYLE = {
  visit:       { bg: "var(--color-primary-light)", color: "var(--color-primary)" },
  vaccination: { bg: "var(--color-success-light)", color: "var(--color-success)" },
  growth:      { bg: "var(--color-info-light)",    color: "var(--color-info)" },
  lab:         { bg: "var(--color-warning-light)", color: "var(--color-warning)" },
  document:    { bg: "var(--color-border)",         color: "var(--color-text-muted)" },
};

function formatEntryDate(dateStr) {
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return dateStr;
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

// Fetches the actual file on demand and opens it in a new tab — same
// on-demand pattern as ViewCertificateButton/ViewInHouseReportButton
// elsewhere on the portal, kept local here since the endpoint differs by
// entry type.
function ViewFileButton({ label, fetchUrl }) {
  const { toastApiError } = useToast();
  const [loading, setLoading] = useState(false);

  async function open() {
    const win = window.open("", "_blank");
    setLoading(true);
    try {
      const res = await apiClient.get(fetchUrl);
      const data = res.data?.data || res.data;
      if (data?.file_data) {
        openDataUrlInNewTab(win, data.file_data);
      } else if (win) {
        win.close();
      }
    } catch (err) {
      if (win) win.close();
      toastApiError(err, "Could not load that file.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <button className="btn-outline" disabled={loading} onClick={open} style={{ padding: "3px 10px", fontSize: 11, whiteSpace: "nowrap" }}>
      {loading ? "Loading…" : label}
    </button>
  );
}

function entryAction(entry) {
  if (entry.type === "vaccination" && entry.detail?.has_certificate && entry.detail?.record_id) {
    return <ViewFileButton label="View Certificate" fetchUrl={API_ENDPOINTS.PORTAL.VACCINATION_FILE(entry.detail.record_id)} />;
  }
  if (entry.type === "lab" && entry.detail?.has_file && entry.detail?.tenant_db && entry.detail?.request_id) {
    return <ViewFileButton label="View Report" fetchUrl={API_ENDPOINTS.PORTAL.LAB_REPORT_FILE(entry.detail.tenant_db, entry.detail.request_id)} />;
  }
  return null;
}

export default function HealthTimeline({ patientAwpid }) {
  const params = patientAwpid ? { patient_awpid: patientAwpid } : {};
  const { data, isLoading, error } = useApi(API_ENDPOINTS.PORTAL.TIMELINE, { params });
  const entries = data?.results || [];

  return (
    <div className="card" style={{ padding: "16px 20px", marginBottom: 20, borderRadius: 12 }}>
      <div style={{ fontFamily: "var(--font-display)", fontWeight: 600, fontSize: 15, marginBottom: 12 }}>
        Health Timeline
      </div>

      {isLoading ? (
        <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>Loading…</div>
      ) : error && !data ? (
        <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>Couldn't load your timeline right now.</div>
      ) : entries.length === 0 ? (
        <div style={{ padding: "24px 8px", textAlign: "center" }}>
          <CalendarClock size={28} style={{ color: "var(--color-text-muted)", marginBottom: 8 }} />
          <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
            Nothing to show yet — visits, vaccinations, growth checks, lab results, and
            documents will all appear here as they happen.
          </div>
        </div>
      ) : (
        <div style={{ display: "grid", gap: 0 }}>
          {entries.map((entry, i) => {
            const Icon = ICON_MAP[entry.icon_hint] || FileText;
            const style = ICON_STYLE[entry.type] || ICON_STYLE.document;
            const isLast = i === entries.length - 1;
            return (
              <div key={i} style={{ display: "flex", gap: 12 }}>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", width: 32 }}>
                  <div style={{
                    width: 32, height: 32, borderRadius: "50%", flexShrink: 0,
                    display: "flex", alignItems: "center", justifyContent: "center",
                    background: style.bg, color: style.color,
                  }}>
                    <Icon size={16} />
                  </div>
                  {!isLast && <div style={{ flex: 1, width: 2, minHeight: 20, background: "var(--color-border)", margin: "2px 0" }} />}
                </div>
                <div style={{ paddingBottom: isLast ? 0 : 18, minWidth: 0, flex: 1 }}>
                  <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginBottom: 2 }}>
                    {formatEntryDate(entry.date)}
                  </div>
                  <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 13, fontWeight: 600 }}>{entry.title}</div>
                      {entry.subtitle && (
                        <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>{entry.subtitle}</div>
                      )}
                    </div>
                    {entryAction(entry)}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
