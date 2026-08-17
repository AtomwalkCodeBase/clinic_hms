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
import { openDataUrlInNewTab } from "../../utils/fileViewer";

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

function PatientBalanceSummary({ appointmentId }) {
  const [summary, setSummary] = useState(null);
  useEffect(() => {
    if (!appointmentId) return;
    apiClient.get(API_ENDPOINTS.BILLING.SUMMARY, { params: { appointment_id: appointmentId } })
      .then(r => setSummary(r.data?.data || null))
      .catch(() => setSummary(null));
  }, [appointmentId]);

  if (!summary) return null;
  const outstanding = Number(summary.grand_outstanding);

  return (
    <div style={{
      display: "flex", gap: 14, flexWrap: "wrap", fontSize: 11.5,
      padding: "8px 12px", borderRadius: 8, background: "var(--color-bg)",
      border: "1px solid var(--color-border)", marginBottom: 14,
    }}>
      <span><strong>Billing:</strong> ₹{summary.billing.total} ({summary.billing.invoice_count})</span>
      <span><strong>Lab:</strong> ₹{summary.lab.total} ({summary.lab.request_count})</span>
      <span><strong>Pharmacy (est.):</strong> ₹{summary.pharmacy.estimated_total}</span>
      {outstanding > 0 && (
        <span style={{ color: "var(--color-error)", fontWeight: 700 }}>
          Outstanding across all: ₹{outstanding.toFixed(2)}
        </span>
      )}
    </div>
  );
}

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
        <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 14 }}>
          Token #{appointment.token_number} · {appointment.doctor_name}
        </div>

        <PatientBalanceSummary appointmentId={appointment.id} />

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
  const [modes, setModes] = useState([]);
  const [mode, setMode] = useState("");
  const [ref, setRef] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    apiClient.get(API_ENDPOINTS.BILLING.PAYMENT_MODES)
      .then(r => {
        const list = r.data?.data || [];
        setModes(list);
        if (list.length) setMode(list[0].name);
      })
      .catch(() => {});
  }, []);

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
                {modes.map(m => <option key={m.id} value={m.name}>{m.name}</option>)}
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

