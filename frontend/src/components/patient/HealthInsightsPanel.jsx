/**
 * components/patient/HealthInsightsPanel.jsx
 * ---------------------------------------------
 * "Health Insights" — embedded as a tab inside My Reports (not a separate
 * page). Read-only rollup of the patient's own vault (SharedDocument), fed
 * by GET /api/v1/portal/health-insights/ (apps/patients/portal_views.py).
 *
 * Most sections here are counts/dates only from SharedDocument — but
 * Flagged Changes and Reports Needing Review DO reflect actual extracted
 * test values, via core.lab_variation.compute_flags() over
 * core.lab_value_extractor's stored results (a separate, async pipeline
 * stage from classification — see PortalHealthInsightsView's docstring).
 * A confidence gate applies server-side before any value is ever compared
 * or shown here; this component never computes or gates anything itself,
 * only renders what the endpoint already decided was trustworthy.
 *
 * Chart choices follow the dataviz skill's researched rules rather than
 * copying the earlier mockup verbatim:
 *   - Report Type Distribution is a horizontal bar list, NOT a donut — the
 *     skill's anti-patterns call out "a donut/pie for comparing close
 *     values" specifically, and a patient's panels are very often tied at
 *     1-2 documents each (exactly that case). Bars stay legible either way.
 *   - Colors are a small FIXED, CVD-validated categorical palette assigned
 *     in a fixed order (never generated/cycled) — see PANEL_PALETTE below.
 *     Beyond 6 panels the tail folds into "Other" rather than adding a 7th+
 *     generated hue (an indistinguishable-under-CVD anti-pattern).
 *   - Upload Activity uses the "emphasis" pattern (one bar — the busiest
 *     month — in the accent color, the rest in a muted tint of the same
 *     hue) instead of two competing saturated colors.
 *
 * Everything lives on this one scrollable page — no nested tabs/sub-screens
 * inside Health Insights. It's a lightweight enhancement panel inside My
 * Reports, not a module in its own right, so a per-analyte trend
 * (TrendSpotlightCard, auto-picking whichever test has enough history) and
 * the latest report's key changes (LatestVsPreviousCard, from
 * flagged_variations) are embedded cards here rather than a separate view.
 */
import { useMemo, useState } from "react";
import {
  BarChart3, FileText, Pill, FlaskConical, Calendar, TrendingUp, TrendingDown, AlertTriangle, Sparkles,
  CalendarClock, ChevronRight, Droplet, Zap, Beaker, Shield, Microscope, HeartPulse, Activity,
} from "lucide-react";
import { useApi } from "../../hooks/useApi";
import API_ENDPOINTS from "../../config/api.config";
import TrendSpotlightCard from "./TrendSpotlightCard";

const RANGE_OPTIONS = [
  { value: "3m",  label: "Last 3 months" },
  { value: "6m",  label: "Last 6 months" },
  { value: "12m", label: "Last 12 months" },
  { value: "all", label: "All time" },
];

// Fixed order, CVD-validated (dataviz skill's validate_palette.js — worst
// adjacent pair ΔE 8.0 deutan/protan, clear of the >=6 floor; direct labels
// on every bar satisfy the secondary-encoding requirement that comes with
// that band). Never cycled or extended — a 7th+ panel folds into "Other".
const PANEL_PALETTE = ["#2A72C9", "#C96A2A", "#1F8F6E", "#BD8A25", "#C23E7E", "#227A45"];
const OTHER_COLOR = "#9B9B94";
const MAX_PANEL_SLOTS = 6;

// Soft pastel badge per stat tile — bg tint + a matching saturated icon
// color. Deliberately not the shared `.icon-chip--*` classes: those are
// tuned for this theme's forest-green/gold brand accents elsewhere in the
// app, but don't offer a fourth (purple) hue and read heavier/darker than
// suits a light, glanceable badge. These four are local to this panel.
const TILE_TINTS = {
  blue:   { bg: "#EAF1FD", fg: "#3D74E0" },
  teal:   { bg: "#E6F7F1", fg: "#12A67F" },
  purple: { bg: "#F1ECFC", fg: "#8558E8" },
  orange: { bg: "#FDEEE2", fg: "#E8813F" },
};

