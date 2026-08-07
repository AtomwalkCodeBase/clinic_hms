/**
 * pages/patient/PrescriptionsPage.jsx
 * -------------------------------------
 * Every consult record for this patient across all hospitals:
 * prescriptions, tests to be done (investigations), advice, follow-up.
 */
import { FlaskConical } from "lucide-react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { usePaginatedList } from "../../hooks/usePaginatedList";
import API_ENDPOINTS from "../../config/api.config";

const FREQ = { od: "Once daily", bd: "Twice daily", td: "3× daily", qid: "4× daily", sos: "As needed", stat: "Immediately", nocte: "At night", mane: "Morning" };

export default function PatientPrescriptionsPage() {
  const { items: allRecords, isLoading, isLoadingMore, hasMore, loadMore } =
    usePaginatedList(API_ENDPOINTS.PORTAL.MY_RECORDS, { pageSize: 20 });
  const records = allRecords.filter(
    r => r.prescription.length > 0 || r.investigations || r.advice || (r.diagnoses || []).length > 0
  );

  return (
    <AppShell>
      <PageShell title="My Prescriptions & Orders">
        {isLoading ? (
          <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>
            Loading your records…
          </div>
        ) : records.length === 0 ? (
          <div className="card" style={{ padding: 44, textAlign: "center" }}>
            <div style={{ fontFamily: "var(--font-display)", fontSize: 18, fontWeight: 600, marginBottom: 6 }}>
              No prescriptions yet
            </div>
            <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
              After your consultation, everything the doctor prescribes will appear here.
            </div>
          </div>
        ) : (
          <div style={{ display: "grid", gap: 16 }}>
            {records.map((r, idx) => (
              <div key={idx} className="card" style={{ padding: 0, overflow: "hidden" }}>
                {/* Visit header */}
                <div style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  padding: "13px 20px", borderBottom: "1px solid var(--color-border)", background: "#FAFAF7",
                }}>
                  <div>
                    <span style={{ fontFamily: "var(--font-display)", fontWeight: 600, fontSize: 15 }}>{r.hospital}</span>
                    <span style={{ fontSize: 12, color: "var(--color-text-muted)", marginLeft: 10 }}>
                      Dr. {r.doctor} · {r.date}{r.time ? ` · ${r.time}` : ""}
                    </span>
                  </div>
                  <span className={`badge ${r.signed ? "badge--success" : "badge--warning"}`}>
                    {r.signed ? "Completed" : "In progress"}
                  </span>
                </div>

                <div style={{ padding: "16px 20px", display: "grid", gap: 14 }}>
                  {/* Diagnoses */}
                  {(r.diagnoses || []).length > 0 && (
                    <div>
                      <div className="stat-label" style={{ marginBottom: 6 }}>Diagnosis</div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                        {r.diagnoses.map((d, i) => (
                          <span key={i} className="badge badge--primary">{d.code} — {d.description}</span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Prescription */}
                  {r.prescription.length > 0 && (
                    <div>
                      <div className="stat-label" style={{ marginBottom: 6 }}>Prescription</div>
                      <table className="data-table">
                        <thead>
                          <tr><th>Medicine</th><th>Dose</th><th>How often</th><th>Days</th><th>Instructions</th></tr>
                        </thead>
                        <tbody>
                          {r.prescription.map((m, i) => (
                            <tr key={i}>
                              <td style={{ fontWeight: 600 }}>{m.drug_name}</td>
                              <td>{m.dosage}</td>
                              <td>{FREQ[m.frequency] || m.frequency}</td>
                              <td>{m.duration_days || "—"}</td>
                              <td style={{ fontSize: 12, color: "var(--color-text-muted)" }}>{m.instructions || "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {/* Tests to do */}
                  {r.investigations && (
                    <div style={{
                      background: "var(--color-warning-light)", border: "1px solid var(--color-warning)",
                      borderRadius: 10, padding: "12px 16px",
                    }}>
                      <div style={{ fontWeight: 700, fontSize: 13, color: "var(--color-warning)", marginBottom: 4, display: "flex", alignItems: "center", gap: 6 }}>
                        <FlaskConical size={14} style={{ flexShrink: 0 }} />
                        Tests to be done — please visit the laboratory
                      </div>
                      <div style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>{r.investigations}</div>
                    </div>
                  )}

                  {/* Advice + follow-up */}
                  {(r.advice || r.follow_up_in_days) && (
                    <div style={{
                      background: "var(--color-primary-light)", borderRadius: 10, padding: "12px 16px",
                    }}>
                      {r.advice && (
                        <div style={{ fontSize: 13, marginBottom: r.follow_up_in_days ? 6 : 0 }}>
                          <strong>Doctor's advice:</strong> {r.advice}
                        </div>
                      )}
                      {r.follow_up_in_days && (
                        <div style={{ fontSize: 13 }}>
                          <strong>Follow-up:</strong> in {r.follow_up_in_days} day{r.follow_up_in_days > 1 ? "s" : ""}
                        </div>
                      )}
                    </div>
                  )}
                </div>
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
