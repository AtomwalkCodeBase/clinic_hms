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
import { useState, useMemo } from "react";
import { FlaskConical, Search, Filter, X, Download } from "lucide-react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { usePaginatedList } from "../../hooks/usePaginatedList";
import { useToast } from "../../hooks/useToast";
import apiClient from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import { usePatientContext } from "../../context/PatientContext";
import { openDataUrlInNewTab } from "../../utils/fileViewer";

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
  const [downloading, setDownloading] = useState(false);
  const [openingHw, setOpeningHw] = useState(false);

  async function downloadPdf() {
    const win = window.open("", "_blank");
    setDownloading(true);
    try {
      const res = await apiClient.get(API_ENDPOINTS.PORTAL.PRESCRIPTION_RECEIPT(rx.tenant_db, rx.id));
      const data = res.data?.data || res.data;
      if (data?.file_data) {
        openDataUrlInNewTab(win, data.file_data);
      } else if (win) {
        win.close();
      }
    } catch (err) {
      toastApiError(err, "Could not generate the PDF.");
      if (win) win.close();
    } finally {
      setDownloading(false);
    }
  }

  async function openHandwritten() {
    const win = window.open("", "_blank");
    setOpeningHw(true);
    try {
      const res = await apiClient.get(API_ENDPOINTS.PORTAL.DOCUMENT(rx.handwritten_document_id));
      const data = res.data?.data || res.data;
      if (data?.file_data) openDataUrlInNewTab(win, data.file_data);
      else if (win) win.close();
    } catch (err) {
      toastApiError(err, "Could not open the handwritten prescription.");
      if (win) win.close();
    } finally {
      setOpeningHw(false);
    }
  }

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
        <div style={{ display: "flex", alignItems: "center", gap: 10, position: "relative", flexShrink: 0 }}>
          <span style={{ padding: "3px 10px", borderRadius: 12, fontSize: 11, fontWeight: 700, background: statusBadge.bg, color: statusBadge.color }}>
            {statusBadge.label}
          </span>
          {rx.handwritten_document_id && (
            <button
              onClick={openHandwritten}
              disabled={openingHw}
              title="Doctor's handwritten prescription"
              style={{
                display: "flex", alignItems: "center", gap: 5, background: "rgba(255,255,255,0.15)", border: "none",
                borderRadius: 8, cursor: "pointer", padding: "5px 9px", fontSize: 11, fontWeight: 700, color: "#fff",
              }}
            >
              <Download size={13} /> {openingHw ? "…" : "Handwritten"}
            </button>
          )}
          <button
            onClick={downloadPdf}
            disabled={downloading}
            title="Download PDF"
            style={{
              display: "flex", alignItems: "center", gap: 5, background: "rgba(255,255,255,0.15)", border: "none",
              borderRadius: 8, cursor: "pointer", padding: "5px 9px", fontSize: 11, fontWeight: 700, color: "#fff",
            }}
          >
            <Download size={13} /> {downloading ? "…" : "PDF"}
          </button>
        </div>
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

