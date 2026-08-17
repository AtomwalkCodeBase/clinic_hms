/**
 * pages/patient/PrescriptionsPage.jsx
 * -------------------------------------
 * Two things on this page:
 *  1. "Your prescriptions" — one card per Rx a doctor has written, with the
 *     same buy-in-house-or-elsewhere choice flow LabReportsPage already has
 *     for lab tests (see PortalPrescriptionListView/ChoiceView). Choosing
 *     in-house surfaces the rx_number — the token to quote at the pharmacy
 *     counter, same idea as the lab request token.
 *  2. The full consult record, unchanged — diagnosis/advice/investigations
 *     context that the choice cards above don't carry.
 */
import { useState } from "react";
import { FlaskConical } from "lucide-react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { usePaginatedList } from "../../hooks/usePaginatedList";
import { useToast } from "../../hooks/useToast";
import apiClient from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import { usePatientContext } from "../../context/PatientContext";

const FREQ = { od: "Once daily", bd: "Twice daily", td: "3× daily", qid: "4× daily", sos: "As needed", stat: "Immediately", nocte: "At night", mane: "Morning" };

const PAY_PREF_LABEL = { pay_at_pharmacy: "Pay at the pharmacy", pay_online: "Pay online (coming soon)" };

const RX_STATUS_BADGE = {
  active:    { label: "Active",    bg: "var(--color-border)", color: "var(--color-text-muted)" },
  dispensed: { label: "Dispensed", bg: "#DCFCE7", color: "#166534" },
  expired:   { label: "Expired",   bg: "#FEE2E2", color: "#991B1B" },
};

// One prescription, self-contained: choice -> (rx_number/pay | nothing more
// to do) — mirrors LabReportsPage's LabOrderCard shape and interaction.
function PrescriptionOrderCard({ rx, onChanged }) {
  const { toastSuccess, toastApiError } = useToast();
  const [saving, setSaving] = useState(false);
  const [editingPayment, setEditingPayment] = useState(!rx.payment_preference);

  async function chooseAndSave(choice, paymentPreference) {
    setSaving(true);
    try {
      await apiClient.post(API_ENDPOINTS.PORTAL.PRESCRIPTION_CHOICE, {
        tenant_db: rx.tenant_db, prescription_id: rx.id,
        patient_choice: choice, payment_preference: paymentPreference || "",
      });
      toastSuccess(choice === "in_house" ? "Got it — quote your Rx number at the pharmacy counter." : "Okay — no action needed here.");
      setEditingPayment(false);
      onChanged?.();
    } catch (err) {
      toastApiError(err, "Could not save your choice.");
    } finally {
      setSaving(false);
    }
  }

  const canEditPayment = rx.status === "active";
  const statusBadge = RX_STATUS_BADGE[rx.status] || RX_STATUS_BADGE.active;

  return (
    <div className="card" style={{ padding: 0, overflow: "hidden" }}>
      <div style={{
        background: "linear-gradient(135deg, var(--color-hero) 0%, var(--color-hero-2) 100%)",
        padding: "12px 20px",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        position: "relative", overflow: "hidden",
      }}>
        <div style={{ position: "relative" }}>
          <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 15, color: "#fff" }}>
            {rx.doctor_name ? `Dr. ${rx.doctor_name}` : "Prescription"}
          </div>
          <div style={{ fontSize: 11, color: "var(--color-hero-muted)", marginTop: 2 }}>
            {rx.hospital}{rx.created_at ? ` · ${new Date(rx.created_at).toLocaleDateString("en-IN")}` : ""}
          </div>
        </div>
        <span style={{ padding: "3px 10px", borderRadius: 12, fontSize: 11, fontWeight: 700, background: statusBadge.bg, color: statusBadge.color, position: "relative", flexShrink: 0 }}>
          {statusBadge.label}
        </span>
      </div>

      <div style={{ padding: "14px 20px" }}>
        {/* Items */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 12 }}>
          {rx.items.map((it, i) => (
            <span key={i} style={{
              display: "inline-flex", alignItems: "center", padding: "4px 12px",
              borderRadius: 20, fontSize: 12, fontWeight: 600,
              background: "var(--color-primary-light)", color: "var(--color-primary)",
              borderLeft: "3px solid var(--color-primary)",
            }}>
              {it.drug_name} {it.dosage} · {FREQ[it.frequency] || it.frequency}
            </span>
          ))}
        </div>

        {rx.patient_choice === "pending" ? (
          <div style={{ display: "flex", gap: 10 }}>
            <button className="btn-primary" disabled={saving} style={{ flex: 1 }}
              onClick={() => chooseAndSave("in_house", "pay_at_pharmacy")}>
              {rx.hospital ? `Buy at ${rx.hospital}` : "Buy at this pharmacy"}
            </button>
            <button className="btn-outline" disabled={saving} style={{ flex: 1 }}
              onClick={() => chooseAndSave("outside", "")}>
              I'll get it elsewhere
            </button>
          </div>
        ) : rx.patient_choice === "in_house" ? (
          <div style={{
            background: "linear-gradient(135deg, #FFFDF5 0%, #FEF9EC 100%)",
            borderLeft: "4px solid var(--color-warning)",
            borderRadius: "0 10px 10px 0",
            padding: "12px 16px",
          }}>
            <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 4 }}>
              Quote this number at the pharmacy counter:
            </div>
            <div style={{ fontFamily: "var(--font-display)", fontWeight: 800, fontSize: 20, color: "var(--color-warning)", marginBottom: 10 }}>
              {rx.rx_number || "—"}
            </div>

            {canEditPayment && editingPayment ? (
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <span style={{ fontSize: 12, fontWeight: 600 }}>Payment:</span>
                <button
                  className={rx.payment_preference === "pay_at_pharmacy" ? "btn-primary" : "btn-outline"}
                  style={{ fontSize: 12, padding: "5px 12px" }}
                  disabled={saving}
                  onClick={() => chooseAndSave("in_house", "pay_at_pharmacy")}
                >
                  Pay at the pharmacy
                </button>
                <button
                  className={rx.payment_preference === "pay_online" ? "btn-primary" : "btn-outline"}
                  style={{ fontSize: 12, padding: "5px 12px" }}
                  disabled={saving}
                  title="Online payment is coming soon — this just lets the pharmacy know your preference."
                  onClick={() => chooseAndSave("in_house", "pay_online")}
                >
                  Pay online (coming soon)
                </button>
              </div>
            ) : (
              <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
                <span style={{ fontWeight: 600 }}>Payment:</span>
                <span>{rx.payment_preference ? PAY_PREF_LABEL[rx.payment_preference] : "Not set"}</span>
                {canEditPayment && (
                  <button type="button" onClick={() => setEditingPayment(true)}
                    style={{ background: "none", border: "none", color: "var(--color-primary)", fontSize: 11, cursor: "pointer", padding: 0, marginLeft: "auto" }}>
                    Change
                  </button>
                )}
              </div>
            )}
          </div>
        ) : (
          <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
            You chose to get this elsewhere.
          </div>
        )}
      </div>
    </div>
  );
}