function StatTile({ tint, icon: Icon, label, value, sub }) {
  const { bg, fg } = TILE_TINTS[tint];
  return (
    <div className="card" style={{ padding: "16px 18px", display: "flex", gap: 12 }}>
      <div style={{
        width: 40, height: 40, flexShrink: 0, borderRadius: 12, background: bg, color: fg,
        display: "flex", alignItems: "center", justifyContent: "center",
      }}>
        <Icon size={18} />
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 11.5, fontWeight: 700, color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.03em" }}>
          {label}
        </div>
        <div style={{ fontFamily: "var(--font-display)", fontSize: 21, fontWeight: 700, marginTop: 2, lineHeight: 1.25 }}>
          {value}
        </div>
        {sub && (
          <div style={{ fontSize: 11.5, color: "var(--color-text-muted)", marginTop: 2 }}>{sub}</div>
        )}
      </div>
    </div>
  );
}

function monthLabel(key) {
  const [y, m] = key.split("-").map(Number);
  if (!y || !m) return key;
  return new Date(y, m - 1, 1).toLocaleDateString("en-IN", { month: "short", year: "2-digit" });
}

function formatDate(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

/** Folds a sorted-desc distribution list down to <= MAX_PANEL_SLOTS entries,
 * summing anything past the cap into a single neutral "Other" bucket — the
 * dataviz skill's rule for "more series than the validated palette holds"
 * (fold the tail, never generate a 7th+ hue). */
function foldDistribution(distribution) {
  if (distribution.length <= MAX_PANEL_SLOTS) {
    return distribution.map((p, i) => ({ ...p, color: PANEL_PALETTE[i] }));
  }
  const head = distribution.slice(0, MAX_PANEL_SLOTS - 1).map((p, i) => ({ ...p, color: PANEL_PALETTE[i] }));
  const tail = distribution.slice(MAX_PANEL_SLOTS - 1);
  const tailCount = tail.reduce((s, p) => s + p.count, 0);
  return [...head, { slug: "_other", label: `Other (${tail.length})`, count: tailCount, color: OTHER_COLOR }];
}

function DistributionBars({ distribution }) {
  const folded = useMemo(() => foldDistribution(distribution), [distribution]);
  const max = Math.max(1, ...folded.map(p => p.count));
  return (
    <div style={{ display: "grid", gap: 12 }}>
      {folded.map(p => (
        <div key={p.slug}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5, marginBottom: 5 }}>
            <span style={{ fontWeight: 600, display: "flex", alignItems: "center", gap: 7, minWidth: 0 }}>
              <span style={{ width: 9, height: 9, borderRadius: "50%", background: p.color, flexShrink: 0 }} />
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.label}</span>
            </span>
            <span style={{ color: "var(--color-text-muted)", fontWeight: 700, flexShrink: 0, marginLeft: 8 }}>{p.count}</span>
          </div>
          <div style={{ height: 9, borderRadius: 5, background: "var(--color-border)", overflow: "hidden" }}>
            <div style={{
              height: "100%", width: `${Math.max(4, (p.count / max) * 100)}%`,
              background: p.color, borderRadius: "0 5px 5px 0",
            }} />
          </div>
        </div>
      ))}
    </div>
  );
}

// Icon per report panel slug (core/report_types.py's PANELS) for the "Your
// Health Documents" quick-summary list — a plain generic icon for anything
// not in this short curated set, rather than one icon per all 15 panels.
const CATEGORY_ICON = {
  cbc: FlaskConical, lipid: Droplet, lft: HeartPulse, kft: Droplet,
  thyroid: Zap, diabetes: Activity, urine: Beaker, electrolytes: Zap,
  vitamin: Sparkles, inflammation: HeartPulse, cardiac: HeartPulse,
  coagulation: Droplet, hormone: Zap, infection: Shield, culture: Microscope,
};

