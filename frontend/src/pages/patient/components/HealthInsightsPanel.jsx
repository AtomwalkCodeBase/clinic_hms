/**
 * pages/patient/components/HealthInsightsPanel.jsx
 * ---------------------------------------------------
 * Health Insights dashboard, embedded (collapsed by default) in
 * MyReportsPage.jsx — the frontend PortalHealthInsightsView,
 * PortalLabTrendsView and PortalHealthInsightNarrativeView never had a
 * home in the app before this.
 *
 * Overview tab: summary counts, flagged value changes since the last
 * reading of the same test, checkup reminders, reports needing review,
 * a report-type distribution, and a couple of plain-fact pattern notes.
 *
 * Trends tab: per-analyte time series (PortalLabTrendsView) with a picker,
 * a small real SVG line chart (no chart library — one parameter, a
 * handful of points, doesn't need one), and a patient-triggered "AI
 * summary" over the selected trend (PortalHealthInsightNarrativeView) —
 * explicitly a button press, never fetched on page load.
 */
import { useEffect, useState } from "react";
import { TrendingUp, TrendingDown, AlertCircle, CalendarClock, FileWarning, Sparkles, ChevronDown } from "lucide-react";
import { useApi } from "../../../hooks/useApi";
import apiClient from "../../../services/api.client";
import API_ENDPOINTS from "../../../config/api.config";
import { useToast } from "../../../hooks/useToast";

const RANGES = [
  { id: "3m", label: "3M" },
  { id: "6m", label: "6M" },
  { id: "12m", label: "12M" },
  { id: "all", label: "All" },
];

const STATUS_COLOR = {
  high: "#B91C1C", low: "#B45309", normal: "#047857",
};

function StatCard({ label, value }) {
  return (
    <div style={{
      flex: "1 1 120px", borderRadius: 10, border: "1px solid var(--color-border)",
      background: "var(--color-bg)", padding: "10px 14px",
    }}>
      <div style={{ fontFamily: "var(--font-display)", fontSize: 22, fontWeight: 700, color: "var(--color-text)" }}>
        {value ?? "—"}
      </div>
      <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>{label}</div>
    </div>
  );
}

function ListBlock({ icon: Icon, title, children, empty }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
        <Icon size={14} color="var(--color-text-muted)" />
        <span style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text)" }}>{title}</span>
      </div>
      {empty ? (
        <div style={{ fontSize: 12, color: "var(--color-text-muted)", fontStyle: "italic" }}>{empty}</div>
      ) : (
        <div style={{ display: "grid", gap: 6 }}>{children}</div>
      )}
    </div>
  );
}

function VariationRow({ f, onOpenDocument }) {
  const Arrow = f.direction === "up" ? TrendingUp : TrendingDown;
  const color = f.concern === "neutral" ? "var(--color-text-muted)" : STATUS_COLOR.high;
  return (
    <div
      onClick={() => onOpenDocument?.(f.document_id)}
      style={{
        display: "flex", gap: 8, alignItems: "flex-start", fontSize: 12.5,
        padding: "8px 10px", borderRadius: 8, background: "var(--color-bg)",
        cursor: onOpenDocument ? "pointer" : "default",
      }}
    >
      <Arrow size={14} color={color} style={{ marginTop: 1, flexShrink: 0 }} />
      <span style={{ color: "var(--color-text)" }}>{f.message}</span>
    </div>
  );
}