export default function PatientPrescriptionsPage() {
  const { selectedPatient } = usePatientContext();
  const patientAwpid = selectedPatient.awpid || "";

  const { items: rxOrders, isLoading: rxLoading, refetch: refetchRxOrders } =
    usePaginatedList(API_ENDPOINTS.PORTAL.PRESCRIPTIONS, {
      pageSize: 20,
      params: patientAwpid ? { patient_awpid: patientAwpid } : {},
    });

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
        {/* Buy in-house or elsewhere — one card per Rx, same pattern as lab tests */}
        {!rxLoading && rxOrders.length > 0 && (
          <div style={{ display: "grid", gap: 14, marginBottom: 24 }}>
            {rxOrders.map(rx => (
              <PrescriptionOrderCard key={`${rx.tenant_db}-${rx.id}`} rx={rx} onChanged={refetchRxOrders} />
            ))}
          </div>
        )}

        {isLoading ? (
          <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>
            Loading your records…
          </div>
        ) : records.length === 0 ? (
          /* Empty state with gradient RX icon ring */
          <div className="card" style={{ padding: 56, textAlign: "center" }}>
            <div style={{
              width: 72, height: 72, borderRadius: "50%", margin: "0 auto 18px",
              background: "linear-gradient(135deg, var(--color-primary-light) 0%, color-mix(in srgb, var(--color-primary-light) 55%, var(--color-primary) 45%) 100%)",
              border: "3px solid color-mix(in srgb, var(--color-primary) 25%, transparent)",
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              <span style={{ fontFamily: "var(--font-display)", fontSize: 28, fontWeight: 800, color: "var(--color-primary)" }}>Rx</span>
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
                  background: "linear-gradient(135deg, var(--color-hero) 0%, var(--color-hero-2) 100%)",
                  padding: "13px 20px",
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  position: "relative", overflow: "hidden",
                }}>
                  <div style={{ position: "relative" }}>
                    <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 15, color: "#fff" }}>
                      {r.hospital}
                    </div>
                    <div style={{ fontSize: 12, color: "var(--color-hero-muted)", marginTop: 2 }}>
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
                      background: "linear-gradient(135deg, var(--color-primary-light) 0%, color-mix(in srgb, var(--color-primary-light) 55%, var(--color-primary) 45%) 100%)",
                      borderLeft: "4px solid var(--color-success)",
                      borderRadius: "0 10px 10px 0",
                      padding: "12px 16px",
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