/** One row of the "Your Health Documents" quick summary — a colored icon
 * badge (same fixed color a category gets in the Report Type Distribution
 * bars above, so the two sections visually agree), a count, the latest
 * date, and a chevron through to that category filtered in My Documents. */
function QuickSummaryRow({ icon: Icon, color, label, count, latest, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "flex", alignItems: "center", gap: 12, width: "100%", padding: "9px 6px",
        border: "none", background: "none", cursor: onClick ? "pointer" : "default", textAlign: "left", font: "inherit",
      }}
    >
      <div style={{
        width: 34, height: 34, flexShrink: 0, borderRadius: 10, color,
        background: `color-mix(in srgb, ${color} 16%, var(--color-bg))`,
        display: "flex", alignItems: "center", justifyContent: "center",
      }}>
        <Icon size={16} />
      </div>
      <div style={{ flex: 1, minWidth: 0, fontSize: 13, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {label}
      </div>
      <div style={{ textAlign: "right", flexShrink: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 700 }}>{count}</div>
        {latest && <div style={{ fontSize: 10.5, color: "var(--color-text-muted)" }}>Latest: {latest}</div>}
      </div>
      {onClick && <ChevronRight size={15} style={{ color: "var(--color-text-muted)", flexShrink: 0 }} />}
    </button>
  );
}

/** "Key parameter changes in your most recent report" — deliberately scoped
 * to flags that belong to the latest lab report specifically (not just the
 * single largest flag ever, which is what the "Flagged Changes" section
 * below already covers over the patient's whole history). Renders nothing
 * when the latest report has no flagged change — an honest empty state
 * rather than reaching for an older, less relevant one. */
function LatestVsPreviousCard({ flag, panelLabel }) {
  const Icon = flag.direction === "up" ? TrendingUp : TrendingDown;
  const concerning = (flag.concern === "higher_is_concern" && flag.direction === "up")
    || (flag.concern === "lower_is_concern" && flag.direction === "down");
  const absDelta = flag.current_value - flag.previous_value;
  const deltaText = `${absDelta > 0 ? "+" : ""}${Math.round(absDelta * 10) / 10}${flag.unit}`;

  return (
    <div className="card" style={{ padding: "18px 20px" }}>
      <div className="dot-label dot-label--gold" style={{ marginBottom: 2 }}>Latest vs Previous Report</div>
      <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 14 }}>
        Your most notable recent change
      </div>

      <div style={{ padding: "12px 14px", borderRadius: 10, background: "var(--color-bg)", border: "1px solid var(--color-border)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12, gap: 8 }}>
          <div>
            <div style={{ fontSize: 13.5, fontWeight: 700 }}>{flag.parameter_label}</div>
            {panelLabel && <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>({panelLabel})</div>}
          </div>
          <span style={{
            display: "flex", alignItems: "center", gap: 4, fontSize: 12.5, fontWeight: 700, flexShrink: 0,
            color: concerning ? "var(--color-error)" : "var(--color-primary)",
          }}>
            <Icon size={14} /> {deltaText}
          </span>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div>
            <div style={{ fontSize: 10.5, color: "var(--color-text-muted)", marginBottom: 3 }}>Previous ({formatDate(flag.previous_document_date)})</div>
            <div style={{ fontSize: 15, fontWeight: 700 }}>{flag.previous_value}{flag.unit}</div>
          </div>
          <div>
            <div style={{ fontSize: 10.5, color: "var(--color-text-muted)", marginBottom: 3 }}>Latest ({formatDate(flag.document_date)})</div>
            <div style={{ fontSize: 15, fontWeight: 700, color: concerning ? "var(--color-error)" : "var(--color-text)" }}>{flag.current_value}{flag.unit}</div>
          </div>
        </div>
      </div>
    </div>
  );
}

