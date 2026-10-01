import { useToast } from "../../../hooks/useToast";
import { useApi } from "../../../hooks/useApi";
import API_ENDPOINTS from "../../../config/api.config";
import { useState, useRef, useEffect } from "react";
import { encounterApi } from "../../../api";
import { CHOICE_BADGE, LAB_STATUS_BADGE } from "./constants";

export function LabOrderSection({ encounterId, isClosed, onViewReport }) {
  const { toastSuccess, toastApiError } = useToast();
  const { data: catalogData } = useApi(API_ENDPOINTS.LAB.CATALOG);
  const catalog = catalogData || [];

  const { data: ordersData, refetch: refetchOrders } = useApi(
    API_ENDPOINTS.LAB.REQUESTS, { params: { encounter_id: encounterId } }
  );
  const orders = ordersData?.results || [];
  const orderedTestIds = new Set(orders.map(o => o.test));

  const [selected, setSelected] = useState([]); // [{id, name}]
  const [ordering, setOrdering] = useState(false);
  const [q, setQ] = useState("");
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    function handler(e) {
      if (ref.current && !ref.current.contains(e.target)) setDropdownOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const results = catalog
    .filter(t => !selected.some(s => s.id === t.id) && !orderedTestIds.has(t.id))
    .filter(t => q.length === 0 || t.name.toLowerCase().includes(q.toLowerCase()) || (t.code || "").toLowerCase().includes(q.toLowerCase()));

  function addTest(t) {
    setSelected(prev => [...prev, { id: t.id, name: t.name }]);
    setQ("");
  }

  function removeSelected(id) {
    setSelected(prev => prev.filter(s => s.id !== id));
  }

  async function orderSelected() {
    if (selected.length === 0) return;
    setOrdering(true);
    try {
      await encounterApi.orderLabTests(encounterId, selected.map(s => s.id));
      toastSuccess(`${selected.length} test(s) ordered.`);
      setSelected([]);
      refetchOrders();
    } catch (err) {
      toastApiError(err, "Could not order tests.");
    } finally {
      setOrdering(false);
    }
  }

  return (
    <div style={{ marginBottom: 14 }}>
      {!isClosed && (
        <div style={{ marginBottom: 12 }}>
          <div ref={ref} style={{ position: "relative" }}>
            <input
              className="form-input"
              value={q}
              onChange={e => { setQ(e.target.value); setDropdownOpen(true); }}
              onFocus={() => setDropdownOpen(true)}
              placeholder="Search the lab catalog — add multiple tests…"
              style={{ width: "100%", boxSizing: "border-box" }}
            />
            {dropdownOpen && (
              <div style={{
                position: "absolute", zIndex: 100, top: "calc(100% + 4px)", left: 0, right: 0,
                background: "#fff", border: "1px solid var(--color-border)", borderRadius: 8,
                boxShadow: "0 4px 24px rgba(0,0,0,0.12)", maxHeight: 220, overflowY: "auto",
              }}>
                {catalog.length === 0 ? (
                  <div style={{ padding: "10px 14px", fontSize: 12, color: "var(--color-text-muted)" }}>
                    No tests in the catalog yet — ask lab staff to add tests under "Test Catalog".
                  </div>
                ) : results.length === 0 ? (
                  <div style={{ padding: "10px 14px", fontSize: 12, color: "var(--color-text-muted)" }}>
                    No matching tests.
                  </div>
                ) : results.map(t => (
                  <div key={t.id}
                    onMouseDown={() => addTest(t)}
                    style={{ padding: "9px 14px", cursor: "pointer", borderBottom: "1px solid var(--color-border)", display: "flex", justifyContent: "space-between", gap: 8 }}
                    className="hover-row"
                  >
                    <span style={{ fontSize: 13 }}>{t.name}{t.code && <span style={{ color: "var(--color-text-muted)" }}> ({t.code})</span>}</span>
                    <span style={{ fontSize: 11, color: "var(--color-text-muted)", whiteSpace: "nowrap" }}>
                      {t.price != null && `₹${t.price} · `}~{t.turnaround_hours}h
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {selected.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10 }}>
              {selected.map(s => (
                <span key={s.id} style={{
                  display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12,
                  padding: "4px 6px 4px 10px", borderRadius: 20, background: "var(--color-primary-light)", color: "var(--color-primary)",
                }}>
                  {s.name}
                  <button type="button" onClick={() => removeSelected(s.id)}
                    style={{ background: "none", border: "none", cursor: "pointer", color: "var(--color-primary)", fontSize: 13, lineHeight: 1, padding: 0 }}>
                    ✕
                  </button>
                </span>
              ))}
              <button type="button" className="btn-primary" style={{ fontSize: 12, padding: "4px 14px" }}
                disabled={ordering} onClick={orderSelected}>
                {ordering ? "Ordering…" : `Order ${selected.length} test(s)`}
              </button>
            </div>
          )}
        </div>
      )}

      {orders.length > 0 && (
        <div style={{ display: "grid", gap: 8, marginBottom: 4 }}>
          {orders.map(o => {
            const choiceBadge = CHOICE_BADGE[o.patient_choice] || CHOICE_BADGE.pending;
            const statusBadge = LAB_STATUS_BADGE[o.status] || LAB_STATUS_BADGE.ordered;
            const hasReportFile = !!o.report?.file_data;
            return (
              <div key={o.id} style={{
                display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap",
                padding: "8px 10px", border: "1px solid var(--color-border)", borderRadius: 8, fontSize: 12,
              }}>
                <span style={{ fontWeight: 700, flex: 1, minWidth: 100 }}>{o.test_name}</span>
                <span style={{ padding: "2px 8px", borderRadius: 10, fontSize: 10, fontWeight: 700, background: statusBadge.bg, color: statusBadge.color }}>
                  {statusBadge.label}
                </span>
                <span style={{ padding: "2px 8px", borderRadius: 10, fontSize: 10, fontWeight: 700, background: choiceBadge.bg, color: choiceBadge.color }}>
                  {choiceBadge.label}
                </span>
                {o.patient_choice === "in_house" && o.payment_status && (
                  <span style={{ fontSize: 10, color: "var(--color-text-muted)" }}>
                    {o.payment_status.replace("_", " ")}
                  </span>
                )}
                {o.report?.result_summary && (
                  <span style={{ color: "var(--color-text-secondary)", fontSize: 11, width: "100%" }}>
                    {o.report.result_summary}
                  </span>
                )}
                {hasReportFile && (
                  <button type="button" className="btn-outline" style={{ fontSize: 11, padding: "3px 10px" }}
                    onClick={() => onViewReport?.({
                      title: o.test_name, doc_type: "lab_report", created_at: o.report.delivered_at,
                      file_data: o.report.file_data, mime_type: o.report.mime_type || "",
                    })}>
                    View Report
                  </button>
                )}
                {o.patient_choice === "outside" && o.attached_document && (
                  <button type="button" className="btn-outline" style={{ fontSize: 11, padding: "3px 10px" }}
                    onClick={() => onViewReport?.({
                      title: o.test_name, doc_type: "lab_report", created_at: o.attached_document.created_at,
                      fetchUrl: API_ENDPOINTS.PATIENTS.DOCUMENT(o.attached_document.id),
                    })}>
                    View Uploaded Report
                  </button>
                )}
                {o.patient_choice === "outside" && !o.attached_document && (
                  <span style={{ fontSize: 10, color: "var(--color-text-muted)" }}>Awaiting patient's upload</span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
