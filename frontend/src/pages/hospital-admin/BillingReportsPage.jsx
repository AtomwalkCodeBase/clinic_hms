/**
 * pages/hospital-admin/BillingReportsPage.jsx
 * ---------------------------------------------
 * Hospital admin: billing reports (HMS-09d-1 payment ledger, HMS-09d-2
 * revenue reports). Two tabs sharing one date-range filter:
 *   - Overview — billed vs collected vs outstanding for the range, a
 *     payment-mode breakdown, and a day-by-day table with the same tiny
 *     inline sparkline pattern DashboardPage.jsx already uses (no charting
 *     library in this app yet, so this stays consistent rather than
 *     introducing one for a single page).
 *   - Ledger — every payment recorded, filterable, with a running total
 *     over the whole filtered set (not just the current page).
 */
import { useState, useEffect, useCallback } from "react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import PaginationControls from "../../components/common/PaginationControls";
import { useApi }    from "../../hooks/useApi";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import { TrendingUp, IndianRupee, Wallet, ListChecks } from "lucide-react";

const todayStr = () => new Date().toISOString().split("T")[0];
const daysAgoStr = n => new Date(Date.now() - n * 86400000).toISOString().split("T")[0];

function money(v) {
  return `₹${Number(v || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/* Same tiny inline sparkline as hospital-admin DashboardPage.jsx */
function Sparkline({ points, width = 100, height = 32, color = "var(--color-primary)" }) {
  if (!points || points.length < 2) points = [0, 0];
  const max = Math.max(...points, 1);
  const step = width / (points.length - 1);
  const d = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(1)},${(height - (p / max) * height + 2).toFixed(1)}`)
    .join(" ");
  return (
    <svg width={width} height={height + 4} style={{ overflow: "visible" }}>
      <path d={d} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" opacity="0.9" />
    </svg>
  );
}