/** A value that changed meaningfully since the patient's last reading of the
 * same test — server-computed by core.lab_variation.compute_flags (never
 * anything derived client-side, so the confidence gate / unit guard / basis
 * logic lives in exactly one place). "reference_range" basis (the report's
 * own printed range) is a stronger signal than "percent_delta" (the flat 20%
 * fallback), shown as a solid vs. softer accent rather than extra copy. */
function FlaggedVariationCard({ flag, onOpenDocument }) {
  const Icon = flag.direction === "up" ? TrendingUp : TrendingDown;
  const strong = flag.basis === "reference_range";
  return (
    <button
      onClick={() => onOpenDocument?.({ id: flag.document_id, title: flag.parameter_label })}
      style={{
        display: "flex", gap: 10, alignItems: "flex-start", width: "100%", textAlign: "left",
        padding: "12px 14px", borderRadius: 10, cursor: "pointer", font: "inherit",
        background: strong ? "var(--color-error-light)" : "var(--color-warning-light)",
        border: `1px solid ${strong ? "var(--color-error)" : "var(--color-warning)"}`,
      }}
    >
      <Icon size={16} style={{ flexShrink: 0, marginTop: 1, color: strong ? "var(--color-error)" : "var(--color-warning)" }} />
      <span style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--color-text)" }}>{flag.message}</span>
    </button>
  );
}

/** A document the automated value-extraction couldn't confidently read —
 * named explicitly rather than silently dropped, per the whole point of
 * this feature. Read-only (no inline correction form — that's a future
 * pass); clicking opens the real document so the patient can at least look
 * at it themselves. Visually modeled on MyReportsPage's ReviewRow (the
 * classification review-tray pattern) but trimmed down, since this is a
 * different, non-overlapping "review" concept — extraction, not filing. */
function ReviewNeededRow({ item, onOpenDocument }) {
  return (
    <button
      onClick={() => onOpenDocument?.({ id: item.id, title: item.title })}
      style={{
        display: "flex", gap: 10, alignItems: "center", width: "100%", textAlign: "left",
        padding: "10px 12px", borderRadius: 10, cursor: "pointer", font: "inherit",
        background: "none", border: "1px solid var(--color-border)", borderLeft: "3px solid var(--color-warning)",
      }}
    >
      <AlertTriangle size={15} style={{ flexShrink: 0, color: "var(--color-warning)" }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {item.title || "Untitled"}
        </div>
        <div style={{ fontSize: 11.5, color: "var(--color-text-muted)", marginTop: 2 }}>{item.reason}</div>
      </div>
      <span style={{
        fontSize: 10.5, fontWeight: 700, color: "var(--color-warning)", border: "1px solid var(--color-border)",
        borderRadius: 5, padding: "2px 6px", flexShrink: 0,
      }}>REVIEW</span>
    </button>
  );
}

/** "It's been N months since your last X" — a general wellness nudge, not a
 * clinical directive (see core.report_types.ROUTINE_CHECKUP_INTERVAL_MONTHS's
 * docstring for why it's one uniform interval, not a differentiated table
 * this app has no guideline source for). Calm info-blue, not the warning/
 * error tones used for Flagged Changes and Reports Needing Review — those
 * two are about something already in hand; this is just a friendly "it's
 * been a while," so it shouldn't visually compete with them for attention. */
function CheckupReminderCard({ reminder }) {
  return (
    <div style={{
      display: "flex", gap: 10, alignItems: "flex-start", padding: "12px 14px",
      borderRadius: 10, background: "var(--color-info-light)", border: "1px solid var(--color-info)",
    }}>
      <CalendarClock size={16} style={{ flexShrink: 0, marginTop: 1, color: "var(--color-info)" }} />
      <span style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--color-text)" }}>{reminder.message}</span>
    </div>
  );
}