// One consult visit — diagnosis/prescription/investigations/advice, exactly
// as before, just extracted into its own component so it can hold its own
// "download PDF" button + loading state (the record card renders straight
// out of a .map(), so hooks need a component boundary to live in).
function ConsultRecordCard({ r }) {
  const { toastApiError } = useToast();
  const [downloading, setDownloading] = useState(false);

  async function downloadPdf() {
    const win = window.open("", "_blank");
    setDownloading(true);
    try {
      const res = await apiClient.get(API_ENDPOINTS.PORTAL.PRESCRIPTION_RECEIPT(r.tenant_db, r.prescription_id));
      const data = res.data?.data || res.data;
      if (data?.file_data) {
        openDataUrlInNewTab(win, data.file_data);
      } else if (win) {
        win.close();
      }
    } catch (err) {
      toastApiError(err, "Could not generate the PDF.");
      if (win) win.close();
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="card" style={{ padding: 0, overflow: "hidden" }}>
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
        <div style={{ display: "flex", alignItems: "center", gap: 10, position: "relative", flexShrink: 0 }}>
          <span className={`badge ${r.signed ? "badge--success" : "badge--warning"}`}>
            {r.signed ? "Completed" : "In progress"}
          </span>
          {/* Only shown once a doctor has actually written a prescription
              for this visit — nothing to download otherwise. */}
          {r.prescription_id && (
            <button
              onClick={downloadPdf}
              disabled={downloading}
              title="Download prescription PDF"
              style={{
                display: "flex", alignItems: "center", gap: 5, background: "rgba(255,255,255,0.15)", border: "none",
                borderRadius: 8, cursor: "pointer", padding: "5px 9px", fontSize: 11, fontWeight: 700, color: "#fff",
              }}
            >
              <Download size={13} /> {downloading ? "…" : "PDF"}
            </button>
          )}
        </div>
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
  );
}

export default function PatientPrescriptionsPage() {
  const { selectedPatient } = usePatientContext();
  const patientAwpid = selectedPatient.awpid || "";

  const { items: rxOrders, isLoading: rxLoading, refetch: refetchRxOrders } =
    usePaginatedList(API_ENDPOINTS.PORTAL.PRESCRIPTIONS, {
      pageSize: 20,
      params: patientAwpid ? { patient_awpid: patientAwpid } : {},
      pollMs: 30000,
    });

  const { items: allRecords, isLoading, isLoadingMore, hasMore, loadMore } =
    usePaginatedList(API_ENDPOINTS.PORTAL.MY_RECORDS, {
      pageSize: 20,
      params: patientAwpid ? { patient_awpid: patientAwpid } : {},
    });
  const withRx = allRecords.filter(
    r => r.prescription.length > 0 || r.investigations || r.advice || (r.diagnoses || []).length > 0
  );

  // ── Search + filter — over the loaded records (usePaginatedList is built
  // for exactly this: client-side filtering over an accumulating list; use
  // "Load more" to widen the pool if what you're looking for isn't loaded
  // yet). Search matches doctor, hospital, drug names, and diagnosis text —
  // filters narrow by date range and visit status. ──────────────────────
  const [search,      setSearch]      = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [dateFrom,    setDateFrom]    = useState("");
  const [dateTo,      setDateTo]      = useState("");
  const [statusFilter,setStatusFilter]= useState(""); // "" | "signed" | "in_progress"
  const [doctorFilter,setDoctorFilter]= useState("");
  const hasActiveFilters = !!(search || dateFrom || dateTo || statusFilter || doctorFilter);

  const doctorOptions = useMemo(
    () => [...new Set(withRx.map(r => r.doctor).filter(Boolean))].sort(),
    [withRx]
  );

  const records = useMemo(() => {
    const q = search.trim().toLowerCase();
    return withRx
      .filter(r => {
        if (dateFrom && r.date && r.date < dateFrom) return false;
        if (dateTo && r.date && r.date > dateTo) return false;
        if (statusFilter === "signed" && !r.signed) return false;
        if (statusFilter === "in_progress" && r.signed) return false;
        if (doctorFilter && r.doctor !== doctorFilter) return false;
        if (!q) return true;
        const haystack = [
          r.doctor, r.hospital,
          ...(r.prescription || []).map(m => m.drug_name),
          ...(r.diagnoses || []).map(d => `${d.code} ${d.description}`),
          r.investigations, r.advice,
        ].filter(Boolean).join(" ").toLowerCase();
        return haystack.includes(q);
      })
      // Most recent first — dates are ISO strings, so a plain string
      // comparison sorts correctly without parsing.
      .sort((a, b) => (b.date || "").localeCompare(a.date || ""));
  }, [withRx, search, dateFrom, dateTo, statusFilter, doctorFilter]);

  return (
    <AppShell>
      <PageShell title={selectedPatient.isSelf ? "My Prescriptions & Orders" : `${selectedPatient.name}'s Prescriptions & Orders`}>
        {/* Search + filter — which prescription was given when, by whom */}
        <div className="card" style={{ marginBottom: 18, padding: 16 }}>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
            <div style={{ position: "relative", flex: "2 1 240px" }}>
              <Search size={14} style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--color-text-muted)" }} />
              <input className="form-input" style={{ paddingLeft: 30 }}
                placeholder="Search medicine, doctor, hospital, diagnosis…"
                value={search} onChange={e => setSearch(e.target.value)} />
            </div>
            <button
              className={hasActiveFilters ? "btn-primary" : "btn-outline"}
              style={{ fontSize: 12, padding: "9px 14px", display: "flex", alignItems: "center", gap: 6 }}
              onClick={() => setShowFilters(v => !v)}>
              <Filter size={13} /> Filters{hasActiveFilters ? " •" : ""}
            </button>
          </div>
          {showFilters && (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10, marginTop: 12 }}>
              <div>
                <label className="stat-label" style={{ display: "block", marginBottom: 5 }}>From date</label>
                <input type="date" className="form-input" value={dateFrom} onChange={e => setDateFrom(e.target.value)} />
              </div>
              <div>
                <label className="stat-label" style={{ display: "block", marginBottom: 5 }}>To date</label>
                <input type="date" className="form-input" value={dateTo} min={dateFrom} onChange={e => setDateTo(e.target.value)} />
              </div>
              <div>
                <label className="stat-label" style={{ display: "block", marginBottom: 5 }}>Visit status</label>
                <select className="form-input" style={{ appearance: "auto" }} value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
                  <option value="">Any</option>
                  <option value="signed">Completed</option>
                  <option value="in_progress">In progress</option>
                </select>
              </div>
              <div>
                <label className="stat-label" style={{ display: "block", marginBottom: 5 }}>Doctor</label>
                <select className="form-input" style={{ appearance: "auto" }} value={doctorFilter} onChange={e => setDoctorFilter(e.target.value)}>
                  <option value="">Any doctor</option>
                  {doctorOptions.map(d => <option key={d} value={d}>Dr. {d}</option>)}
                </select>
              </div>
              {hasActiveFilters && (
                <div style={{ display: "flex", alignItems: "flex-end" }}>
                  <button type="button" className="btn-outline" style={{ fontSize: 12, padding: "8px 12px", display: "flex", alignItems: "center", gap: 4 }}
                    onClick={() => { setSearch(""); setDateFrom(""); setDateTo(""); setStatusFilter(""); setDoctorFilter(""); }}>
                    <X size={12} /> Clear
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

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
              {hasActiveFilters ? "Nothing matches these filters" : "No prescriptions yet"}
            </div>
            <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
              {hasActiveFilters ? "Try clearing search or filters." : "After your consultation, everything the doctor prescribes will appear here."}
            </div>
          </div>
        ) : (
          <div style={{ display: "grid", gap: 16 }}>
            {records.map((r, idx) => (
              <ConsultRecordCard key={idx} r={r} />
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
