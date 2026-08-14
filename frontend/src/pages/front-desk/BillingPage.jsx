/**
 * pages/front-desk/BillingPage.jsx
 * ------------------------------------
 * Front desk billing. Two panels:
 *   - Today's appointments needing billing (payment_preference = pay at
 *     desk) — "Bill" opens a line-item invoice builder pulled from the
 *     BillingService catalog.
 *   - Recent invoices — "Record Payment" collects cash/card/UPI against
 *     whatever's still outstanding.
 */
import { useState, useCallback, useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useApi }    from "../../hooks/useApi";
import { useToast }  from "../../hooks/useToast";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";

const TODAY = new Date().toISOString().split("T")[0];

const INVOICE_BADGE = {
  draft:          "badge--neutral",
  issued:         "badge--primary",
  paid:           "badge--success",
  partially_paid: "badge--warning",
  cancelled:      "badge--error",
};

const inputStyle = {
  width: "100%", boxSizing: "border-box",
  border: "1.5px solid var(--color-border)", borderRadius: 8,
  padding: "9px 12px", fontSize: 14,
  background: "var(--color-surface)", color: "var(--color-text)", outline: "none",
};
const labelStyle = { display: "block", fontSize: 12, fontWeight: 600, marginBottom: 5 };

function BillModal({ appointment, services, onClose, onCreated }) {
  const { toastSuccess, toastApiError } = useToast();
  const [items, setItems] = useState([{ service: "", description: "", quantity: 1, unit_price: "", tax_rate: 0 }]);
  const [saving, setSaving] = useState(false);

  function updateItem(i, patch) {
    setItems(list => list.map((it, idx) => idx === i ? { ...it, ...patch } : it));
  }
  function pickService(i, serviceId) {
    const svc = services.find(s => String(s.id) === String(serviceId));
    updateItem(i, {
      service: serviceId,
      description: svc?.name || "",
      unit_price: svc?.unit_price || "",
      tax_rate: svc?.tax_rate || 0,
    });
  }
  function addRow() {
    setItems(list => [...list, { service: "", description: "", quantity: 1, unit_price: "", tax_rate: 0 }]);
  }
  function removeRow(i) {
    setItems(list => list.filter((_, idx) => idx !== i));
  }

  const total = items.reduce((sum, it) => {
    const qty = Number(it.quantity) || 0;
    const price = Number(it.unit_price) || 0;
    const tax = Number(it.tax_rate) || 0;
    return sum + qty * price * (1 + tax / 100);
  }, 0);

  async function handleSubmit(e) {
    e.preventDefault();
    const validItems = items.filter(it => it.description && Number(it.unit_price) > 0);
    if (validItems.length === 0) {
      toastApiError({ message: "Add at least one billable item." }, "Nothing to bill.");
      return;
    }
    setSaving(true);
    try {
      await apiClient.post(API_ENDPOINTS.BILLING.INVOICES, {
        appointment_id: appointment.id,
        items: validItems.map(it => ({
          service: it.service || null,
          description: it.description,
          quantity: Number(it.quantity) || 1,
          unit_price: Number(it.unit_price),
          tax_rate: Number(it.tax_rate) || 0,
        })),
      });
      toastSuccess("Invoice created.");
      onCreated();
      onClose();
    } catch (err) {
      toastApiError(err, "Could not create invoice.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(0,0,0,0.45)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div style={{ background: "var(--color-surface)", borderRadius: 16, width: "100%", maxWidth: 620, maxHeight: "90vh", overflowY: "auto", padding: 32, boxShadow: "0 20px 60px rgba(0,0,0,0.3)" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
          <h2 style={{ margin: 0, fontSize: 18 }}>Bill — {appointment.patient_name}</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer" }}>✕</button>
        </div>
        <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 20 }}>
          Token #{appointment.token_number} · {appointment.doctor_name}
        </div>

        <form onSubmit={handleSubmit}>
          <div style={{ display: "grid", gap: 12 }}>
            {items.map((it, i) => (
              <div key={i} style={{
                display: "grid", gridTemplateColumns: "1.6fr 0.6fr 0.8fr 0.6fr auto", gap: 8,
                alignItems: "end", padding: "10px 0", borderBottom: "1px solid var(--color-border)",
              }}>
                <div>
                  <label style={labelStyle}>Service</label>
                  <select style={inputStyle} value={it.service}
                    onChange={e => e.target.value ? pickService(i, e.target.value) : updateItem(i, { service: "" })}>
                    <option value="">Custom item</option>
                    {services.map(s => <option key={s.id} value={s.id}>{s.name} (₹{s.unit_price})</option>)}
                  </select>
                  {!it.service && (
                    <input style={{ ...inputStyle, marginTop: 6 }} placeholder="Description"
                      value={it.description} onChange={e => updateItem(i, { description: e.target.value })} />
                  )}
                </div>
                <div>
                  <label style={labelStyle}>Qty</label>
                  <input style={inputStyle} type="number" min="1" value={it.quantity}
                    onChange={e => updateItem(i, { quantity: e.target.value })} />
                </div>
                <div>
                  <label style={labelStyle}>Unit Price (₹)</label>
                  <input style={inputStyle} type="number" min="0" step="0.01" value={it.unit_price}
                    onChange={e => updateItem(i, { unit_price: e.target.value })} />
                </div>
                <div>
                  <label style={labelStyle}>Tax %</label>
                  <input style={inputStyle} type="number" min="0" step="0.01" value={it.tax_rate}
                    onChange={e => updateItem(i, { tax_rate: e.target.value })} />
                </div>
                <button type="button" onClick={() => removeRow(i)}
                  style={{ background: "none", border: "none", color: "var(--color-error)", cursor: "pointer", fontSize: 18, padding: "8px 4px" }}>
                  ✕
                </button>
              </div>
            ))}
          </div>

          <button type="button" onClick={addRow} className="btn-outline" style={{ fontSize: 12, padding: "6px 14px", marginTop: 12 }}>
            + Add item
          </button>

          <div style={{
            display: "flex", justifyContent: "space-between", alignItems: "center",
            marginTop: 20, paddingTop: 16, borderTop: "1.5px solid var(--color-border)",
          }}>
            <div style={{ fontSize: 14, fontWeight: 700 }}>Total: ₹{total.toFixed(2)}</div>
            <div style={{ display: "flex", gap: 10 }}>
              <button type="button" onClick={onClose} className="btn-outline" style={{ padding: "9px 18px" }}>Cancel</button>
              <button type="submit" disabled={saving} className="btn-primary" style={{ padding: "9px 18px" }}>
                {saving ? "Creating…" : "Create Invoice"}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}

function PaymentModal({ invoice, onClose, onRecorded }) {
  const { toastSuccess, toastApiError } = useToast();
  const outstanding = Number(invoice.total_amount) - Number(invoice.paid_amount);
  const [amount, setAmount] = useState(outstanding > 0 ? outstanding.toFixed(2) : "0");
  const [mode, setMode] = useState("cash");
  const [ref, setRef] = useState("");
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setSaving(true);
    try {
      await apiClient.post(API_ENDPOINTS.BILLING.PAYMENTS, {
        invoice: invoice.id,
        amount: Number(amount),
        payment_mode: mode,
        transaction_ref: ref,
      });
      toastSuccess("Payment recorded.");
      onRecorded();
      onClose();
    } catch (err) {
      toastApiError(err, "Could not record payment.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(0,0,0,0.45)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div style={{ background: "var(--color-surface)", borderRadius: 16, width: "100%", maxWidth: 420, padding: 32, boxShadow: "0 20px 60px rgba(0,0,0,0.3)" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
          <h2 style={{ margin: 0, fontSize: 18 }}>Record Payment</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer" }}>✕</button>
        </div>
        <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 18 }}>
          {invoice.invoice_number} · Outstanding: ₹{outstanding.toFixed(2)}
        </div>
        <form onSubmit={handleSubmit}>
          <div style={{ display: "grid", gap: 14 }}>
            <div><label style={labelStyle}>Amount (₹)</label>
              <input style={inputStyle} type="number" min="0" step="0.01" value={amount} onChange={e => setAmount(e.target.value)} required />
            </div>
            <div><label style={labelStyle}>Payment Mode</label>
              <select style={inputStyle} value={mode} onChange={e => setMode(e.target.value)}>
                <option value="cash">Cash</option>
                <option value="card">Card</option>
                <option value="upi">UPI</option>
                <option value="online">Online</option>
                <option value="credit">Credit</option>
              </select>
            </div>
            <div><label style={labelStyle}>Transaction Ref (optional)</label>
              <input style={inputStyle} value={ref} onChange={e => setRef(e.target.value)} placeholder="UPI/txn ID" />
            </div>
          </div>
          <div style={{ display: "flex", gap: 10, marginTop: 22 }}>
            <button type="button" onClick={onClose} className="btn-outline" style={{ flex: 1, padding: "9px 0" }}>Cancel</button>
            <button type="submit" disabled={saving} className="btn-primary" style={{ flex: 2, padding: "9px 0" }}>
              {saving ? "Recording…" : "Record Payment"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function BillingPage() {
  const { toastApiError } = useToast();
  const location = useLocation();
  const navigate = useNavigate();
  // Arriving from the OPD Queue's "Bill" button for one specific patient —
  // open straight to their invoice builder instead of landing on the
  // generic billing page and making front desk hunt for the right row
  // themselves in "Today's patients".
  const [billModal, setBillModal] = useState(() => location.state?.appointment || null);
  const [payModal, setPayModal] = useState(null);

  useEffect(() => {
    if (location.state) navigate(location.pathname, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const { data: apptData, isLoading: apptLoading, refetch: refetchAppts } =
    useApi(API_ENDPOINTS.OPD.APPOINTMENTS, { params: { date: TODAY, page_size: 100 } });
  const appointments = (apptData?.results || []).filter(a => a.status !== "cancelled");

  const { data: invData, isLoading: invLoading, refetch: refetchInvoices } =
    useApi(API_ENDPOINTS.BILLING.INVOICES, { params: { page_size: 20 } });
  const invoices = invData?.results || [];

  const { data: svcData } = useApi(API_ENDPOINTS.BILLING.SERVICES);
  const services = svcData?.data || svcData || [];

  const refreshAll = useCallback(() => { refetchAppts(); refetchInvoices(); }, [refetchAppts, refetchInvoices]);

  const needsBilling = appointments.filter(a => a.payment_preference !== "pay_online" || true);
  // ^ show every non-cancelled appointment today — front desk may need to
  // bill a "pay online" patient too if online payment didn't go through.

  return (
    <AppShell>
      <PageShell title="Billing">
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, alignItems: "start" }}>

          {/* Today's appointments needing billing */}
          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--color-border)" }}>
              <span className="dot-label dot-label--gold">Today's patients</span>
            </div>
            {apptLoading ? (
              <div style={{ padding: 32, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
            ) : needsBilling.length === 0 ? (
              <div style={{ padding: 32, textAlign: "center", color: "var(--color-text-muted)", fontSize: 13 }}>
                No appointments today.
              </div>
            ) : (
              <div>
                {needsBilling.map(a => (
                  <div key={a.id} style={{
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                    padding: "12px 20px", borderBottom: "1px solid var(--color-border)",
                  }}>
                    <div>
                      <div style={{ fontWeight: 600, fontSize: 13 }}>{a.patient_name || "—"}</div>
                      <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
                        Token #{a.token_number} · {a.doctor_name}
                        {a.payment_preference === "pay_at_desk" && (
                          <span className="badge badge--warning" style={{ marginLeft: 6, fontSize: 10 }}>Pay at desk</span>
                        )}
                      </div>
                    </div>
                    <button className="btn-primary" style={{ fontSize: 11, padding: "5px 12px" }} onClick={() => setBillModal(a)}>
                      Bill
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Recent invoices */}
          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <div style={{
              display: "flex", justifyContent: "space-between", alignItems: "center",
              padding: "14px 20px", borderBottom: "1px solid var(--color-border)",
            }}>
              <span className="dot-label dot-label--green">Recent invoices</span>
              <button className="btn-outline" style={{ fontSize: 12, padding: "5px 14px" }} onClick={refreshAll}>Refresh</button>
            </div>
            {invLoading ? (
              <div style={{ padding: 32, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
            ) : invoices.length === 0 ? (
              <div style={{ padding: 32, textAlign: "center", color: "var(--color-text-muted)", fontSize: 13 }}>
                No invoices yet — bill a patient from the left.
              </div>
            ) : (
              <div>
                {invoices.map(inv => {
                  const outstanding = Number(inv.total_amount) - Number(inv.paid_amount);
                  return (
                    <div key={inv.id} style={{
                      display: "flex", alignItems: "center", justifyContent: "space-between",
                      padding: "12px 20px", borderBottom: "1px solid var(--color-border)",
                    }}>
                      <div>
                        <div style={{ fontWeight: 600, fontSize: 13 }}>{inv.invoice_number}</div>
                        <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
                          ₹{inv.total_amount} total
                          {outstanding > 0 && ` · ₹${outstanding.toFixed(2)} due`}
                        </div>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span className={`badge ${INVOICE_BADGE[inv.status] || "badge--neutral"}`}>{inv.status?.replace("_", " ")}</span>
                        {outstanding > 0 && (
                          <button className="btn-outline" style={{ fontSize: 11, padding: "5px 12px" }} onClick={() => setPayModal(inv)}>
                            Record Payment
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {billModal && (
          <BillModal
            appointment={billModal}
            services={services}
            onClose={() => setBillModal(null)}
            onCreated={refreshAll}
          />
        )}
        {payModal && (
          <PaymentModal
            invoice={payModal}
            onClose={() => setPayModal(null)}
            onRecorded={refreshAll}
          />
        )}
      </PageShell>
    </AppShell>
  );
}
