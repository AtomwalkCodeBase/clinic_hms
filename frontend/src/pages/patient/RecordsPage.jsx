/**
 * pages/patient/RecordsPage.jsx
 * -------------------------------
 * Full visit history across all hospitals — timeline of consults with
 * vitals, diagnoses, and outcomes.
 */
import { useSearchParams } from "react-router-dom";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { usePaginatedList } from "../../hooks/usePaginatedList";
import API_ENDPOINTS from "../../config/api.config";

const BADGE = {
  scheduled: "badge--primary", waiting: "badge--warning", vitals_done: "badge--success",
  in_progress: "badge--info", done: "badge--success", cancelled: "badge--error",
};

export default function PatientRecordsPage() {
  const [searchParams] = useSearchParams();
  const patientAwpid = searchParams.get("patient_awpid") || "";
  const patientName  = searchParams.get("patient_name") || "";

  const { items: records, isLoading, isLoadingMore, hasMore, loadMore } =
    usePaginatedList(API_ENDPOINTS.PORTAL.MY_RECORDS, {
      pageSize: 20,
      params: patientAwpid ? { patient_awpid: patientAwpid } : {},
    });

  return (
    <AppShell>
      <PageShell title={patientName ? `${patientName}'s Health Records` : "My Health Records"}>
        {isLoading ? (
          <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>
            Loading your history…
          </div>
        ) : records.length === 0 ? (
          <div className="card" style={{ padding: 44, textAlign: "center" }}>
            <div style={{ fontFamily: "var(--font-display)", fontSize: 18, fontWeight: 600, marginBottom: 6 }}>
              No visits yet
            </div>
            <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
              Your consultation history will build up here after each hospital visit.
            </div>
          </div>
        ) : (
          <div style={{ display: "grid", gap: 14 }}>
            {records.map((r, i) => (
              <div key={i} className="card" style={{ padding: "16px 20px" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
                  <div>
                    <span style={{ fontFamily: "var(--font-display)", fontWeight: 600, fontSize: 15 }}>{r.hospital}</span>
                    <span style={{ fontSize: 12, color: "var(--color-text-muted)", marginLeft: 10 }}>
                      Dr. {r.doctor} · {r.date}{r.time ? ` · ${r.time}` : ""}
                    </span>
                  </div>
                  <span className={`badge ${BADGE[r.status] || "badge--neutral"}`}>{r.status?.replace("_", " ")}</span>
                </div>

                {r.chief_complaint && (
                  <div style={{ fontSize: 13, fontStyle: "italic", color: "var(--color-text-secondary)", marginBottom: 8 }}>
                    "{r.chief_complaint}"
                  </div>
                )}

                {r.vitals && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
                    {[
                      r.vitals.bp && `BP ${r.vitals.bp}`,
                      r.vitals.pulse && `Pulse ${r.vitals.pulse}`,
                      r.vitals.spo2 && `SpO₂ ${r.vitals.spo2}%`,
                      r.vitals.temperature && `Temp ${r.vitals.temperature}°F`,
                      r.vitals.weight_kg && `${r.vitals.weight_kg} kg`,
                    ].filter(Boolean).map(v => (
                      <span key={v} style={{
                        fontSize: 11, fontWeight: 700, padding: "3px 10px", borderRadius: 12,
                        background: "var(--color-info-light)", color: "var(--color-info)",
                      }}>{v}</span>
                    ))}
                  </div>
                )}

                {(r.diagnoses || []).length > 0 && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {r.diagnoses.map((d, di) => (
                      <span key={di} className="badge badge--primary">{d.code} — {d.description}</span>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {hasMore && (
              <button
                onClick={loadMore}
                disabled={isLoadingMore}
                className="btn-outline"
                style={{ justifySelf: "center", padding: "9px 24px", fontSize: 13 }}>
                {isLoadingMore ? "Loading…" : "Load more"}
              </button>
            )}
          </div>
        )}
      </PageShell>
    </AppShell>
  );
}
