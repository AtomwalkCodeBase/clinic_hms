/**
 * components/patient/TrendSpotlightCard.jsx
 * -------------------------------------------
 * A single "<Parameter> Trend" card embedded directly in the Health
 * Insights overview — NOT a separate screen. Health Insights is a
 * lightweight enhancement panel inside My Reports, not a major module of
 * its own, so it doesn't get its own nested navigation; every section
 * lives on the one scrollable page (see HealthInsightsPanel.jsx).
 *
 * Auto-picks ONE parameter to feature: GET .../health-insights/trends/
 * (PortalLabTrendsView) already sorts by "most confident readings on
 * file", so parameters[0] is whichever analyte actually has enough
 * history to plot — there's no tab strip to choose from. If nothing yet
 * has 2+ confident readings (a single analyte quite often being the case
 * early on — a trend needs the SAME test read twice), this renders
 * nothing rather than a misleading placeholder chart.
 */
import { useState } from "react";
import { useApi } from "../../hooks/useApi";
import API_ENDPOINTS from "../../config/api.config";
import { TrendingUp, TrendingDown } from "lucide-react";

function shortDate(value) {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-IN", { month: "short", year: "numeric" });
}

function fullDate(value) {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

const STATUS_WORD = { high: "High", low: "Low", normal: "Normal" };

function TrendChart({ points, unit }) {
  const [hover, setHover] = useState(null); // index of the hovered point, or null
  const values = points.map(p => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = (max - min) * 0.25 || Math.max(1, Math.abs(max) * 0.1) || 1;
  const yMin = min - pad, yMax = max + pad;
  const W = 400, H = 130, PAD_X = 8, PAD_Y = 12;
  const n = points.length;
  const xFor = (i) => (n === 1 ? W / 2 : PAD_X + (i / (n - 1)) * (W - PAD_X * 2));
  const yFor = (v) => PAD_Y + (1 - (v - yMin) / (yMax - yMin)) * (H - PAD_Y * 2);
  const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"} ${xFor(i).toFixed(1)} ${yFor(p.value).toFixed(1)}`).join(" ");
  const areaPath = `${linePath} L ${xFor(n - 1).toFixed(1)} ${H} L ${xFor(0).toFixed(1)} ${H} Z`;

  const hp = hover !== null ? points[hover] : null;
  let tipX, tipY, tipAbove;
  if (hp) {
    const boxW = 96, boxH = hp.status ? 46 : 32;
    tipX = Math.max(2, Math.min(W - boxW - 2, xFor(hover) - boxW / 2));
    tipAbove = yFor(hp.value) - boxH - 10 >= 2;
    tipY = tipAbove ? yFor(hp.value) - boxH - 10 : yFor(hp.value) + 10;
  }

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: 120, display: "block", overflow: "visible" }}>
      <path d={areaPath} fill="var(--color-primary-light)" stroke="none" />
      <path d={linePath} fill="none" stroke="var(--color-primary)" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />
      {points.map((p, i) => {
        const outOfRange = p.status === "high" || p.status === "low";
        return (
          <g key={i}>
            <circle cx={xFor(i)} cy={yFor(p.value)} r={outOfRange ? 5 : 4}
              fill={outOfRange ? "var(--color-error)" : "var(--color-primary)"}
              stroke="var(--color-bg)" strokeWidth="2" />
            {/* Larger invisible hit target — the visible dot is too small to
                hover reliably, especially on the smaller sizes this card
                renders at (side-by-side with the Insight panel). */}
            <circle cx={xFor(i)} cy={yFor(p.value)} r={11} fill="transparent"
              onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(v => (v === i ? null : v))}
              style={{ cursor: "pointer" }} />
          </g>
        );
      })}
      {hp && (
        <g pointerEvents="none">
          <rect x={tipX} y={tipY} width={96} height={hp.status ? 46 : 32} rx={7} fill="var(--color-text)" opacity="0.94" />
          <text x={tipX + 48} y={tipY + 14} textAnchor="middle" fontSize="9.5" fontWeight="700" fill="#fff">{fullDate(hp.date)}</text>
          <text x={tipX + 48} y={tipY + 27} textAnchor="middle" fontSize="11" fill="#fff">{hp.value}{unit}</text>
          {hp.status && (
            <text x={tipX + 48} y={tipY + 39} textAnchor="middle" fontSize="9.5"
              fill={hp.status === "normal" ? "#8fe0c2" : "#ffb3b3"}>{STATUS_WORD[hp.status]}</text>
          )}
        </g>
      )}
    </svg>
  );
}

export default function TrendSpotlightCard({ patientAwpid, range }) {
  const { data } = useApi(API_ENDPOINTS.PORTAL.HEALTH_INSIGHTS_TRENDS, {
    params: { range, ...(patientAwpid ? { patient_awpid: patientAwpid } : {}) },
  });
  const parameters = data?.parameters || [];
  if (!parameters.length) return null;

  const p = parameters[0];
  const points = p.points;
  const first = points[0], last = points[points.length - 1];
  const delta = last.value - first.value;
  const dirWord = delta > 0 ? "increased" : delta < 0 ? "decreased" : "stayed about the same";
  const concerning = (p.concern === "higher_is_concern" && delta > 0) || (p.concern === "lower_is_concern" && delta < 0);
  const Icon = delta >= 0 ? TrendingUp : TrendingDown;

  return (
    <div className="card" style={{ padding: "18px 20px" }}>
      <div className="dot-label dot-label--blue" style={{ marginBottom: 2 }}>{p.label} Trend</div>
      <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 14 }}>
        Your {p.label} levels over time
      </div>

      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        <div style={{ flex: "1 1 200px", minWidth: 0 }}>
          <TrendChart points={points} unit={p.unit} />
          <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6 }}>
            {points.map((pt, i) => (
              <span key={i} style={{ fontSize: 10, color: "var(--color-text-muted)" }}>{shortDate(pt.date)}</span>
            ))}
          </div>
        </div>

        <div style={{ flex: "1 1 160px", display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{
            display: "flex", gap: 7, alignItems: "flex-start", padding: "9px 11px", borderRadius: 9,
            background: concerning ? "var(--color-warning-light)" : "var(--color-primary-light)",
          }}>
            <Icon size={14} style={{ flexShrink: 0, marginTop: 1, color: concerning ? "var(--color-warning)" : "var(--color-primary)" }} />
            <span style={{ fontSize: 11.5, lineHeight: 1.5 }}>
              <strong style={{ color: concerning ? "var(--color-warning)" : "var(--color-primary)" }}>Insight</strong><br />
              Your {p.label} has {dirWord} from {first.value}{p.unit} to {last.value}{p.unit} across the last {points.length} available reports.
            </span>
          </div>
          <div style={{
            fontSize: 10.5, lineHeight: 1.5, color: "var(--color-text-muted)",
            padding: "9px 11px", borderRadius: 9, border: "1px solid var(--color-border)",
          }}>
            This is based on the reports available in your documents. For medical advice, please consult your doctor.
          </div>
        </div>
      </div>
    </div>
  );
}