// A simple, real SVG line chart — one series, a handful of points, doesn't
// need a charting library. Reference range (when the latest point carries
// one) is drawn as a shaded band behind the line.
function TrendChart({ param }) {
  const [hoverIdx, setHoverIdx] = useState(null);
  const points = param.points || [];
  if (points.length < 2) return null;
  const W = 640, H = 200, PAD = 36;
  const values = points.map(p => p.value);
  const refLows = points.map(p => p.reference_low).filter(v => v != null);
  const refHighs = points.map(p => p.reference_high).filter(v => v != null);
  const yMin = Math.min(...values, ...refLows, 0.95 * Math.min(...values));
  const yMax = Math.max(...values, ...refHighs, 1.05 * Math.max(...values));
  const span = yMax - yMin || 1;
  const x = i => PAD + (i / (points.length - 1)) * (W - PAD * 2);
  const y = v => H - PAD - ((v - yMin) / span) * (H - PAD * 2);

  const last = points[points.length - 1];
  const hovered = hoverIdx != null ? points[hoverIdx] : null;

  const line = points.map((p, i) => `${i === 0 ? "M" : "L"} ${x(i)} ${y(p.value)}`).join(" ");
  const bandTop = refHighs.length ? y(Math.max(...refHighs)) : null;
  const bandBottom = refLows.length ? y(Math.min(...refLows)) : null;

  return (
    <div style={{ position: "relative" }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }}>
        {bandTop != null && bandBottom != null && (
          <rect x={PAD} y={bandTop} width={W - PAD * 2} height={Math.max(0, bandBottom - bandTop)}
            fill="var(--color-success-light)" opacity={0.5} />
        )}
        <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="var(--color-border)" strokeWidth={1} />
        <text x={2} y={y(yMax) + 4} fontSize={9} fill="var(--color-text-muted)">{Math.round(yMax * 10) / 10}</text>
        <text x={2} y={y(yMin) + 4} fontSize={9} fill="var(--color-text-muted)">{Math.round(yMin * 10) / 10}</text>
        <path d={line} fill="none" stroke="var(--color-primary)" strokeWidth={2} />
        {points.map((p, i) => (
          <circle key={i} cx={x(i)} cy={y(p.value)} r={hoverIdx === i ? 5 : 3.5}
            fill={STATUS_COLOR[p.status] || "var(--color-primary)"}
            stroke="#fff" strokeWidth={1}
            onMouseEnter={() => setHoverIdx(i)} onMouseLeave={() => setHoverIdx(null)}
            style={{ cursor: "pointer" }}
          />
        ))}
      </svg>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--color-text-muted)", padding: "0 4px" }}>
        <span>{points[0].date}</span>
        <span>{points[points.length - 1].date}</span>
      </div>
      <div style={{ marginTop: 6, fontSize: 12.5, color: "var(--color-text)" }}>
        {hovered ? (
          <span>
            <b>{hovered.value} {param.unit}</b> on {hovered.date}
            {hovered.status && hovered.status !== "normal" && (
              <span style={{ color: STATUS_COLOR[hovered.status], fontWeight: 700, textTransform: "capitalize" }}> · {hovered.status}</span>
            )}
          </span>
        ) : (
          <span>
            Latest: <b>{last.value} {param.unit}</b>
            {last.status && last.status !== "normal" && (
              <span style={{ color: STATUS_COLOR[last.status], fontWeight: 700, textTransform: "capitalize" }}> · {last.status}</span>
            )}
          </span>
        )}
      </div>
    </div>
  );
}

