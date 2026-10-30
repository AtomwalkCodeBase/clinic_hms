/** My Health Journey: tabs for insights timeline, vaccine record, visits, medicines and growth, for the account owner or a linked family member. */
import { useState, useEffect, useMemo } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Syringe, Activity, Building2, TrendingUp, Baby, Pill } from "lucide-react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { usePaginatedList } from "../../hooks/usePaginatedList";
import { useApi }    from "../../hooks/useApi";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import ROUTES from "../../config/routes.config";
import { usePatientContext } from "../../context/PatientContext";
import HealthSummaryCard from "./components/HealthSummaryCard";
import HealthJourney from "../../components/healthJourney/HealthJourney";
import { openDocumentWith } from "../../components/healthJourney/openDocument";
import { PORTAL_APPOINTMENT_BADGE as BADGE } from "../../constants/badges";
// Tab definitions — id maps to the rendered panel below.
const ALL_TABS = [
  { id: "health-timeline", label: "Insights Timeline", icon: Activity,  pediatricOnly: false },
  { id: "vaccine-record",  label: "Vaccine Record",   icon: Syringe,   pediatricOnly: true },
  { id: "visits",          label: "Visits",           icon: Building2, pediatricOnly: false },
  { id: "medicines",       label: "Medicines",        icon: Pill,      pediatricOnly: false },
  { id: "growth",          label: "Growth",           icon: TrendingUp, pediatricOnly: false },
];

