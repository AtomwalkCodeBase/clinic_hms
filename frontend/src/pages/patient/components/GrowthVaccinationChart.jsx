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
 *     (only vaccination records do). Hovering/clicking a growth point shows
 *     a detail card (date / value / age / source), NOT a fake "view
 *     document" link. Hovering a vaccination marker shows the same kind of
 *     card; clicking one that has a real certificate on file
 *     (has_certificate && record_id) opens the actual uploaded file via the
 *     same endpoint the Vaccination Timeline's "View Certificate" uses.
 *
 * Readability pass (this revision): every chart now draws real axis
 * gridlines with numeric labels (so a value can be read off the chart
 * without guessing), a "Latest" stat readout with a trend arrow, a
 * plain-English caption, and a styled hover tooltip on every point/marker
 * (not the browser's native <title> tooltip, which nobody notices) — so the
 * chart is legible on first glance instead of requiring a click to
 * understand what a dot means.
 */
import { useMemo, useState } from "react";
import apiClient from "../../../services/api.client";
import API_ENDPOINTS from "../../../config/api.config";
import { useToast } from "../../../hooks/useToast";

const METRICS = [
  { id: "height_cm", label: "Height", unit: "cm", color: "#1B5E43", light: "#E4F0EA" },
  { id: "weight_kg", label: "Weight", unit: "kg", color: "#2E6FA3", light: "#E3EDF5" },
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
  Completed: "#1B8A5A",
  Upcoming: "#C9950A",
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

function formatDateShort(dateStr) {
  if (!dateStr) return "";
  return new Date(dateStr).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

const SOURCE_LABEL = { clinic: "Recorded during a hospital visit", home: "Self-reported" };

// Evenly-spaced axis ticks between min/max — not D3-style "nice numbers",
// just readable rounded steps, which is all a 4-tick reference axis needs.
function makeTicks(min, max, count = 4) {
  if (min === max) return [min];
  const step = (max - min) / (count - 1);
  return Array.from({ length: count }, (_, i) => min + step * i);
}

function roundTo(v, decimals) {
  const f = Math.pow(10, decimals);
  return Math.round(v * f) / f;
}

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

  const latest = growthPoints.length ? growthPoints[growthPoints.length - 1] : null;
  const first = growthPoints.length ? growthPoints[0] : null;
  const trend = latest && first && growthPoints.length > 1
    ? (latest.value > first.value ? "up" : latest.value < first.value ? "down" : "flat")
    : null;

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

  const caption = chartType === "story"
    ? `${metricDef.label} over time, with vaccination visits marked below the line. Hover any point for the exact reading.`
    : `${metricDef.label} recorded at each visit. Hover a point for the exact date and value.`;

  return (
    <div className="card" style={{ padding: "18px 22px", marginBottom: 20 }}>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-start", justifyContent: "space-between", gap: 12, marginBottom: 4 }}>
        <div>
          <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 17 }}>
            Growth &amp; Vaccination Chart
          </div>
          <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 2, maxWidth: 480 }}>
            {caption}
          </div>
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <SegmentedControl options={METRICS.map(m => ({ id: m.id, label: m.label }))} value={metric} onChange={setMetric} />
          <SegmentedControl options={CHART_TYPES} value={chartType} onChange={setChartType} />
        </div>
      </div>

      {!loading && latest && (
        <div style={{ display: "flex", alignItems: "baseline", gap: 10, margin: "10px 0 4px" }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: 0.5 }}>
            Latest
          </span>
          <span style={{ fontSize: 22, fontWeight: 800, fontFamily: "var(--font-display)", color: metricDef.color }}>
            {latest.value} <span style={{ fontSize: 13, fontWeight: 600 }}>{metricDef.unit}</span>
          </span>
          {trend && (
            <span style={{
              display: "inline-flex", alignItems: "center", gap: 3, fontSize: 11, fontWeight: 700,
              padding: "2px 8px", borderRadius: 10,
              background: trend === "up" ? "#E4F0EA" : trend === "down" ? "#FBEAEA" : "#F0F0EE",
              color: trend === "up" ? "#1B8A5A" : trend === "down" ? "#B3392C" : "var(--color-text-muted)",
            }}>
              {trend === "up" ? "▲" : trend === "down" ? "▼" : "—"} since {formatDateShort(first.date)}
            </span>
          )}
          <span style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
            measured {formatDate(latest.date)}{latest.ageDays != null ? ` · ${formatAge(latest.ageDays)}` : ""}
          </span>
        </div>
      )}

      {loading ? (
        <div style={{ fontSize: 12, color: "var(--color-text-muted)", padding: "20px 0" }}>Loading…</div>
      ) : !hasAnyData ? (
        <div style={{ fontSize: 12, color: "var(--color-text-muted)", padding: "20px 0" }}>
          No growth measurements or vaccination records yet.
        </div>
      ) : (
        <>
          <div style={{ marginTop: 10 }}>
            {chartType === "story" ? (
              <StoryChart
                points={growthPoints}
                markers={vaxMarkers}
                metricDef={metricDef}
                onMarkerClick={clickVaxMarker}
              />
            ) : (
              <SimpleChart type={chartType} points={growthPoints} metricDef={metricDef} />
            )}
          </div>

          {chartType === "story" && vaxMarkers.length > 0 && (
            <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 8, fontSize: 11 }}>
              {Object.entries(BUCKET_COLOR).map(([label, color]) => (
                <span key={label} style={{ display: "inline-flex", alignItems: "center", gap: 5, color: "var(--color-text-muted)" }}>
                  <span style={{ width: 8, height: 8, borderRadius: "50%", background: color, display: "inline-block" }} />
                  {label}
                </span>
              ))}
              <span style={{ color: "var(--color-text-muted)", fontStyle: "italic" }}>Click a vaccination dot to open its certificate, if one's on file.</span>
            </div>
          )}

          {detail && (
            <div style={{
              marginTop: 14, padding: "10px 14px", borderRadius: 10,
              background: "#F5F1E9", border: "1px solid var(--color-border)",
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
    <div style={{ display: "inline-flex", background: "#F5F1E9", borderRadius: 8, padding: 3, gap: 2 }}>
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

// Floating tooltip, positioned in percentage-of-viewBox space so it lines
// up correctly regardless of the SVG's actual rendered pixel size (the
// wrapping div is always exactly as tall as the SVG and exactly as wide as
// its container, same as the SVG itself — see callers).
function ChartTooltip({ x, y, viewW, viewH, children, align = "top" }) {
  if (x == null) return null;
  const left = (x / viewW) * 100;
  const top = (y / viewH) * 100;
  return (
    <div style={{
      position: "absolute", left: `${left}%`, top: `${top}%`,
      transform: align === "top" ? "translate(-50%, -100%) translateY(-12px)" : "translate(-50%, 0) translateY(12px)",
      background: "#17281F", color: "#F4F1E8", padding: "9px 13px", borderRadius: 9,
      fontSize: 12, lineHeight: 1.55, whiteSpace: "nowrap", pointerEvents: "none",
      boxShadow: "0 8px 24px rgba(0,0,0,0.28)", zIndex: 30,
    }}>
      {children}
      <div style={{
        position: "absolute", left: "50%", transform: "translateX(-50%)",
        width: 0, height: 0, borderLeft: "6px solid transparent", borderRight: "6px solid transparent",
        ...(align === "top"
          ? { bottom: -6, borderTop: "6px solid #17281F" }
          : { top: -6, borderBottom: "6px solid #17281F" }),
      }} />
    </div>
  );
}

function TooltipValue({ label, value }) {
  return (
    <div>
      <span style={{ opacity: 0.65 }}>{label}: </span>
      <span style={{ fontWeight: 700 }}>{value}</span>
    </div>
  );
}

// "Story" chart — the one that answers "tell the story of how healthy the
// child is for that age": the selected metric plotted against real AGE
// (not just chronological order), with real Y-axis gridlines/labels so a
// value can be read off directly, and vaccination events overlaid in a
// marker lane on the same age axis. Age positioning is computed from real
// date_of_birth + real event dates — nothing plotted here is estimated.
function StoryChart({ points, markers, metricDef, onMarkerClick }) {
  const [hover, setHover] = useState(null); // { kind, x, y, ... }
  if (points.length === 0 && markers.length === 0) return null;

  // Narrower viewBox now that this card sits in the 2fr column next to
  // Recommended by Doctor instead of spanning the full page width — keeps
  // the chart filling its box instead of letterboxing inside a wide,
  // fixed-height SVG that's now rendered at a much narrower CSS width.
  const width = 560, chartH = 180, laneH = 46, padX = 52, padY = 16;
  const totalH = chartH + laneH + 26;

  const ages = [...points.map(p => p.ageDays), ...markers.map(m => m.ageDays)].filter(a => a != null);
  const ageMin = Math.min(...ages, 0);
  const ageMax = Math.max(...ages, 1);
  const ageRange = ageMax - ageMin || 1;

  const x = age => padX + ((age - ageMin) / ageRange) * (width - padX - 16);

  let yTicks = [];
  let y = () => chartH / 2;
  if (points.length > 0) {
    const values = points.map(p => p.value);
    const vMin = Math.min(...values);
    const vMax = Math.max(...values);
    const pad = (vMax - vMin) * 0.12 || vMax * 0.1 || 1;
    const lo = Math.max(0, vMin - pad);
    const hi = vMax + pad;
    y = value => padY + (chartH - padY * 2) * (1 - (value - lo) / (hi - lo || 1));
    yTicks = makeTicks(lo, hi, 4);
  }

  const sorted = points.length > 1 ? [...points].sort((a, b) => a.ageDays - b.ageDays) : points;
  const linePath = sorted.length > 1
    ? sorted.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.ageDays).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ")
    : "";
  const areaPath = sorted.length > 1
    ? `${linePath} L${x(sorted[sorted.length - 1].ageDays).toFixed(1)},${chartH - padY} L${x(sorted[0].ageDays).toFixed(1)},${chartH - padY} Z`
    : "";

  const ageTickCount = 5;
  const ageTicks = ages.length ? makeTicks(ageMin, ageMax, ageTickCount) : [];

  return (
    <div style={{ position: "relative" }}>
      <svg viewBox={`0 0 ${width} ${totalH}`} width="100%" height={totalH} preserveAspectRatio="xMidYMid meet">
        <defs>
          <linearGradient id="storyFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={metricDef.color} stopOpacity="0.28" />
            <stop offset="100%" stopColor={metricDef.color} stopOpacity="0.02" />
          </linearGradient>
        </defs>

        {/* Y gridlines + labels */}
        {yTicks.map((t, i) => (
          <g key={i}>
            <line x1={padX} y1={y(t)} x2={width - 12} y2={y(t)} stroke="var(--color-border)" strokeWidth={1} strokeDasharray="3,4" />
            <text x={padX - 8} y={y(t) + 3} fontSize={10} fill="var(--color-text-muted)" textAnchor="end">
              {roundTo(t, 1)}{metricDef.unit}
            </text>
          </g>
        ))}

        {points.length === 0 ? (
          <text x={width / 2} y={chartH / 2} fontSize={11} fill="var(--color-text-muted)" textAnchor="middle">
            No {metricDef.label.toLowerCase()} measurements recorded yet.
          </text>
        ) : (
          <>
            {sorted.length > 1 && <path d={areaPath} fill="url(#storyFill)" />}
            {sorted.length > 1 && <path d={linePath} fill="none" stroke={metricDef.color} strokeWidth={2.6} strokeLinecap="round" strokeLinejoin="round" />}
            {sorted.map((p, i) => {
              const isHover = hover?.kind === "point" && hover.i === i;
              return (
                <circle
                  key={i} cx={x(p.ageDays)} cy={y(p.value)} r={isHover ? 7.5 : 5.5}
                  fill={metricDef.color} stroke="#fff" strokeWidth={isHover ? 2.5 : 1.5}
                  style={{ cursor: "pointer", transition: "r 0.1s" }}
                  onMouseEnter={() => setHover({ kind: "point", i, x: x(p.ageDays), y: y(p.value), p })}
                  onMouseLeave={() => setHover(null)}
                />
              );
            })}
          </>
        )}

        {/* X axis line + age ticks */}
        <line x1={padX} y1={chartH - padY} x2={width - 12} y2={chartH - padY} stroke="var(--color-border)" strokeWidth={1} />
        {ageTicks.map((t, i) => (
          <text key={i} x={x(t)} y={chartH - 2} fontSize={9.5} fill="var(--color-text-muted)" textAnchor="middle">
            {formatAge(t)}
          </text>
        ))}

        {/* separator between growth panel and vaccination lane */}
        <line x1={0} y1={chartH + 8} x2={width} y2={chartH + 8} stroke="var(--color-border)" strokeWidth={1} />
        <text x={padX} y={chartH + 20} fontSize={9.5} fontWeight={700} fill="var(--color-text-muted)" style={{ textTransform: "uppercase", letterSpacing: 0.4 }}>
          Vaccinations
        </text>

        {/* vaccination marker lane */}
        {markers.map((m, i) => {
          const mx = x(m.ageDays);
          const color = BUCKET_COLOR[m.bucket];
          const isHover = hover?.kind === "marker" && hover.i === i;
          return (
            <g
              key={i} style={{ cursor: "pointer" }}
              onClick={() => onMarkerClick(m)}
              onMouseEnter={() => setHover({ kind: "marker", i, x: mx, y: chartH + laneH + 6, m })}
              onMouseLeave={() => setHover(null)}
            >
              <line x1={mx} y1={chartH + 24} x2={mx} y2={chartH + laneH + 2} stroke={color} strokeWidth={1.4} strokeDasharray="2,2" opacity={0.6} />
              <circle cx={mx} cy={chartH + laneH + 2} r={isHover ? 7 : 5.5} fill={color} stroke="#fff" strokeWidth={isHover ? 2 : 1} style={{ transition: "r 0.1s" }} />
            </g>
          );
        })}
      </svg>

      {hover?.kind === "point" && (
        <ChartTooltip x={hover.x} y={hover.y} viewW={width} viewH={totalH}>
          <TooltipValue label={metricDef.label} value={`${hover.p.value} ${metricDef.unit}`} />
          <TooltipValue label="Date" value={formatDate(hover.p.date)} />
          {hover.p.ageDays != null && <TooltipValue label="Age" value={formatAge(hover.p.ageDays)} />}
          {SOURCE_LABEL[hover.p.source] && <div style={{ opacity: 0.65, marginTop: 2 }}>{SOURCE_LABEL[hover.p.source]}</div>}
        </ChartTooltip>
      )}
      {hover?.kind === "marker" && (
        <ChartTooltip x={hover.x} y={hover.y} viewW={width} viewH={totalH} align="bottom">
          <div style={{ fontWeight: 700, marginBottom: 2 }}>{hover.m.vaccine_name}</div>
          <TooltipValue label="Status" value={hover.m.bucket} />
          <TooltipValue label="Date" value={formatDate(hover.m.eventDate)} />
          {hover.m.ageDays != null && <TooltipValue label="Age" value={formatAge(hover.m.ageDays)} />}
          <div style={{ opacity: 0.65, marginTop: 2 }}>
            {hover.m.has_certificate ? "Click to view certificate" : "No document on file"}
          </div>
        </ChartTooltip>
      )}
    </div>
  );
}

// Simple chronological chart of the selected metric alone — Line / Bar /
// Area variants, with real Y-axis gridlines and a styled hover tooltip on
// every point/bar (date / value / age / source — no fabricated document
// link, since a growth measurement has no document in this system).
function SimpleChart({ type, points, metricDef }) {
  const [hover, setHover] = useState(null);
  if (points.length === 0) {
    return (
      <div style={{ padding: "40px 0", textAlign: "center", fontSize: 12, color: "var(--color-text-muted)" }}>
        No {metricDef.label.toLowerCase()} measurements recorded yet.
      </div>
    );
  }

  const width = 560, height = 190, padX = 52, padY = 18;
  const values = points.map(p => p.value);
  const vMin = Math.min(...values, 0);
  const vMax = Math.max(...values);
  const pad = (vMax - vMin) * 0.12 || vMax * 0.1 || 1;
  const lo = Math.max(0, vMin - pad);
  const hi = vMax + pad;
  const range = hi - lo || 1;
  const stepX = points.length > 1 ? (width - padX - 16) / (points.length - 1) : 0;

  const coords = points.map((p, i) => ({
    ...p,
    x: padX + i * stepX,
    y: padY + (height - padY * 2) * (1 - (p.value - lo) / range),
  }));

  const yTicks = makeTicks(lo, hi, 4);
  const linePath = coords.length > 1 ? coords.map((c, i) => `${i === 0 ? "M" : "L"}${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(" ") : "";
  const baseline = height - padY;
  const areaPath = coords.length > 1
    ? `${linePath} L${coords[coords.length - 1].x.toFixed(1)},${baseline} L${coords[0].x.toFixed(1)},${baseline} Z`
    : "";
  const barWidth = points.length > 1 ? Math.min(30, stepX * 0.5) : 30;

  // Label every point if there's room, otherwise thin them out so text
  // never overlaps — always keep the first and last labelled.
  const labelEvery = Math.max(1, Math.ceil(coords.length / 8));

  return (
    <div style={{ position: "relative" }}>
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} preserveAspectRatio="xMidYMid meet">
        <defs>
          <linearGradient id="simpleFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={metricDef.color} stopOpacity="0.30" />
            <stop offset="100%" stopColor={metricDef.color} stopOpacity="0.02" />
          </linearGradient>
        </defs>

        {yTicks.map((t, i) => {
          const ty = padY + (height - padY * 2) * (1 - (t - lo) / range);
          return (
            <g key={i}>
              <line x1={padX} y1={ty} x2={width - 12} y2={ty} stroke="var(--color-border)" strokeWidth={1} strokeDasharray="3,4" />
              <text x={padX - 8} y={ty + 3} fontSize={10} fill="var(--color-text-muted)" textAnchor="end">
                {roundTo(t, 1)}{metricDef.unit}
              </text>
            </g>
          );
        })}

        {type === "bar" && coords.map((c, i) => {
          const isHover = hover === i;
          return (
            <rect
              key={i} x={c.x - barWidth / 2} y={c.y} width={barWidth} height={Math.max(baseline - c.y, 0)}
              fill={metricDef.color} opacity={isHover ? 1 : 0.85} rx={4}
              style={{ cursor: "pointer", transition: "opacity 0.1s" }}
              onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}
            />
          );
        })}

        {type === "area" && coords.length > 1 && <path d={areaPath} fill="url(#simpleFill)" />}
        {(type === "line" || type === "area") && coords.length > 1 && (
          <path d={linePath} fill="none" stroke={metricDef.color} strokeWidth={2.6} strokeLinecap="round" strokeLinejoin="round" />
        )}
        {(type === "line" || type === "area") && coords.map((c, i) => {
          const isHover = hover === i;
          return (
            <circle
              key={i} cx={c.x} cy={c.y} r={isHover ? 7.5 : 5.5} fill={metricDef.color} stroke="#fff" strokeWidth={isHover ? 2.5 : 1.5}
              style={{ cursor: "pointer", transition: "r 0.1s" }}
              onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}
            />
          );
        })}

        <line x1={padX} y1={baseline} x2={width - 12} y2={baseline} stroke="var(--color-border)" strokeWidth={1} />
        {coords.map((c, i) => {
          if (i !== 0 && i !== coords.length - 1 && i % labelEvery !== 0) return null;
          return (
            <text key={i} x={c.x} y={height - 3} fontSize={9.5} fill="var(--color-text-muted)" textAnchor="middle">
              {formatDateShort(c.date)}
            </text>
          );
        })}
      </svg>

      {hover != null && (
        <ChartTooltip x={coords[hover].x} y={coords[hover].y} viewW={width} viewH={height}>
          <TooltipValue label={metricDef.label} value={`${coords[hover].value} ${metricDef.unit}`} />
          <TooltipValue label="Date" value={formatDate(coords[hover].date)} />
          {coords[hover].ageDays != null && <TooltipValue label="Age" value={formatAge(coords[hover].ageDays)} />}
          {SOURCE_LABEL[coords[hover].source] && <div style={{ opacity: 0.65, marginTop: 2 }}>{SOURCE_LABEL[coords[hover].source]}</div>}
        </ChartTooltip>
      )}
    </div>
  );
}