function InvoiceDetailModal({ invoiceId, onClose, onChanged }) {
  const { toastSuccess, toastApiError } = useToast();
  const [invoice, setInvoice] = useState(null);
  const [services, setServices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [discount, setDiscount] = useState("");
  const [savingDiscount, setSavingDiscount] = useState(false);
  const [newItem, setNewItem] = useState({ service: "", description: "", quantity: 1, unit_price: "", tax_rate: 0 });
  const [addingItem, setAddingItem] = useState(false);
  const [pdfLoading, setPdfLoading] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([
      apiClient.get(API_ENDPOINTS.BILLING.INVOICE(invoiceId)),
      apiClient.get(API_ENDPOINTS.BILLING.SERVICES),
    ]).then(([invRes, svcRes]) => {
      const inv = invRes.data?.data;
      setInvoice(inv);
      setDiscount(inv?.discount_amount ?? "0");
      setServices(svcRes.data?.data || []);
    }).catch(() => setInvoice(null))
      .finally(() => setLoading(false));
  }, [invoiceId]);
  useEffect(() => { load(); }, [load]);

  async function saveDiscount() {
    setSavingDiscount(true);
    try {
      await apiClient.patch(API_ENDPOINTS.BILLING.INVOICE(invoiceId), { discount_amount: Number(discount) || 0 });
      toastSuccess("Discount applied.");
      load();
      onChanged();
    } catch (err) {
      toastApiError(err, "Could not apply discount.");
    } finally {
      setSavingDiscount(false);
    }
  }

  function pickService(serviceId) {
    const svc = services.find(s => String(s.id) === String(serviceId));
    setNewItem({
      service: serviceId,
      description: svc?.name || "",
      quantity: 1,
      unit_price: svc?.unit_price || "",
      tax_rate: svc?.tax_rate || 0,
    });
  }

  async function addItem(e) {
    e.preventDefault();
    if (!newItem.description || !Number(newItem.unit_price)) return;
    setAddingItem(true);
    try {
      await apiClient.post(API_ENDPOINTS.BILLING.INVOICE_ITEMS(invoiceId), {
        service: newItem.service || null,
        description: newItem.description,
        quantity: Number(newItem.quantity) || 1,
        unit_price: Number(newItem.unit_price),
        tax_rate: Number(newItem.tax_rate) || 0,
      });
      toastSuccess("Item added.");
      setNewItem({ service: "", description: "", quantity: 1, unit_price: "", tax_rate: 0 });
      load();
      onChanged();
    } catch (err) {
      toastApiError(err, "Could not add item.");
    } finally {
      setAddingItem(false);
    }
  }

  const canEdit = invoice && (invoice.status === "draft" || invoice.status === "issued");

  async function downloadPdf() {
    const win = window.open("", "_blank");
    setPdfLoading(true);
    try {
      const res = await apiClient.get(API_ENDPOINTS.BILLING.INVOICE_PDF(invoiceId));
      const data = res.data?.data || res.data;
      if (data?.file_data) {
        openDataUrlInNewTab(win, data.file_data);
      } else if (win) {
        win.close();
      }
    } catch (err) {
      toastApiError(err, "Could not generate the invoice PDF.");
      if (win) win.close();
    } finally {
      setPdfLoading(false);
    }
  }

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(0,0,0,0.45)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div style={{ background: "var(--color-surface)", borderRadius: 16, width: "100%", maxWidth: 640, maxHeight: "90vh", overflowY: "auto", padding: 32, boxShadow: "0 20px 60px rgba(0,0,0,0.3)" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
          <h2 style={{ margin: 0, fontSize: 18 }}>{invoice?.invoice_number || "Invoice"}</h2>
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            {invoice && (
              <button type="button" onClick={downloadPdf} disabled={pdfLoading}
                className="btn-outline" style={{ fontSize: 12, padding: "6px 14px" }}>
                {pdfLoading ? "Preparing…" : "Print / PDF"}
              </button>
            )}
            <button onClick={onClose} style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer" }}>✕</button>
          </div>
        </div>

        {loading || !invoice ? (
          <div style={{ padding: 32, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
        ) : (
          <>
            <span className={`badge ${INVOICE_BADGE[invoice.status] || "badge--neutral"}`}>{invoice.status?.replace("_", " ")}</span>

            <div style={{ marginTop: 18, marginBottom: 6, fontSize: 12, fontWeight: 700, color: "var(--color-text-muted)" }}>ITEMS</div>
            <div style={{ display: "grid", gap: 6, marginBottom: 14 }}>
              {(invoice.items || []).map(it => (
                <div key={it.id} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "6px 0", borderBottom: "1px solid var(--color-border)" }}>
                  <span>{it.description} {it.quantity > 1 && `× ${it.quantity}`}</span>
                  <span>₹{it.total}{Number(it.tax_rate) > 0 && ` (+${it.tax_rate}% tax)`}</span>
                </div>
              ))}
              {(invoice.items || []).length === 0 && <div style={{ fontSize: 12, color: "var(--color-text-muted)", fontStyle: "italic" }}>No items.</div>}
            </div>

            {canEdit && (
              <form onSubmit={addItem} style={{ display: "grid", gridTemplateColumns: "1.4fr 0.6fr 0.8fr 0.6fr auto", gap: 8, alignItems: "end", marginBottom: 18, padding: 10, borderRadius: 8, background: "var(--color-bg)" }}>
                <div>
                  <select style={inputStyle} value={newItem.service} onChange={e => e.target.value ? pickService(e.target.value) : setNewItem(f => ({ ...f, service: "" }))}>
                    <option value="">Custom item</option>
                    {services.map(s => <option key={s.id} value={s.id}>{s.name} (₹{s.unit_price})</option>)}
                  </select>
                  {!newItem.service && (
                    <input style={{ ...inputStyle, marginTop: 6 }} placeholder="Description" value={newItem.description}
                      onChange={e => setNewItem(f => ({ ...f, description: e.target.value }))} />
                  )}
                </div>
                <input style={inputStyle} type="number" min="1" value={newItem.quantity} placeholder="Qty"
                  onChange={e => setNewItem(f => ({ ...f, quantity: e.target.value }))} />
                <input style={inputStyle} type="number" min="0" step="0.01" value={newItem.unit_price} placeholder="Price"
                  onChange={e => setNewItem(f => ({ ...f, unit_price: e.target.value }))} />
                <input style={inputStyle} type="number" min="0" step="0.01" value={newItem.tax_rate} placeholder="Tax %"
                  onChange={e => setNewItem(f => ({ ...f, tax_rate: e.target.value }))} />
                <button type="submit" disabled={addingItem} className="btn-outline" style={{ fontSize: 12, padding: "8px 12px" }}>
                  {addingItem ? "…" : "+ Add"}
                </button>
              </form>
            )}

            <div style={{ display: "grid", gap: 4, fontSize: 13, marginBottom: 14 }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}><span>Subtotal</span><span>₹{invoice.subtotal}</span></div>
              <div style={{ display: "flex", justifyContent: "space-between" }}><span>Tax</span><span>₹{invoice.tax_amount}</span></div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span>Discount</span>
                {canEdit ? (
                  <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
                    <input style={{ ...inputStyle, width: 90, padding: "5px 8px" }} type="number" min="0" step="0.01"
                      value={discount} onChange={e => setDiscount(e.target.value)} />
                    <button type="button" onClick={saveDiscount} disabled={savingDiscount} className="btn-outline" style={{ fontSize: 11, padding: "5px 10px" }}>
                      {savingDiscount ? "…" : "Apply"}
                    </button>
                  </span>
                ) : <span>₹{invoice.discount_amount}</span>}
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontWeight: 700, fontSize: 14, borderTop: "1.5px solid var(--color-border)", paddingTop: 6, marginTop: 4 }}>
                <span>Total</span><span>₹{invoice.total_amount}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", color: "var(--color-text-muted)" }}>
                <span>Paid</span><span>₹{invoice.paid_amount}</span>
              </div>
            </div>

            {(invoice.payments || []).length > 0 && (
              <>
                <div style={{ marginBottom: 6, fontSize: 12, fontWeight: 700, color: "var(--color-text-muted)" }}>PAYMENTS</div>
                <div style={{ display: "grid", gap: 4, marginBottom: 14 }}>
                  {invoice.payments.map(p => (
                    <div key={p.id} style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5 }}>
                      <span>{p.payment_mode}{p.transaction_ref && ` · ${p.transaction_ref}`}</span>
                      <span>₹{p.amount}</span>
                    </div>
                  ))}
                </div>
              </>
            )}

            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button type="button" onClick={onClose} className="btn-outline" style={{ padding: "9px 18px" }}>Close</button>
            </div>
          </>
        )}
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
  const [detailModalId, setDetailModalId] = useState(null);

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
                        <button onClick={() => setDetailModalId(inv.id)}
                          style={{ background: "none", border: "none", padding: 0, cursor: "pointer", fontWeight: 600, fontSize: 13, color: "var(--color-primary)", textDecoration: "underline" }}>
                          {inv.invoice_number}
                        </button>
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
        {detailModalId && (
          <InvoiceDetailModal
            invoiceId={detailModalId}
            onClose={() => setDetailModalId(null)}
            onChanged={refreshAll}
          />
        )}
      </PageShell>
    </AppShell>
  );
}
