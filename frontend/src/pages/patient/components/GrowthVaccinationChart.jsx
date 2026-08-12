/**
 * pages/patient/components/GrowthVaccinationChart.jsx
 * -----------------------------------------------------
 * Real, production Growth + Vaccination chart for the patient portal.
 *
 * Data sources (both already fetched by RecordsPage.jsx from live APIs,
 * passed down as props — no mock numbers anywhere in this file):
 *   - `growth`   → GET /api/v1/portal/growth/       (PortalGrowthView)
 *                  series: [{ date, height_cm, weight_kg, source }]
 *   - `roadmap`  → GET /api/v1/portal/vaccinations/  (.roadmap, build_roadmap())
 *                  items: { vaccine_name, scheduled_label, administered_date,
 *                           due_date, status, timing, record_id, has_certificate, ... }
 *
 * Honesty constraints carried over from the backend (do not relax these
 * client-side just to make the chart look richer):
 *   - No percentile/reference curves — PortalGrowthView returns
 *     percentile_available: false on purpose ("a made-up percentile band
 *     would be worse than not showing one"). Nothing here draws one.
 *   - No head-circumference metric — SharedVital has no such field.
 *   - Growth measurements have no uploaded document attached in this system
 *     (only vaccination records do). Clicking a growth point opens a detail
 *     card (date / value / source), NOT a fake "view document" link.
 *     Clicking a vaccination marker that has a real certificate on file
 *     (has_certificate && record_id) opens the actual uploaded file via the
 *     same endpoint the Vaccination Timeline's "View Certificate" uses.
 *
 * Four real chart types (Story / Line / Bar / Area) across two real metrics
 * (Height / Weight) — no fabricated third metric.
 */
import { useMemo, useState } from "react";
import apiClient from "../../../services/api.client";
import API_ENDPOINTS from "../../../config/api.config";
import { useToast } from "../../../hooks/useToast";

const METRICS = [
  { id: "height_cm", label: "Height", unit: "cm", color: "#1B5E43" },
  { id: "weight_kg", label: "Weight", unit: "kg", color: "#2E6FA3" },
];

const CHART_TYPES = [
  { id: "story", label: "Growth + Vaccine Story" },
  { id: "line",  label: "Line" },
  { id: "bar",   label: "Bar" },
  { id: "area",  label: "Area" },
];

// Mirrors vaxBucket() in RecordsPage.jsx exactly (kept local — that helper
// isn't exported) so marker colors on this chart always agree with the
// pill colors on the timeline below it.
function vaxBucket(item) {
  const status = item.status;
  if (status === "completed" || status === "declined") return "Completed";
  if (status === "pending_review" || status === "rejected") return "Needs Review";
  if (status === "ordered") return "Needs Review";
  if (status === "unknown") {
    return item.timing === "due_now" || item.timing === "past_window" ? "Needs Review" : "Upcoming";
  }
  return "Upcoming";
}

const BUCKET_COLOR = {
  Completed: "var(--color-success)",
  Upcoming: "var(--color-warning)",
  "Needs Review": "#6B3FA0",
};

function daysBetween(a, b) {
  return Math.round((new Date(b) - new Date(a)) / 86400000);
}

function formatAge(days) {
  if (days == null || days < 0) return "";
  if (days < 60) return `${days}d old`;
  const months = days / 30.44;
  if (months < 24) return `${months < 3 ? months.toFixed(1) : Math.round(months)}mo old`;
  return `${(months / 12).toFixed(1)}yr old`;
}