function StatCard({ icon: Icon, label, value, sub, dotClass = "dot-label--green" }) {
  return (
    <div className="card" style={{ padding: "16px 20px" }}>
      <div className={`dot-label ${dotClass}`} style={{ marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
        {Icon && <Icon size={13} />} {label}
      </div>
      <div style={{ fontFamily: "var(--font-display)", fontSize: 24, fontWeight: 600 }}>{value}</div>
      {sub && <div style={{ fontSize: 11.5, color: "var(--color-text-muted)", marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

function DateRangeBar({ from, to, onFrom, onTo }) {
  return (
    <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 18 }}>
      <label style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text-muted)" }}>From</label>
      <input type="date" className="form-input" value={from} max={to} onChange={e => onFrom(e.target.value)} style={{ width: 160 }} />
      <label style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text-muted)" }}>To</label>
      <input type="date" className="form-input" value={to} min={from} max={todayStr()} onChange={e => onTo(e.target.value)} style={{ width: 160 }} />
    </div>
  );
}

function OverviewTab({ dateFrom, dateTo }) {
  const { data, isLoading } = useApi(API_ENDPOINTS.BILLING.REVENUE_REPORT, {
    params: { date_from: dateFrom, date_to: dateTo },
  });

  const daily = data?.daily || [];
  const billedPoints = daily.map(d => Number(d.billed));
  const collectedPoints = daily.map(d => Number(d.collected));

  return (
    <>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14, marginBottom: 22 }}>
        <StatCard icon={IndianRupee} label="Billed" value={isLoading ? "—" : money(data?.total_billed)}
          sub={`${data?.invoice_count ?? 0} invoices`} dotClass="dot-label--blue" />
        <StatCard icon={Wallet} label="Collected" value={isLoading ? "—" : money(data?.total_collected)}
          sub={`${data?.payment_count ?? 0} payments`} dotClass="dot-label--green" />
        <StatCard icon={TrendingUp} label="Collection rate" value={isLoading ? "—" : (data?.collection_rate != null ? `${(data.collection_rate * 100).toFixed(0)}%` : "—")}
          sub="Collected ÷ billed, this range" dotClass="dot-label--gold" />
        <StatCard icon={ListChecks} label="Outstanding" value={isLoading ? "—" : money(data?.total_outstanding)}
          sub="Across all unpaid invoices (not range-limited)" dotClass="dot-label--red" />
      </div>

      <div className="card" style={{ padding: 20, marginBottom: 20 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
          <h3 style={{ margin: 0, fontSize: 15 }}>Daily trend</h3>
          <div style={{ display: "flex", gap: 16, fontSize: 11.5 }}>
            <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <Sparkline points={billedPoints.length ? billedPoints : [0, 0]} width={40} height={14} color="var(--color-info)" /> Billed
            </span>
            <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <Sparkline points={collectedPoints.length ? collectedPoints : [0, 0]} width={40} height={14} color="var(--color-success)" /> Collected
            </span>
          </div>
        </div>
        {isLoading ? (
          <div style={{ padding: 24, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
        ) : daily.length === 0 ? (
          <div style={{ padding: 24, textAlign: "center", color: "var(--color-text-muted)", fontSize: 13 }}>No billing activity in this range.</div>
        ) : (
          <table className="data-table">
            <thead><tr><th>Date</th><th>Billed</th><th>Collected</th></tr></thead>
            <tbody>
              {daily.slice().reverse().map(d => (
                <tr key={d.date}>
                  <td style={{ fontSize: 12.5 }}>{d.date}</td>
                  <td style={{ fontSize: 12.5 }}>{money(d.billed)}</td>
                  <td style={{ fontSize: 12.5 }}>{money(d.collected)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card" style={{ padding: 20 }}>
        <h3 style={{ margin: "0 0 14px", fontSize: 15 }}>By payment mode</h3>
        {isLoading ? (
          <div style={{ padding: 12, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
        ) : (data?.by_payment_mode || []).length === 0 ? (
          <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>No payments in this range.</div>
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            {data.by_payment_mode.map(row => (
              <div key={row.payment_mode} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "8px 0", borderBottom: "1px solid var(--color-border)" }}>
                <span>{row.payment_mode}</span>
                <span style={{ fontWeight: 700 }}>{money(row.amount)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}

function LedgerTab({ dateFrom, dateTo }) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [mode, setMode] = useState("");
  const [modes, setModes] = useState([]);

  useEffect(() => {
    apiClient.get(API_ENDPOINTS.BILLING.PAYMENT_MODES).then(r => setModes(r.data?.data || [])).catch(() => {});
  }, []);

  const { data, isLoading } = useApi(API_ENDPOINTS.BILLING.PAYMENTS, {
    params: { date_from: dateFrom, date_to: dateTo, payment_mode: mode || undefined, page, page_size: pageSize },
  });
  const rows = data?.results || [];
  const pagination = data?.pagination || null;

  return (
    <div className="card" style={{ padding: 0, overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 20px", borderBottom: "1px solid var(--color-border)", flexWrap: "wrap", gap: 10 }}>
        <span className="dot-label dot-label--green">
          Payments in range — total {isLoading ? "—" : money(data?.total_amount)}
        </span>
        <select className="form-input" style={{ width: 160, appearance: "auto" }} value={mode} onChange={e => { setMode(e.target.value); setPage(1); }}>
          <option value="">All payment modes</option>
          {modes.map(m => <option key={m.id} value={m.name}>{m.name}</option>)}
        </select>
      </div>
      {isLoading ? (
        <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
      ) : rows.length === 0 ? (
        <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)", fontSize: 13 }}>No payments recorded in this range.</div>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Date</th><th>Invoice</th><th>Patient</th><th>Amount</th><th>Mode</th><th>Ref</th><th>Recorded by</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(p => (
              <tr key={p.id}>
                <td style={{ fontSize: 12 }}>{p.paid_at ? new Date(p.paid_at).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—"}</td>
                <td style={{ fontSize: 12, fontWeight: 700 }}>{p.invoice_number}</td>
                <td style={{ fontSize: 12 }}>{p.patient_name} <span style={{ color: "var(--color-text-muted)" }}>· {p.patient_uhid}</span></td>
                <td style={{ fontSize: 12, fontWeight: 700 }}>{money(p.amount)}</td>
                <td style={{ fontSize: 12 }}>{p.payment_mode}</td>
                <td style={{ fontSize: 11, color: "var(--color-text-muted)" }}>{p.transaction_ref || "—"}</td>
                <td style={{ fontSize: 12 }}>{p.recorded_by_name || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <PaginationControls pagination={pagination} page={page} pageSize={pageSize} onPageChange={setPage} onPageSizeChange={setPageSize} />
    </div>
  );
}

export default function BillingReportsPage() {
  const [tab, setTab] = useState("overview");
  const [dateFrom, setDateFrom] = useState(daysAgoStr(29));
  const [dateTo, setDateTo] = useState(todayStr());

  return (
    <AppShell>
      <PageShell title="Billing Reports">
        <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
          {[["overview", "Revenue Overview"], ["ledger", "Payment Ledger"]].map(([val, label]) => (
            <button key={val} className={tab === val ? "btn-primary" : "btn-outline"}
              style={{ fontSize: 12, padding: "6px 16px" }} onClick={() => setTab(val)}>
              {label}
            </button>
          ))}
        </div>

        <DateRangeBar from={dateFrom} to={dateTo} onFrom={setDateFrom} onTo={setDateTo} />

        {tab === "overview"
          ? <OverviewTab dateFrom={dateFrom} dateTo={dateTo} />
          : <LedgerTab dateFrom={dateFrom} dateTo={dateTo} />}
      </PageShell>
    </AppShell>
  );
}