function TabBar({ active, onChange, isAdult }) {
  const tabs = ALL_TABS.filter(t => !(isAdult && t.pediatricOnly));
  return (
    <div style={{
      background: "var(--color-surface)",
      border: "1px solid var(--color-border)",
      borderRadius: 14,
      padding: "6px 8px",
      display: "flex", gap: 4,
      marginBottom: 20,
      overflowX: "auto",
    }}>
      {tabs.map(tab => {
        const isActive = tab.id === active;
        const Icon = tab.icon;
        return (
          <button
            key={tab.id}
            onClick={() => onChange(tab.id)}
            style={{
              padding: "8px 18px", fontSize: 13, fontWeight: isActive ? 700 : 500,
              cursor: "pointer", border: "none", borderRadius: 10,
              whiteSpace: "nowrap", transition: "all 0.15s ease",
              display: "inline-flex", alignItems: "center", gap: 7,
              background: isActive
                ? "linear-gradient(135deg, var(--color-hero) 0%, var(--color-hero-2) 100%)"
                : "transparent",
              color: isActive ? "var(--color-hero-text)" : "var(--color-text-muted)",
            }}
          >
            {Icon && <Icon size={15} />}
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

// Sir's health-journey views (insights timeline, growth, immunisation record) for the patient being viewed, one section per tab.
function InsightsPanel({ awpid, name, section }) {
  const navigate = useNavigate();
  // Carries the vaccine to the booking form, which fills the reason from it.
  const bookVaccine = (r) => {
    try { sessionStorage.setItem("bookingReason", `Vaccination: ${r.vaccine} dose ${r.dose}`); } catch { /* the form is just left empty */ }
    navigate(ROUTES.PATIENT.HOSPITALS);
  };
  const children = useMemo(() => [{ id: awpid, name: name || "Your" }], [awpid, name]);
  const openDocument = useMemo(
    () => openDocumentWith(API_ENDPOINTS.PORTAL.DOCUMENT, { patient_awpid: awpid }),
    [awpid],
  );
  if (!awpid) return null;
  return (
    <HealthJourney key={`${awpid}-${section}`} http={apiClient} children={children} section={section} onOpenDocument={openDocument}
      onBookVaccine={bookVaccine}
      emptyAction={{ label: "Upload a report", onClick: () => navigate(ROUTES.PATIENT.MY_REPORTS) }} />
  );
}

export default function PatientRecordsPage() {
  const [searchParams] = useSearchParams();
  const { selectedPatient, selectPatient, familyMembers } = usePatientContext();
  const [activeTab, setActiveTab] = useState("health-timeline");

  useEffect(() => {
    const qAwpid = searchParams.get("patient_awpid") || "";
    const qName  = searchParams.get("patient_name") || "";
    if (qAwpid) selectPatient(qAwpid, qName);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const patientAwpid = selectedPatient.awpid || "";
  const patientName  = selectedPatient.isSelf ? "" : selectedPatient.name;
  const params = patientAwpid ? { patient_awpid: patientAwpid } : {};

  const { data: summary, isLoading: summaryLoading, error: summaryError } =
    useApi(API_ENDPOINTS.PORTAL.HEALTH_SUMMARY, { params });
  const { data: growth } =
    useApi(API_ENDPOINTS.PORTAL.GROWTH, { params });

  const ageYears = growth?.age_years ?? null;
  const isAdult  = ageYears !== null && ageYears >= 18;

  const { data: profile } = useApi(API_ENDPOINTS.PORTAL.PROFILE, { skip: !selectedPatient.isSelf });

  const familyMember = !selectedPatient.isSelf
    ? (familyMembers || []).find(m => m.awpid === patientAwpid)
    : null;
  const heroGender = selectedPatient.isSelf ? (profile?.gender || "") : (familyMember?.gender || "");
  const heroPhoto  = selectedPatient.isSelf ? (profile?.photo || "") : "";

  const { items: records, isLoading: recordsLoading, isLoadingMore, hasMore, loadMore } =
    usePaginatedList(API_ENDPOINTS.PORTAL.MY_RECORDS, { pageSize: 20, params });
  const { items: prescriptions, isLoading: medicinesLoading } =
    usePaginatedList(API_ENDPOINTS.PORTAL.PRESCRIPTIONS, { pageSize: 20, params });

  return (
    <AppShell>
      <PageShell title={patientName ? `${patientName}'s Health Journey` : "My Health Journey"}>
        {/* Patient profile header — always visible across all tabs */}
        <HealthSummaryCard
          displayName={patientName || summary?.patient_name}
          photo={heroPhoto}
          gender={heroGender}
          summary={summary}
          summaryLoading={summaryLoading}
          summaryError={summaryError}
          growth={growth}
        />

        {/* Tab switcher */}
        <TabBar active={activeTab} onChange={setActiveTab} isAdult={isAdult} />

        {/* ── Health Timeline tab ────────────────────────────────── */}
        {activeTab === "health-timeline" && (
          <InsightsPanel awpid={patientAwpid || profile?.awpid || ""} name={patientName} section="timeline" />
        )}

        {/* ── Medicines tab: what each hospital prescribed, newest first ─────────── */}
        {activeTab === "medicines" && (
          medicinesLoading ? (
            <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading medicines…</div>
          ) : prescriptions.length === 0 ? (
            <div className="card" style={{ padding: 44, textAlign: "center" }}>
              <div style={{ fontFamily: "var(--font-display)", fontSize: 18, fontWeight: 600, marginBottom: 6 }}>No medicines yet</div>
              <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>Medicines a doctor prescribes will appear here after each visit.</div>
            </div>
          ) : (
            <div style={{ display: "grid", gap: 12 }}>
              {prescriptions.map((rx) => (
                <div key={rx.opd_prescription_id} style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: 16, overflow: "hidden" }}>
                  <div style={{ padding: "12px 18px", borderBottom: "1px solid var(--color-border)" }}>
                    <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 15 }}>{rx.hospital}</div>
                    <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 2 }}>
                      Dr. {rx.doctor_name} · {new Date(rx.created_at).toLocaleDateString()}{rx.rx_number ? ` · ${rx.rx_number}` : ""}
                    </div>
                  </div>
                  <div style={{ padding: "8px 18px 14px", overflowX: "auto" }}>
                    <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
                      <thead>
                        <tr style={{ textAlign: "left", color: "var(--color-text-muted)", fontSize: 11 }}>
                          <th style={{ padding: "6px 8px 6px 0" }}>Medicine</th><th>Dose</th><th>Frequency</th><th>Quantity</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(rx.items || []).map((it, i) => (
                          <tr key={i} style={{ borderTop: "1px solid var(--color-border)" }}>
                            <td style={{ padding: "7px 8px 7px 0", fontWeight: 600 }}>{it.drug_name}</td>
                            <td>{it.dosage || "–"}</td><td>{it.frequency || "–"}</td><td>{it.quantity ?? "–"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))}
            </div>
          )
        )}

        {/* ── Visits tab ────────────────────────────────────────── */}
        {activeTab === "visits" && (
          recordsLoading ? (
            <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>
              Loading visits…
            </div>
          ) : records.length === 0 ? (
            <div className="card" style={{ padding: 44, textAlign: "center" }}>
              <div style={{ fontFamily: "var(--font-display)", fontSize: 18, fontWeight: 600, marginBottom: 6 }}>
                No visits yet
              </div>
              <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
                Your consultation history will appear here after each hospital visit.
              </div>
            </div>
          ) : (
            <div style={{ display: "grid", gap: 12 }}>
              {records.map((r, i) => (
                <div key={i} style={{
                  background: "var(--color-surface)",
                  border: "1px solid var(--color-border)",
                  borderRadius: 16,
                  overflow: "hidden",
                }}>
                  {/* Card header strip */}
                  <div style={{
                    background: "linear-gradient(90deg, #F5F1E9 0%, var(--color-surface) 100%)",
                    borderBottom: "1px solid var(--color-border)",
                    padding: "12px 18px",
                    display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12,
                  }}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 15, color: "var(--color-text)" }}>
                        {r.hospital}
                      </div>
                      <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 2 }}>
                        Dr. {r.doctor} · {r.date}{r.time ? ` · ${r.time}` : ""}
                      </div>
                    </div>
                    <span className={`badge ${BADGE[r.status] || "badge--neutral"}`} style={{ flexShrink: 0 }}>
                      {r.status?.replace("_", " ")}
                    </span>
                  </div>

                  {/* Card body */}
                  <div style={{ padding: "12px 18px", display: "grid", gap: 8 }}>
                    {r.chief_complaint && (
                      <div style={{
                        fontSize: 13, fontStyle: "italic", color: "var(--color-text-secondary)",
                        borderLeft: "3px solid var(--color-accent)", paddingLeft: 10,
                      }}>
                        "{r.chief_complaint}"
                      </div>
                    )}

                    {r.vitals && (
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                        {[
                          r.vitals.bp          && `BP ${r.vitals.bp}`,
                          r.vitals.pulse       && `Pulse ${r.vitals.pulse}`,
                          r.vitals.spo2        && `SpO₂ ${r.vitals.spo2}%`,
                          r.vitals.temperature && `Temp ${r.vitals.temperature}°F`,
                          r.vitals.weight_kg   && `${r.vitals.weight_kg} kg`,
                        ].filter(Boolean).map(v => (
                          <span key={v} style={{
                            fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 20,
                            background: "var(--color-info-light)", color: "var(--color-info)",
                            border: "1px solid #AECAD8",
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
                </div>
              ))}
              {hasMore && (
                <button
                  onClick={loadMore}
                  disabled={isLoadingMore}
                  className="btn-outline"
                  style={{ justifySelf: "center", padding: "9px 24px", fontSize: 13 }}
                >
                  {isLoadingMore ? "Loading…" : "Load more"}
                </button>
              )}
            </div>
          )
        )}

        {/* ── Growth tab ────────────────────────────────────────── */}
        {/* Same upgraded chart as the Vaccinations tab (gridlines, hover */}
        {activeTab === "growth" && <InsightsPanel awpid={patientAwpid || profile?.awpid || ""} name={patientName} section="growth" />}
        {activeTab === "vaccine-record" && !isAdult && <InsightsPanel awpid={patientAwpid || profile?.awpid || ""} name={patientName} section="vaccines" />}
      </PageShell>
    </AppShell>
  );
}