export default function HealthInsightsPanel({ patientAwpid, onOpenDocument, onViewAll }) {
  const [range, setRange] = useState("12m");

  const { data, isLoading, error } = useApi(API_ENDPOINTS.PORTAL.HEALTH_INSIGHTS, {
    params: { range, ...(patientAwpid ? { patient_awpid: patientAwpid } : {}) },
  });

  const distribution = data?.report_distribution || [];
  const uploadActivity = data?.upload_activity || [];
  const recentPrescriptions = data?.recent_prescriptions || [];
  const recentReports = data?.recent_reports || [];
  const flaggedVariations = data?.flagged_variations || [];
  const reportsNeedingReview = data?.reports_needing_review || [];
  const checkupReminders = data?.checkup_reminders || [];
  const totalDocuments = data?.total_documents ?? 0;
  const totalReports = data?.total_reports ?? 0;
  const totalPrescriptions = data?.total_prescriptions ?? 0;
  const otherDocuments = Math.max(0, totalDocuments - totalReports - totalPrescriptions);

  const maxMonthCount = useMemo(
    () => Math.max(1, ...(data?.upload_activity || []).map(m => m.count)),
    [data]
  );

  const busiestMonth = useMemo(() => {
    const months = data?.upload_activity || [];
    if (!months.length) return null;
    return months.reduce((best, m) => (m.count > best.count ? m : best), months[0]);
  }, [data]);

  const takeaways = useMemo(() => {
    if (!data || totalDocuments === 0) return [];
    const items = [];
    const rangeLabel = RANGE_OPTIONS.find(r => r.value === (data.range || range))?.label.toLowerCase() || "this period";
    items.push(`You've added ${totalDocuments} document${totalDocuments === 1 ? "" : "s"} in the ${rangeLabel === "all time" ? "vault" : rangeLabel}.`);
    if (data.most_common_panel) items.push(`Most of your lab reports are ${data.most_common_panel}.`);
    if (data.latest_report_date) items.push(`Your most recent document is dated ${formatDate(data.latest_report_date)}.`);
    items.push(...(data.pattern_insights || []));
    return items;
  }, [data, totalDocuments, range]);

  // The "Latest vs Previous Report" spotlight — whichever flagged change
  // has the most recent document_date, not just the largest flag ever
  // (that's what the full "Flagged Changes" list below already covers).
  // Deliberately NOT bound to literally the newest uploaded document: that
  // report might be a panel with nothing flaggable (e.g. a normal
  // Inflammatory Markers result) while a CBC one report back has a real,
  // recent, worth-surfacing change — the flag's own date is the better
  // "recency" signal here than "which document was uploaded last."
  const latestReportFlag = useMemo(() => {
    if (!flaggedVariations.length) return null;
    return [...flaggedVariations].sort((a, b) => (b.document_date || "").localeCompare(a.document_date || ""))[0];
  }, [flaggedVariations]);
  const latestReportPanelLabel = latestReportFlag
    ? recentReports.find(r => r.id === latestReportFlag.document_id)?.report_categories?.[0]?.label
    : undefined;

  const topCategories = useMemo(() => foldDistribution(distribution).filter(p => p.slug !== "_other"), [distribution]);

  return (
    <div>
      <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginBottom: 12 }}>
        Quick insights from your uploaded health documents and prescriptions.
      </div>

      <div style={{
        display: "flex", gap: 9, alignItems: "flex-start", padding: "10px 14px", marginBottom: 18,
        borderRadius: 10, background: "var(--color-primary-light)",
      }}>
        <Sparkles size={15} style={{ flexShrink: 0, marginTop: 1, color: "var(--color-primary)" }} />
        <span style={{ fontSize: 12, lineHeight: 1.5, color: "var(--color-text-secondary)" }}>
          <strong style={{ color: "var(--color-primary)" }}>Generated automatically</strong> from your reports to
          help you spot patterns early. It's a helpful second pair of eyes, not a diagnosis — always confirm
          anything important with your doctor.
        </span>
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 20 }}>
        {RANGE_OPTIONS.map(o => (
          <button
            key={o.value}
            onClick={() => setRange(o.value)}
            className={o.value === range ? "badge badge--primary" : "badge badge--neutral"}
            style={{ cursor: "pointer", border: "none", padding: "8px 16px", fontSize: 12.5, fontWeight: 700, borderRadius: 20 }}
          >
            {o.label}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
      ) : error ? (
        <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>
          Couldn't load Health Insights right now. Please try again in a moment.
        </div>
      ) : totalDocuments === 0 ? (
        <div className="card" style={{ padding: 44, textAlign: "center" }}>
          <div style={{ fontFamily: "var(--font-display)", fontSize: 18, fontWeight: 600, marginBottom: 6 }}>
            No documents in this range yet
          </div>
          <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
            Add a report or prescription above, or try a wider date range.
          </div>
        </div>
      ) : (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 14, marginBottom: 20 }}>
            <StatTile
              tint="blue" icon={FileText} label="Total Documents" value={totalDocuments}
              sub={`${totalReports} report${totalReports === 1 ? "" : "s"} · ${totalPrescriptions} prescription${totalPrescriptions === 1 ? "" : "s"}${otherDocuments > 0 ? ` · ${otherDocuments} other${otherDocuments === 1 ? "" : "s"}` : ""}`}
            />
            <StatTile
              tint="teal" icon={FlaskConical} label="Lab Reports" value={totalReports}
              sub={distribution.length > 0 ? `Most common: ${distribution[0].label} (${distribution[0].count})` : "None classified yet"}
            />
            <StatTile
              tint="purple" icon={Pill} label="Prescriptions" value={totalPrescriptions}
              sub={recentPrescriptions.length > 0 ? `Latest: ${formatDate(recentPrescriptions[0].date)}` : "None in this range"}
            />
            <StatTile tint="orange" icon={Calendar} label="Latest Report" value={formatDate(data.latest_report_date)} />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(340px, 100%), 1fr))", gap: 16, marginBottom: 16 }}>
            <div className="card" style={{ padding: "18px 20px" }}>
              <div className="dot-label dot-label--blue" style={{ marginBottom: 14 }}>Report Type Distribution</div>
              {distribution.length === 0 ? (
                <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>No lab reports have been classified into a panel yet.</div>
              ) : (
                <DistributionBars distribution={distribution} />
              )}
            </div>

            <TrendSpotlightCard patientAwpid={patientAwpid} range={range} />
          </div>

          {(latestReportFlag || topCategories.length > 0 || totalPrescriptions > 0) && (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(340px, 100%), 1fr))", gap: 16, marginBottom: 16 }}>
              {latestReportFlag && <LatestVsPreviousCard flag={latestReportFlag} panelLabel={latestReportPanelLabel} />}

              <div className="card" style={{ padding: "18px 20px" }}>
                <div className="dot-label dot-label--green" style={{ marginBottom: 2 }}>Your Health Documents</div>
                <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 8 }}>Quick summary</div>
                <div style={{ display: "grid" }}>
                  {topCategories.map(p => (
                    <QuickSummaryRow
                      key={p.slug} icon={CATEGORY_ICON[p.slug] || FlaskConical} color={p.color}
                      label={p.label} count={p.count}
                      onClick={() => onViewAll?.(p.slug)}
                    />
                  ))}
                  {totalPrescriptions > 0 && (
                    <QuickSummaryRow
                      icon={Pill} color={TILE_TINTS.purple.fg} label="Prescriptions" count={totalPrescriptions}
                      latest={recentPrescriptions[0] ? formatDate(recentPrescriptions[0].date) : null}
                      onClick={() => onViewAll?.("prescription")}
                    />
                  )}
                </div>
              </div>
            </div>
          )}

          {takeaways.length > 0 && (
            <div className="card" style={{ padding: "16px 20px", marginBottom: 20 }}>
              <div className="dot-label dot-label--green" style={{ marginBottom: 10 }}>Quick summary</div>
              <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 6 }}>
                {takeaways.map((t, i) => (
                  <li key={i} style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>{t}</li>
                ))}
              </ul>
            </div>
          )}

          {flaggedVariations.length > 0 && (
            <div className="card" style={{ padding: "16px 20px", marginBottom: 20 }}>
              <div className="dot-label dot-label--red" style={{ marginBottom: 12 }}>Flagged Changes</div>
              <div style={{ display: "grid", gap: 8 }}>
                {flaggedVariations.map(flag => (
                  <FlaggedVariationCard key={`${flag.parameter_slug}:${flag.document_id}`} flag={flag} onOpenDocument={onOpenDocument} />
                ))}
              </div>
            </div>
          )}

          {checkupReminders.length > 0 && (
            <div className="card" style={{ padding: "16px 20px", marginBottom: 20 }}>
              <div className="dot-label dot-label--blue" style={{ marginBottom: 12 }}>Checkup Reminders</div>
              <div style={{ display: "grid", gap: 8 }}>
                {checkupReminders.map(r => (
                  <CheckupReminderCard key={r.panel_slug} reminder={r} />
                ))}
              </div>
            </div>
          )}

          {uploadActivity.length > 0 && (
            <div className="card" style={{ padding: "18px 20px", marginBottom: 16 }}>
              <div className="dot-label dot-label--gold" style={{ marginBottom: 14, display: "flex", alignItems: "center", gap: 6 }}>
                <BarChart3 size={13} /> Upload Activity
              </div>
              <div style={{ display: "flex", alignItems: "flex-end", gap: 6, height: 140, marginBottom: 14 }}>
                {uploadActivity.map(m => {
                  const isBusiest = m.month === busiestMonth?.month;
                  return (
                    <div key={m.month} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 4, minWidth: 0 }}>
                      <div style={{ fontSize: 10.5, color: isBusiest ? "var(--color-accent)" : "var(--color-text-muted)", fontWeight: isBusiest ? 700 : 400 }}>{m.count}</div>
                      <div style={{
                        width: "100%", maxWidth: 22,
                        height: Math.max(4, (m.count / maxMonthCount) * 88),
                        background: isBusiest ? "var(--color-accent)" : "color-mix(in srgb, var(--color-primary) 30%, var(--color-border))",
                        borderRadius: "4px 4px 0 0",
                      }} />
                      <div style={{ fontSize: 9.5, color: "var(--color-text-muted)", whiteSpace: "nowrap" }}>{monthLabel(m.month)}</div>
                    </div>
                  );
                })}
              </div>
              {busiestMonth && (
                <div style={{
                  display: "flex", alignItems: "center", gap: 8, fontSize: 12.5,
                  background: "var(--color-accent-light)", color: "var(--color-text)",
                  borderRadius: 10, padding: "10px 12px",
                }}>
                  <TrendingUp size={15} style={{ flexShrink: 0, color: "var(--color-accent)" }} />
                  <span>
                    Your busiest month was <strong>{monthLabel(busiestMonth.month)}</strong>, with {busiestMonth.count} document{busiestMonth.count === 1 ? "" : "s"} uploaded.
                  </span>
                </div>
              )}
            </div>
          )}

          {reportsNeedingReview.length > 0 && (
            <div className="card" style={{ padding: "18px 20px", marginBottom: 16 }}>
              <div className="dot-label dot-label--gold" style={{ marginBottom: 12 }}>Reports Needing Review</div>
              <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 12 }}>
                We couldn't confidently read the results in these — take a look, or re-upload a clearer copy.
              </div>
              <div style={{ display: "grid", gap: 8 }}>
                {reportsNeedingReview.map(item => (
                  <ReviewNeededRow key={item.id} item={item} onOpenDocument={onOpenDocument} />
                ))}
              </div>
            </div>
          )}

          {onViewAll && (
            <div style={{ textAlign: "right", marginTop: 14 }}>
              <button
                onClick={() => onViewAll()}
                style={{ background: "none", border: "none", cursor: "pointer", fontSize: 12.5, fontWeight: 700, color: "var(--color-primary)" }}
              >
                View all reports →
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