function TrendsTab({ patientAwpid, range }) {
  const params = patientAwpid ? { patient_awpid: patientAwpid, range } : { range };
  const { data, isLoading } = useApi(API_ENDPOINTS.PORTAL.HEALTH_INSIGHTS_TRENDS, { params });
  const parameters = data?.parameters || [];
  const [slug, setSlug] = useState("");
  const { toastApiError } = useToast();
  const [narrative, setNarrative] = useState(null);
  const [narrating, setNarrating] = useState(false);

  useEffect(() => {
    if (parameters.length && !parameters.some(p => p.slug === slug)) {
      setSlug(parameters[0].slug);
      setNarrative(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const selected = parameters.find(p => p.slug === slug) || null;

  async function generateNarrative() {
    setNarrating(true);
    setNarrative(null);
    try {
      const payload = { parameter_slug: slug, range, ...(patientAwpid ? { patient_awpid: patientAwpid } : {}) };
      const res = await apiClient.post(API_ENDPOINTS.PORTAL.HEALTH_INSIGHTS_NARRATE, payload);
      const d = res.data?.data || res.data;
      setNarrative(d?.narrative || null);
    } catch (err) {
      toastApiError(err, "Could not generate a summary right now.");
    } finally {
      setNarrating(false);
    }
  }

  if (isLoading) return <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>Loading trends…</div>;
  if (!parameters.length) {
    return (
      <div style={{ fontSize: 12, color: "var(--color-text-muted)", fontStyle: "italic" }}>
        Not enough repeated test results yet to show a trend — this fills in once the same test has been
        taken at least twice in this range.
      </div>
    );
  }

  return (
    <div>
      <div style={{ position: "relative", display: "inline-block", marginBottom: 14 }}>
        <select
          value={slug}
          onChange={e => { setSlug(e.target.value); setNarrative(null); }}
          className="form-input"
          style={{ fontSize: 13, paddingRight: 28, appearance: "none" }}
        >
          {parameters.map(p => (
            <option key={p.slug} value={p.slug}>{p.label} ({p.points.length} readings)</option>
          ))}
        </select>
        <ChevronDown size={14} style={{ position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)", pointerEvents: "none", color: "var(--color-text-muted)" }} />
      </div>

      {selected && <TrendChart param={selected} />}

      <div style={{ marginTop: 14 }}>
        <button
          type="button" onClick={generateNarrative} disabled={narrating}
          className="btn-outline" style={{ fontSize: 12, display: "inline-flex", alignItems: "center", gap: 6 }}
        >
          <Sparkles size={13} /> {narrating ? "Thinking…" : "See what this trend means"}
        </button>
        {narrative !== null && (
          <div style={{
            marginTop: 10, fontSize: 12.5, lineHeight: 1.6, color: "var(--color-text)",
            background: "var(--color-bg)", border: "1px solid var(--color-border)", borderRadius: 8, padding: "10px 12px",
          }}>
            {narrative || "Couldn't generate a summary for this right now — try again in a moment."}
          </div>
        )}
      </div>
    </div>
  );
}

export default function HealthInsightsPanel({ patientAwpid, onOpenDocument }) {
  const [range, setRange] = useState("12m");
  const [tab, setTab] = useState("overview");
  const params = patientAwpid ? { patient_awpid: patientAwpid, range } : { range };
  const { data, isLoading } = useApi(API_ENDPOINTS.PORTAL.HEALTH_INSIGHTS, { params });

  const maxPanelCount = Math.max(1, ...(data?.report_distribution || []).map(p => p.count));

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 10, marginBottom: 14 }}>
        <div style={{ display: "flex", gap: 4 }}>
          {[["overview", "Overview"], ["trends", "Trends"]].map(([id, label]) => (
            <button key={id} type="button" onClick={() => setTab(id)}
              style={{
                padding: "6px 14px", fontSize: 12.5, fontWeight: 600, borderRadius: 8, border: "none", cursor: "pointer",
                background: tab === id ? "var(--color-primary)" : "transparent",
                color: tab === id ? "#fff" : "var(--color-text-secondary)",
              }}>
              {label}
            </button>
          ))}
        </div>
        <div style={{ display: "flex", border: "1px solid var(--color-border)", borderRadius: 8, overflow: "hidden" }}>
          {RANGES.map(r => (
            <button key={r.id} type="button" onClick={() => setRange(r.id)}
              style={{
                padding: "5px 10px", fontSize: 11.5, fontWeight: 600, border: "none", cursor: "pointer",
                background: range === r.id ? "var(--color-primary)" : "transparent",
                color: range === r.id ? "#fff" : "var(--color-text-secondary)",
              }}>
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {tab === "trends" ? (
        <TrendsTab patientAwpid={patientAwpid} range={range} />
      ) : isLoading ? (
        <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>Loading insights…</div>
      ) : !data || data.total_documents === 0 ? (
        <div style={{ fontSize: 12, color: "var(--color-text-muted)", fontStyle: "italic" }}>
          Nothing to summarize yet for this range.
        </div>
      ) : (
        <div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginBottom: 18 }}>
            <StatCard label="Documents" value={data.total_documents} />
            <StatCard label="Lab Reports" value={data.total_reports} />
            <StatCard label="Prescriptions" value={data.total_prescriptions} />
            <StatCard label="Most Common" value={data.most_common_panel || "—"} />
          </div>

          {data.flagged_variations?.length > 0 && (
            <ListBlock icon={AlertCircle} title="Notable Changes Since Last Reading">
              {data.flagged_variations.map((f, i) => (
                <VariationRow key={i} f={f} onOpenDocument={onOpenDocument} />
              ))}
            </ListBlock>
          )}

          {data.checkup_reminders?.length > 0 && (
            <ListBlock icon={CalendarClock} title="Checkup Reminders">
              {data.checkup_reminders.map((r, i) => (
                <div key={i} style={{ fontSize: 12.5, padding: "8px 10px", borderRadius: 8, background: "var(--color-bg)", color: "var(--color-text)" }}>
                  {r.message}
                </div>
              ))}
            </ListBlock>
          )}

          {data.reports_needing_review?.length > 0 && (
            <ListBlock icon={FileWarning} title="Reports Needing Review">
              {data.reports_needing_review.map(r => (
                <div key={r.id} onClick={() => onOpenDocument?.(r.id)}
                  style={{
                    fontSize: 12.5, padding: "8px 10px", borderRadius: 8, background: "var(--color-bg)",
                    display: "flex", justifyContent: "space-between", gap: 8,
                    cursor: onOpenDocument ? "pointer" : "default",
                  }}>
                  <span style={{ color: "var(--color-text)", fontWeight: 600 }}>{r.title}</span>
                  <span style={{ color: "var(--color-text-muted)" }}>{r.reason}</span>
                </div>
              ))}
            </ListBlock>
          )}

          {data.report_distribution?.length > 0 && (
            <ListBlock icon={FileWarning} title="Report Types">
              {data.report_distribution.map(p => (
                <div key={p.slug} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
                  <span style={{ width: 110, flexShrink: 0, color: "var(--color-text)" }}>{p.label}</span>
                  <div style={{ flex: 1, height: 8, borderRadius: 4, background: "var(--color-border)", overflow: "hidden" }}>
                    <div style={{ width: `${(p.count / maxPanelCount) * 100}%`, height: "100%", background: "var(--color-primary)" }} />
                  </div>
                  <span style={{ width: 20, textAlign: "right", color: "var(--color-text-muted)" }}>{p.count}</span>
                </div>
              ))}
            </ListBlock>
          )}

          {data.pattern_insights?.length > 0 && (
            <div style={{ fontSize: 12, color: "var(--color-text-muted)", display: "grid", gap: 4 }}>
              {data.pattern_insights.map((s, i) => <div key={i}>• {s}</div>)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