function formatDate(dateStr) {
  if (!dateStr) return "";
  return new Date(dateStr).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

const SOURCE_LABEL = { clinic: "Recorded during a hospital visit", home: "Self-reported" };

export default function GrowthVaccinationChart({ growth, growthLoading, roadmap, roadmapLoading }) {
  const { toastApiError } = useToast();
  const [metric, setMetric] = useState("height_cm");
  const [chartType, setChartType] = useState("story");
  const [detail, setDetail] = useState(null);
  const [certLoading, setCertLoading] = useState(false);

  const dob = growth?.date_of_birth;
  const metricDef = METRICS.find(m => m.id === metric);

  const growthPoints = useMemo(() => {
    const series = growth?.series || [];
    return series
      .map(p => ({
        date: p.date,
        value: p[metric],
        source: p.source,
        ageDays: dob ? daysBetween(dob, p.date) : null,
      }))
      .filter(p => p.value != null);
  }, [growth, metric, dob]);

  const vaxMarkers = useMemo(() => {
    if (!dob) return [];
    return (roadmap || [])
      .map(item => {
        const eventDate = item.administered_date || item.due_date;
        if (!eventDate) return null;
        return { ...item, eventDate, ageDays: daysBetween(dob, eventDate), bucket: vaxBucket(item) };
      })
      .filter(Boolean)
      .sort((a, b) => a.ageDays - b.ageDays);
  }, [roadmap, dob]);

  async function viewCertificate(recordId) {
    setCertLoading(true);
    try {
      const res = await apiClient.get(API_ENDPOINTS.PORTAL.VACCINATION_FILE(recordId));
      const data = res.data?.data || res.data;
      if (data?.file_data) {
        const win = window.open();
        if (win) win.location.href = data.file_data;
      } else {
        toastApiError(null, "No file is attached to that record.");
      }
    } catch (err) {
      toastApiError(err, "Could not load the certificate.");
    } finally {
      setCertLoading(false);
    }
  }

  function clickGrowthPoint(p) {
    setDetail({
      kind: "growth",
      title: `${metricDef.label}: ${p.value} ${metricDef.unit}`,
      lines: [
        formatDate(p.date) + (p.ageDays != null ? ` · ${formatAge(p.ageDays)}` : ""),
        SOURCE_LABEL[p.source] || null,
      ].filter(Boolean),
    });
  }

  function clickVaxMarker(item) {
    setDetail({
      kind: "vax",
      title: item.vaccine_name,
      lines: [
        `${item.bucket}${item.scheduled_label ? ` · ${item.scheduled_label}` : ""}`,
        formatDate(item.eventDate) + (item.ageDays != null ? ` · ${formatAge(item.ageDays)}` : ""),
      ],
      recordId: item.record_id,
      hasCertificate: !!item.has_certificate,
    });
  }

  const loading = growthLoading || roadmapLoading;
  const hasAnyData = growthPoints.length > 0 || vaxMarkers.length > 0;

  return (
    <div className="card" style={{ padding: "16px 20px", marginBottom: 20 }}>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 14 }}>
        <div style={{ fontFamily: "var(--font-display)", fontWeight: 600, fontSize: 15 }}>
          Growth &amp; Vaccination Chart
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <SegmentedControl options={METRICS.map(m => ({ id: m.id, label: m.label }))} value={metric} onChange={setMetric} />
          <SegmentedControl options={CHART_TYPES} value={chartType} onChange={setChartType} />
        </div>
      </div>

      {loading ? (
        <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>Loading…</div>
      ) : !hasAnyData ? (
        <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
          No growth measurements or vaccination records yet.
        </div>
      ) : (
        <>
          {chartType === "story" ? (
            <StoryChart
              points={growthPoints}
              markers={vaxMarkers}
              metricDef={metricDef}
              onPointClick={clickGrowthPoint}
              onMarkerClick={clickVaxMarker}
            />
          ) : (
            <SimpleChart
              type={chartType}
              points={growthPoints}
              metricDef={metricDef}
              onPointClick={clickGrowthPoint}
            />
          )}

          {chartType === "story" && vaxMarkers.length > 0 && (
            <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 10, fontSize: 11 }}>
              {Object.entries(BUCKET_COLOR).map(([label, color]) => (
                <span key={label} style={{ display: "inline-flex", alignItems: "center", gap: 5, color: "var(--color-text-muted)" }}>
                  <span style={{ width: 8, height: 8, borderRadius: "50%", background: color, display: "inline-block" }} />
                  {label}
                </span>
              ))}
            </div>
          )}

          {detail && (
            <div style={{
              marginTop: 14, padding: "10px 14px", borderRadius: 10,
              background: "var(--color-surface-alt, #F5F1E9)", border: "1px solid var(--color-border)",
              display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap",
            }}>
              <div>
                <div style={{ fontWeight: 700, fontSize: 13 }}>{detail.title}</div>
                {detail.lines.map((l, i) => (
                  <div key={i} style={{ fontSize: 11, color: "var(--color-text-muted)" }}>{l}</div>
                ))}
                {detail.kind === "vax" && !detail.hasCertificate && (
                  <div style={{ fontSize: 11, color: "var(--color-text-muted)", fontStyle: "italic", marginTop: 2 }}>
                    No document on file for this record.
                  </div>
                )}
              </div>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                {detail.kind === "vax" && detail.hasCertificate && detail.recordId && (
                  <button
                    className="btn-outline"
                    disabled={certLoading}
                    onClick={() => viewCertificate(detail.recordId)}
                    style={{ padding: "5px 12px", fontSize: 11 }}
                  >
                    {certLoading ? "Loading…" : "View Certificate"}
                  </button>
                )}
                <button
                  onClick={() => setDetail(null)}
                  style={{ border: "none", background: "none", color: "var(--color-text-muted)", cursor: "pointer", fontSize: 16, lineHeight: 1 }}
                  aria-label="Close"
                >
                  ×
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function SegmentedControl({ options, value, onChange }) {
  return (
    <div style={{ display: "inline-flex", background: "var(--color-surface-alt, #F5F1E9)", borderRadius: 8, padding: 3, gap: 2 }}>
      {options.map(o => {
        const active = o.id === value;
        return (
          <button
            key={o.id}
            onClick={() => onChange(o.id)}
            style={{
              padding: "5px 10px", fontSize: 11, fontWeight: active ? 700 : 500,
              border: "none", borderRadius: 6, cursor: "pointer", whiteSpace: "nowrap",
              background: active ? "var(--color-primary)" : "transparent",
              color: active ? "#fff" : "var(--color-text-muted)",
              transition: "all 0.15s ease",
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

// "Story" chart — the one that answers "tell the story of how healthy the
// child is for that age": the selected metric plotted against real AGE
// (not just chronological order), with vaccination events overlaid in a
// marker lane on the same age axis so a parent can see growth and
// vaccination timing together. Age positioning is computed from real
// date_of_birth + real event dates — nothing plotted here is estimated.
function StoryChart({ points, markers, metricDef, onPointClick, onMarkerClick }) {
  if (points.length === 0 && markers.length === 0) return null;

  const width = 680, chartH = 170, laneH = 46, padX = 34, padY = 14;
  const totalH = chartH + laneH + 20;

  const ages = [...points.map(p => p.ageDays), ...markers.map(m => m.ageDays)].filter(a => a != null);
  const ageMin = Math.min(...ages, 0);
  const ageMax = Math.max(...ages, 1);
  const ageRange = ageMax - ageMin || 1;

  const x = age => padX + ((age - ageMin) / ageRange) * (width - padX * 2);

  let y = () => chartH / 2;
  if (points.length > 0) {
    const values = points.map(p => p.value);
    const vMin = Math.min(...values);
    const vMax = Math.max(...values);
    const vRange = vMax - vMin || 1;
    y = value => padY + (chartH - padY * 2) * (1 - (value - vMin) / vRange);
  }

  const sorted = points.length > 1 ? [...points].sort((a, b) => a.ageDays - b.ageDays) : points;
  const linePath = sorted.length > 1
    ? sorted.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.ageDays).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ")
    : "";

  return (
    <svg viewBox={`0 0 ${width} ${totalH}`} width="100%" height={totalH} preserveAspectRatio="xMidYMid meet">
      {/* growth line */}
      {points.length === 0 ? (
        <text x={width / 2} y={chartH / 2} fontSize={11} fill="var(--color-text-muted)" textAnchor="middle">
          No {metricDef.label.toLowerCase()} measurements recorded yet.
        </text>
      ) : (
        <>
          {sorted.length > 1 && <path d={linePath} fill="none" stroke={metricDef.color} strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" />}
          {sorted.map((p, i) => (
            <circle
              key={i} cx={x(p.ageDays)} cy={y(p.value)} r={5}
              fill={metricDef.color} stroke="#fff" strokeWidth={1.5}
              style={{ cursor: "pointer" }}
              onClick={() => onPointClick(p)}
            >
              <title>{`${p.value} ${metricDef.unit} · ${formatDate(p.date)}`}</title>
            </circle>
          ))}
        </>
      )}

      {/* separator */}
      <line x1={0} y1={chartH + 6} x2={width} y2={chartH + 6} stroke="var(--color-border)" strokeWidth={1} />

      {/* vaccination marker lane */}
      {markers.map((m, i) => {
        const mx = x(m.ageDays);
        const color = BUCKET_COLOR[m.bucket];
        return (
          <g key={i} style={{ cursor: "pointer" }} onClick={() => onMarkerClick(m)}>
            <line x1={mx} y1={chartH + 10} x2={mx} y2={chartH + laneH - 4} stroke={color} strokeWidth={1.4} strokeDasharray="2,2" opacity={0.6} />
            <circle cx={mx} cy={chartH + laneH - 4} r={5} fill={color}>
              <title>{`${m.vaccine_name} · ${m.bucket} · ${formatDate(m.eventDate)}`}</title>
            </circle>
          </g>
        );
      })}

      {ages.length > 0 && (
        <>
          <text x={padX} y={totalH - 2} fontSize={9} fill="var(--color-text-muted)" textAnchor="start">{formatAge(ageMin)}</text>
          <text x={width - padX} y={totalH - 2} fontSize={9} fill="var(--color-text-muted)" textAnchor="end">{formatAge(ageMax)}</text>
        </>
      )}
    </svg>
  );
}

// Simple chronological chart of the selected metric alone — Line / Bar /
// Area variants, each with clickable points that open the same honest
// detail card (date / value / source, no fabricated document link).
function SimpleChart({ type, points, metricDef, onPointClick }) {
  if (points.length === 0) {
    return (
      <div style={{ padding: "30px 0", textAlign: "center", fontSize: 12, color: "var(--color-text-muted)" }}>
        No {metricDef.label.toLowerCase()} measurements recorded yet.
      </div>
    );
  }

  const width = 680, height = 170, padX = 24, padY = 16;
  const values = points.map(p => p.value);
  const min = Math.min(...values, 0);
  const max = Math.max(...values);
  const range = max - min || 1;
  const stepX = points.length > 1 ? (width - padX * 2) / (points.length - 1) : 0;

  const coords = points.map((p, i) => ({
    ...p,
    x: padX + i * stepX,
    y: padY + (height - padY * 2) * (1 - (p.value - min) / range),
  }));

  const linePath = coords.length > 1 ? coords.map((c, i) => `${i === 0 ? "M" : "L"}${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(" ") : "";
  const baseline = height - padY;
  const areaPath = coords.length > 1
    ? `${linePath} L${coords[coords.length - 1].x.toFixed(1)},${baseline} L${coords[0].x.toFixed(1)},${baseline} Z`
    : "";
  const barWidth = points.length > 1 ? Math.min(28, stepX * 0.5) : 28;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} preserveAspectRatio="xMidYMid meet">
      {type === "bar" && coords.map((c, i) => (
        <rect
          key={i} x={c.x - barWidth / 2} y={c.y} width={barWidth} height={Math.max(baseline - c.y, 0)}
          fill={metricDef.color} opacity={0.85} rx={3}
          style={{ cursor: "pointer" }}
          onClick={() => onPointClick(c)}
        >
          <title>{`${c.value} ${metricDef.unit} · ${formatDate(c.date)}`}</title>
        </rect>
      ))}

      {type === "area" && coords.length > 1 && <path d={areaPath} fill={metricDef.color} opacity={0.18} />}
      {(type === "line" || type === "area") && coords.length > 1 && (
        <path d={linePath} fill="none" stroke={metricDef.color} strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" />
      )}
      {(type === "line" || type === "area") && coords.map((c, i) => (
        <circle
          key={i} cx={c.x} cy={c.y} r={5} fill={metricDef.color} stroke="#fff" strokeWidth={1.5}
          style={{ cursor: "pointer" }}
          onClick={() => onPointClick(c)}
        >
          <title>{`${c.value} ${metricDef.unit} · ${formatDate(c.date)}`}</title>
        </circle>
      ))}

      <text x={coords[0].x} y={height - 2} fontSize={9} fill="var(--color-text-muted)" textAnchor="start">
        {formatDate(coords[0].date)}
      </text>
      {coords.length > 1 && (
        <text x={coords[coords.length - 1].x} y={height - 2} fontSize={9} fill="var(--color-text-muted)" textAnchor="end">
          {formatDate(coords[coords.length - 1].date)}
        </text>
      )}
    </svg>
  );
}
