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
import { usePatientContext } from "../../context/PatientContext";

const FREQ = { od: "Once daily", bd: "Twice daily", td: "3× daily", qid: "4× daily", sos: "As needed", stat: "Immediately", nocte: "At night", mane: "Morning" };

export default function PatientPrescriptionsPage() {
  const { selectedPatient } = usePatientContext();
  const patientAwpid = selectedPatient.awpid || "";

  const { items: allRecords, isLoading, isLoadingMore, hasMore, loadMore } =
    usePaginatedList(API_ENDPOINTS.PORTAL.MY_RECORDS, {
      pageSize: 20,
      params: patientAwpid ? { patient_awpid: patientAwpid } : {},
    });
  const records = allRecords.filter(
    r => r.prescription.length > 0 || r.investigations || r.advice || (r.diagnoses || []).length > 0
  );

  return (
    <AppShell>
      <PageShell title={selectedPatient.isSelf ? "My Prescriptions & Orders" : `${selectedPatient.name}'s Prescriptions & Orders`}>
        {isLoading ? (
          <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>
            Loading your records…
          </div>
        ) : records.length === 0 ? (
          /* Empty state with gradient RX icon ring */
          <div className="card" style={{ padding: 56, textAlign: "center" }}>
            <div style={{
              width: 72, height: 72, borderRadius: "50%", margin: "0 auto 18px",
              background: "linear-gradient(135deg, #E9F1EC 0%, #D4E8DC 100%)",
              border: "3px solid rgba(27,94,67,0.25)",
              display: "flex", alignItems: "center", justifyContent: "center",
              boxShadow: "0 4px 16px rgba(27,94,67,0.12)",
            }}>
              <span style={{ fontFamily: "var(--font-display)", fontSize: 28, fontWeight: 800, color: "#1B5E43" }}>Rx</span>
            </div>
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
                {/* Visit header — dark gradient strip */}
                <div style={{
                  background: "linear-gradient(135deg, #1B5E43 0%, #123828 100%)",
                  padding: "13px 20px",
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  position: "relative", overflow: "hidden",
                }}>
                  {/* Subtle gold glow */}
                  <div style={{
                    position: "absolute", width: 180, height: 180, borderRadius: "50%",
                    background: "radial-gradient(circle, rgba(201,162,75,0.14) 0%, transparent 70%)",
                    top: -80, right: -40, pointerEvents: "none",
                  }} />
                  <div style={{ position: "relative" }}>
                    <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 15, color: "#fff" }}>
                      {r.hospital}
                    </div>
                    <div style={{ fontSize: 12, color: "#8FA89A", marginTop: 2 }}>
                      Dr. {r.doctor} · {r.date}{r.time ? ` · ${r.time}` : ""}
                    </div>
                  </div>
                  <span className={`badge ${r.signed ? "badge--success" : "badge--warning"}`} style={{ position: "relative", flexShrink: 0 }}>
                    {r.signed ? "Completed" : "In progress"}
                  </span>
                </div>

                <div style={{ padding: "16px 20px", display: "grid", gap: 14, background: "#fff" }}>
                  {/* Diagnoses */}
                  {(r.diagnoses || []).length > 0 && (
                    <div>
                      <div className="stat-label" style={{ marginBottom: 6 }}>Diagnosis</div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                        {r.diagnoses.map((d, i) => (
                          <span key={i} style={{
                            display: "inline-flex", alignItems: "center", padding: "4px 12px",
                            borderRadius: 20, fontSize: 12, fontWeight: 600,
                            background: "var(--color-primary-light)", color: "var(--color-primary)",
                            borderLeft: "3px solid var(--color-primary)",
                          }}>
                            {d.code} — {d.description}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Prescription table */}
                  {r.prescription.length > 0 && (
                    <div>
                      <div className="stat-label" style={{ marginBottom: 6 }}>Prescription</div>
                      <table className="data-table">
                        <thead>
                          <tr><th>Medicine</th><th>Dose</th><th>How often</th><th>Days</th><th>Instructions</th></tr>
                        </thead>
                        <tbody>
                          {r.prescription.map((m, i) => (
                            <tr key={i} style={{ background: i % 2 === 0 ? "#fff" : "#FAFAF7" }}>
                              <td style={{ fontWeight: 700, color: "var(--color-primary)" }}>{m.drug_name}</td>
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

                  {/* Tests to do — amber gradient box */}
                  {r.investigations && (
                    <div style={{
                      background: "linear-gradient(135deg, #FFFDF5 0%, #FEF9EC 100%)",
                      borderLeft: "4px solid var(--color-warning)",
                      borderRadius: "0 10px 10px 0",
                      padding: "12px 16px",
                      boxShadow: "inset 2px 0 0 rgba(176,124,36,0.12)",
                    }}>
                      <div style={{ fontWeight: 700, fontSize: 13, color: "var(--color-warning)", marginBottom: 4, display: "flex", alignItems: "center", gap: 6 }}>
                        <FlaskConical size={15} style={{ flexShrink: 0 }} />
                        Tests to be done — please visit the laboratory
                      </div>
                      <div style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>{r.investigations}</div>
                    </div>
                  )}

                  {/* Advice + follow-up — green gradient box */}
                  {(r.advice || r.follow_up_in_days) && (
                    <div style={{
                      background: "linear-gradient(135deg, #E9F1EC 0%, #E0EEE5 100%)",
                      borderLeft: "4px solid var(--color-success)",
                      borderRadius: "0 10px 10px 0",
                      padding: "12px 16px",
                      boxShadow: "inset 2px 0 0 rgba(27,94,67,0.12)",
                    }}>
                      {r.advice && (
                        <div style={{ fontSize: 13, marginBottom: r.follow_up_in_days ? 6 : 0, color: "var(--color-text)" }}>
                          <strong style={{ color: "var(--color-success)" }}>Doctor's advice:</strong> {r.advice}
                        </div>
                      )}
                      {r.follow_up_in_days && (
                        <div style={{ fontSize: 13, color: "var(--color-text)" }}>
                          <strong style={{ color: "var(--color-success)" }}>Follow-up:</strong> in {r.follow_up_in_days} day{r.follow_up_in_days > 1 ? "s" : ""}
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
