/**
 * pages/patient/RecordsPage.jsx
 * -------------------------------
 * "Health Journey" — full visit history across all hospitals (timeline of
 * consults with vitals, diagnoses, and outcomes), plus the growth chart and
 * vaccination roadmap, for the account owner or a linked family member.
 *
 * Layout (rebuilt from the old flat "X / 18 completed" checklist):
 *   HealthSummaryCard (hero: avatar, name, age/gender, last visit, banner)
 *   VaccinationStats  (4 stat cards: completed/upcoming/needs review/outside)
 *   Growth            (unchanged, out of this rebuild's scope)
 *   two-column: Vaccination Timeline (left) + VaccinationSidebar (right)
 *   HealthTimeline    (unchanged, out of this rebuild's scope)
 *   Visit history list (unchanged)
 *
 * ActionCenter.jsx has been removed. Its three responsibilities now live
 * elsewhere: doctor-ordered vaccines → VaccinationSidebar's "Recommended by
 * Doctor" card; due-now/past-window "no record on file" vaccines → the
 * Needs Review stat card plus each row's own "Add Record" action in the
 * timeline below (no separate summary card needed — the timeline no longer
 * dumps all rows by default, so it isn't the wall of detail it used to be
 * sitting right next to a summary of itself); upcoming follow-ups (the one
 * non-vaccine item ActionCenter carried) → VaccinationSidebar's "Upcoming
 * Follow-ups" card, ported as-is.
 */
import { useState, useEffect, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ChevronDown, ChevronUp, Calendar, Syringe, Activity, Building2, TrendingUp } from "lucide-react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { usePaginatedList } from "../../hooks/usePaginatedList";
import { useApi }    from "../../hooks/useApi";
import { useToast }  from "../../hooks/useToast";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import ROUTES from "../../config/routes.config";
import { usePatientContext } from "../../context/PatientContext";
import HealthSummaryCard from "./components/HealthSummaryCard";
import VaccinationStats from "./components/VaccinationStats";
import VaccinationSidebar, { RecommendedByDoctor } from "./components/VaccinationSidebar";
import HealthTimeline from "./components/HealthTimeline";
import GrowthVaccinationChart from "./components/GrowthVaccinationChart";

const BADGE = {
  scheduled: "badge--primary", waiting: "badge--warning", vitals_done: "badge--success",
  in_progress: "badge--info", done: "badge--success", cancelled: "badge--error",
};

// Status values from build_roadmap() (apps/registry/vaccine_schedule.py):
// "completed" / "pending_review" / "rejected" when a real SharedVaccination
// record matches the slot, or "unknown" when none does. "unknown" is never
// shown as "overdue" or "missed" — the backend genuinely doesn't know
// whether the vaccine was given elsewhere, only that there's no record of
// it here. The `timing` field ("upcoming" / "due_now" / "past_window") is
// separate, informational-only metadata about whether the age window has
// been reached — it does not change the status label/color.
//
// Buckets into the 3-pill vocabulary the mockup uses (Completed / Upcoming /
// Needs Review) — a coarser read than the old per-status badge set, on
// purpose: "pending_review" and "unknown due_now/past_window" both read as
// "someone should look at this", so they share one pill and one color
// rather than five different badge styles.
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

const PILL_STYLE = {
  Completed:    { label: "Completed",    bg: "var(--color-success-light)", color: "var(--color-success)" },
  Upcoming:     { label: "Upcoming",     bg: "var(--color-warning-light)", color: "var(--color-warning)" },
  "Needs Review": { label: "Needs Review", bg: "#F1E9FA", color: "#6B3FA0" },
};

// Groups an already-ordered roadmap array into schedule-order sections keyed
// by scheduled_label ("Birth", "6 weeks", …) — build_roadmap() already
// returns catalog slots in schedule order followed by any extra/unmatched
// records, so grouping just needs to preserve first-seen order, not re-sort.
function groupByMilestone(roadmap) {
  const order = [];
  const byLabel = {};
  for (const item of roadmap) {
    const label = item.scheduled_label || "Other records";
    if (!byLabel[label]) { byLabel[label] = []; order.push(label); }
    byLabel[label].push(item);
  }
  return order.map(label => ({ label, items: byLabel[label] }));
}

// Splits the roadmap into "shown by default" and "behind the toggle": every
// resolved slot (Completed bucket — already has an answer, cheap to show)
// stays visible, plus only the first 2 not-yet-resolved slots (Upcoming or
// Needs Review) in schedule order. This is the fix for the old page dumping
// all 18 rows at once — a parent gets the next couple of actionable things
// expanded, and everything further out collapses behind "View all vaccines".
const PENDING_PREVIEW_COUNT = 2;

function splitTimeline(roadmap) {
  let pendingSeen = 0;
  const decorated = roadmap.map(item => {
    const bucket = vaxBucket(item);
    let visible = true;
    if (bucket !== "Completed") {
      pendingSeen += 1;
      visible = pendingSeen <= PENDING_PREVIEW_COUNT;
    }
    return { item, bucket, visible };
  });
  const hiddenCount = decorated.filter(d => !d.visible).length;
  return { decorated, hiddenCount };
}

// Fetches the actual certificate file for a vaccination record on demand and
// opens it in a new tab — the roadmap only ever sends has_certificate (a
// boolean) to keep that payload light. Same pattern as LabReportsPage's
// ViewInHouseReportButton / PortalLabReportFileView.
function ViewCertificateButton({ recordId }) {
  const { toastApiError } = useToast();
  const [loading, setLoading] = useState(false);

  async function open() {
    setLoading(true);
    try {
      const res = await apiClient.get(API_ENDPOINTS.PORTAL.VACCINATION_FILE(recordId));
      const data = res.data?.data || res.data;
      if (data?.file_data) {
        const win = window.open();
        if (win) win.location.href = data.file_data;
      }
    } catch (err) {
      toastApiError(err, "Could not load the certificate.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <button className="btn-outline" disabled={loading} onClick={open} style={{ padding: "3px 10px", fontSize: 11 }}>
      {loading ? "Loading…" : "View Certificate"}
    </button>
  );
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload  = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

// Today's date in YYYY-MM-DD, for the date input's `max` — blocks the
// browser's native date picker from accepting a future date outright, and
// (paired with the maxLength guard on typed input below) makes it much
// harder to fat-finger a 5-digit year like "82026" that would otherwise
// sail through as a "valid-looking" date string.
function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function UploadVaccinationForm({ patientAwpid, prefillVaccine, prefillLabel, onDone, onCancel }) {
  const { toastSuccess, toastApiError } = useToast();
  const [vaccineName, setVaccineName] = useState(prefillVaccine || "");
  const [administeredDate, setAdministeredDate] = useState("");
  const [file, setFile] = useState(null);
  const [saving, setSaving] = useState(false);

  async function submit() {
    if (!vaccineName.trim() || !administeredDate) return;
    setSaving(true);
    try {
      const body = {
        vaccine_name: vaccineName.trim(),
        administered_date: administeredDate,
        // Ties this self-reported record back to the exact schedule slot
        // ("Birth", "6 Weeks", ...) it fulfills, when known — without this,
        // build_roadmap() can't match the upload to its catalog slot (name
        // + label must both match), so the slot keeps showing "No record"
        // AND the upload shows up a second time, unmatched, at the very
        // end of the list. Left blank on purpose for a free-form "outside"
        // entry that isn't tied to any specific slot (Upload Card / Enter
        // Manually from the sidebar) — those are correctly appended as extras.
        scheduled_label: prefillLabel || "",
        ...(patientAwpid ? { patient_awpid: patientAwpid } : {}),
      };
      if (file) {
        body.file_data = await fileToDataUrl(file);
        body.file_name = file.name;
        body.mime_type = file.type;
      }
      await apiClient.post(API_ENDPOINTS.PORTAL.VACCINATION_UPLOAD, body);
      toastSuccess("Submitted — this will show as pending review until a doctor confirms it.");
      onDone();
    } catch (err) {
      toastApiError(err, "Could not submit that record.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card" style={{ padding: 14, display: "grid", gap: 8, marginTop: 8 }}>
      <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
        Add a vaccination given outside this network — a doctor will need to confirm it before it shows as done.
        The certificate photo is optional, so this also works as a manual entry.
      </div>
      <input
        placeholder="Vaccine name"
        value={vaccineName}
        onChange={e => setVaccineName(e.target.value)}
        style={{ padding: "8px 10px", borderRadius: 6, border: "1px solid var(--color-border)", fontSize: 13 }}
      />
      <input
        type="date"
        value={administeredDate}
        max={todayIso()}
        min="1900-01-01"
        onChange={e => {
          // Belt-and-braces against a mistyped year (e.g. "82026" instead
          // of "2026") slipping through as a technically-valid-looking
          // date string — the backend now rejects this too, but catching
          // it here means the field itself flags the problem inline.
          const v = e.target.value;
          const yearPart = v.split("-")[0];
          if (yearPart && yearPart.length > 4) return;
          setAdministeredDate(v);
        }}
        style={{ padding: "8px 10px", borderRadius: 6, border: "1px solid var(--color-border)", fontSize: 13 }}
      />
      <input type="file" accept="image/*,application/pdf" onChange={e => setFile(e.target.files?.[0] || null)} />
      <div style={{ display: "flex", gap: 8 }}>
        <button className="btn-primary" disabled={saving || !vaccineName.trim() || !administeredDate} onClick={submit}
          style={{ padding: "8px 16px", fontSize: 13 }}>
          {saving ? "Submitting…" : "Submit"}
        </button>
        <button className="btn-outline" onClick={onCancel} style={{ padding: "8px 16px", fontSize: 13 }}>Cancel</button>
      </div>
    </div>
  );
}

// Mapping of API scheduled_label → age-range display text for the timeline header
const MILESTONE_AGES = {
  "Birth": "0-1 month",
  "6 Weeks": "6-7 weeks",
  "10 Weeks": "10-11 weeks",
  "14 Weeks": "14-16 weeks",
  "6 Months": "6-9 months",
  "9 Months": "9-12 months",
  "12 Months": "12-15 months",
  "15 Months": "15-18 months",
  "18 Months": "18-24 months",
  "2 Years": "24-30 months",
  "5 Years": "4-6 years",
};

// Builds display groups: completed/upcoming items grouped by milestone label,
// all Needs Review items collected into a single group at the bottom.
function buildTimelineGroups(roadmap) {
  const milestoneOrder = [];
  const milestoneMap = {};
  const needsReview = [];
  for (const item of roadmap) {
    const bucket = vaxBucket(item);
    if (bucket === "Needs Review") {
      needsReview.push(item);
    } else {
      const label = item.scheduled_label || "Other";
      if (!milestoneMap[label]) { milestoneMap[label] = []; milestoneOrder.push(label); }
      milestoneMap[label].push(item);
    }
  }
  const groups = milestoneOrder.map(label => ({ label, items: milestoneMap[label], type: "milestone" }));
  if (needsReview.length > 0) groups.push({ label: "Needs Review", items: needsReview, type: "needs_review" });
  return groups;
}

// How many "Needs Review" (no-record) rows show before the list collapses
// behind "View all vaccines" — that group is the one that can list every
// unrecorded vaccine in the schedule, which is what made the timeline run
// so long.
const VAX_PREVIEW_COUNT = 5;

// How many age-milestone groups (6 weeks, 10 weeks, 14 weeks, ...) show
// before the rest collapse behind the same toggle — a full pediatric
// schedule has a dozen-plus of these, each with its own 2-3 vaccine rows,
// which makes the card run very long even when every individual group is
// short. Same showAll flag as VAX_PREVIEW_COUNT above controls both.
const GROUP_PREVIEW_COUNT = 3;

// Left column (~2/3 width): grouped vaccination timeline with vertical
// dot-and-line design. uploadFor/setUploadFor are lifted to the page level
// so VaccinationSidebar's "Upload Card"/"Enter Manually" buttons can open
// the same form from the right column.
function VaccinationTimeline({ patientAwpid, vax, vaxLoading, refetchVax, uploadFor, setUploadFor, uploadForLabel, setUploadForLabel, vaxSectionRef }) {
  const navigate = useNavigate();
  const [showAll, setShowAll] = useState(false);
  const [viewMode, setViewMode] = useState("age");
  const [collapsed, setCollapsed] = useState(false);

  const roadmap = vax?.roadmap ?? [];
  const hasData = roadmap.length > 0;
  const groups = buildTimelineGroups(roadmap);

  function getMilestoneStatus(group) {
    if (group.type === "needs_review") return "needs_review";
    const allCompleted = group.items.every(item => vaxBucket(item) === "Completed");
    return allCompleted ? "completed" : "upcoming";
  }

  return (
    <div ref={vaxSectionRef} className="card" style={{ padding: "20px 22px" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: collapsed ? 0 : 20, flexWrap: "wrap", gap: 8 }}>
        <button
          onClick={() => setCollapsed(c => !c)}
          style={{
            display: "flex", alignItems: "center", gap: 10, background: "none", border: "none",
            padding: 0, cursor: "pointer", textAlign: "left",
          }}
          aria-expanded={!collapsed}
          title={collapsed ? "Expand" : "Collapse"}
        >
          <div style={{
            width: 34, height: 34, borderRadius: 10,
            background: "linear-gradient(135deg, #1B5E43 0%, #123828 100%)",
            display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
          }}>
            <Calendar size={16} style={{ color: "#C9A24B" }} />
          </div>
          <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 16, color: "var(--color-text)" }}>
            Vaccination Timeline
          </span>
          {collapsed ? <ChevronDown size={16} style={{ color: "var(--color-text-muted)" }} /> : <ChevronUp size={16} style={{ color: "var(--color-text-muted)" }} />}
        </button>
        {!collapsed && (
          <div style={{
            display: "flex", background: "var(--color-bg)", borderRadius: 10,
            border: "1px solid var(--color-border)", overflow: "hidden", padding: 3, gap: 3,
          }}>
            <button
              onClick={() => setViewMode("age")}
              style={{
                padding: "5px 14px", fontSize: 12, fontWeight: 600, cursor: "pointer",
                border: "none", borderRadius: 7,
                background: viewMode === "age" ? "var(--color-surface)" : "transparent",
                color: viewMode === "age" ? "var(--color-primary)" : "var(--color-text-muted)",
                boxShadow: viewMode === "age" ? "0 1px 4px rgba(0,0,0,0.1)" : "none",
              }}
            >Group by age</button>
            <button
              onClick={() => setViewMode("date")}
              style={{
                padding: "5px 14px", fontSize: 12, fontWeight: 600, cursor: "pointer",
                border: "none", borderRadius: 7,
                background: viewMode === "date" ? "var(--color-surface)" : "transparent",
                color: viewMode === "date" ? "var(--color-primary)" : "var(--color-text-muted)",
                boxShadow: viewMode === "date" ? "0 1px 4px rgba(0,0,0,0.1)" : "none",
              }}
            >By date</button>
          </div>
        )}
      </div>

      {collapsed ? null : (
      <>
      {/* Inline upload form (triggered by "Add outside vaccination" sidebar button) */}
      {uploadFor === "" && (
        <UploadVaccinationForm
          patientAwpid={patientAwpid}
          onCancel={() => setUploadFor(null)}
          onDone={() => { setUploadFor(null); refetchVax(); }}
        />
      )}

      {vaxLoading ? (
        <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>Loading…</div>
      ) : !hasData ? (
        <div style={{
          textAlign: "center", padding: "40px 24px",
          color: "var(--color-text-muted)",
        }}>
          <div style={{
            width: 56, height: 56, borderRadius: 16, margin: "0 auto 16px",
            background: "var(--color-primary-light)",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <Calendar size={24} style={{ color: "var(--color-primary)" }} />
          </div>
          <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 15, color: "var(--color-text)", marginBottom: 6 }}>
            No vaccination records yet
          </div>
          <div style={{ fontSize: 13, lineHeight: 1.6, marginBottom: 20 }}>
            Add previous records to build your vaccination history,<br />
            or create a plan with your doctor.
          </div>
          <button
            onClick={() => setUploadFor("")}
            style={{
              background: "var(--color-primary)", color: "#fff",
              border: "none", borderRadius: 10, padding: "9px 20px",
              fontSize: 13, fontWeight: 600, cursor: "pointer",
            }}
          >
            Add Records
          </button>
        </div>
      ) : (
        <div>
          {(() => {
            const needsReviewGroup = groups.find(g => g.type === "needs_review");
            const needsReviewHiddenCount = needsReviewGroup
              ? Math.max(0, needsReviewGroup.items.length - VAX_PREVIEW_COUNT)
              : 0;
            const visibleGroups = showAll ? groups : groups.slice(0, GROUP_PREVIEW_COUNT);
            const hiddenGroupCount = Math.max(0, groups.length - GROUP_PREVIEW_COUNT);
            return (
          <>
          {visibleGroups.map((group, groupIdx) => {
            const milestoneStatus = getMilestoneStatus(group);
            const isLast = groupIdx === visibleGroups.length - 1;
            const ageRange = MILESTONE_AGES[group.label];
            // The "Needs Review" group is the one that can run long (every
            // vaccine with no record at all lands here) — that's what the
            // "View all vaccines" toggle below is actually for. The
            // showAll state existed before but nothing ever consumed it, so
            // clicking the button relabeled itself and did nothing; this is
            // what makes it actually hide/show rows.
            const isPreviewable = group.type === "needs_review";
            const visibleItems = isPreviewable && !showAll
              ? group.items.slice(0, VAX_PREVIEW_COUNT)
              : group.items;

            // Circle marker config per milestone status
            const circleConfig = milestoneStatus === "completed"
              ? { bg: "var(--color-success)", border: "var(--color-success)", type: "check" }
              : milestoneStatus === "upcoming"
              ? { bg: "#fff", border: "var(--color-warning)", type: "dot" }
              : { bg: "#F1E9FA", border: "#6B3FA0", type: "question" };

            return (
              <div key={group.label} style={{ display: "flex", gap: 14 }}>
                {/* Vertical timeline column */}
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", width: 26, flexShrink: 0, paddingTop: 2 }}>
                  <div style={{
                    width: 26, height: 26, borderRadius: "50%", flexShrink: 0,
                    background: circleConfig.bg,
                    border: `2px solid ${circleConfig.border}`,
                    display: "flex", alignItems: "center", justifyContent: "center",
                  }}>
                    {circleConfig.type === "check" && (
                      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                        <path d="M2 6.5L4.5 9L10 3" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                      </svg>
                    )}
                    {circleConfig.type === "dot" && (
                      <div style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--color-warning)" }} />
                    )}
                    {circleConfig.type === "question" && (
                      <span style={{ fontSize: 13, fontWeight: 700, color: "#6B3FA0", lineHeight: 1 }}>?</span>
                    )}
                  </div>
                  {!isLast && (
                    <div style={{ flex: 1, width: 2, background: "var(--color-border)", margin: "3px 0", minHeight: 24 }} />
                  )}
                </div>

                {/* Milestone content */}
                <div style={{ flex: 1, paddingBottom: isLast ? 0 : 22, minWidth: 0 }}>
                  {/* Milestone label */}
                  <div style={{ marginBottom: 10, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <span style={{
                      fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 14,
                      color: milestoneStatus === "completed" ? "var(--color-primary)"
                           : milestoneStatus === "upcoming" ? "var(--color-warning)"
                           : "#6B3FA0",
                    }}>
                      {group.label}
                    </span>
                    {ageRange && (
                      <span style={{
                        fontSize: 11, fontWeight: 600, padding: "2px 8px", borderRadius: 20,
                        background: milestoneStatus === "completed" ? "var(--color-success-light)"
                                  : milestoneStatus === "upcoming" ? "var(--color-warning-light)"
                                  : "#F1E9FA",
                        color: milestoneStatus === "completed" ? "var(--color-success)"
                             : milestoneStatus === "upcoming" ? "var(--color-warning)"
                             : "#6B3FA0",
                      }}>
                        {ageRange}
                      </span>
                    )}
                    {group.type === "needs_review" && (
                      <span style={{
                        fontSize: 11, fontWeight: 600, padding: "2px 8px", borderRadius: 20,
                        background: "#F1E9FA", color: "#6B3FA0",
                      }}>
                        Records not available
                      </span>
                    )}
                  </div>

                  {/* Vaccine rows */}
                  <div style={{ display: "grid", gap: 8 }}>
                    {visibleItems.map((v, i) => {
                      const bucket = vaxBucket(v);
                      const pill = PILL_STYLE[bucket];
                      const canUpload = !v.record_id
                        ? v.status === "unknown"
                        : v.verification_status === "rejected";
                      const showBook = v.status === "ordered" ||
                        (v.status === "unknown" && v.timing === "upcoming" && group.type !== "needs_review");

                      // Color-coded left border + subtle background by status
                      const rowStyle = bucket === "Completed"
                        ? { borderLeft: "4px solid var(--color-success)", background: "#FAFDFB" }
                        : bucket === "Upcoming"
                        ? { borderLeft: "4px solid var(--color-warning)", background: "#FEFCF5" }
                        : { borderLeft: "4px solid #9B6FD4", background: "#FDFAFF" };

                      return (
                        <div key={i} style={{
                          display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8,
                          border: "1px solid var(--color-border)", borderRadius: 10, padding: "10px 14px",
                          transition: "box-shadow 0.15s",
                          ...rowStyle,
                        }}>
                          <div style={{ minWidth: 0, flex: 1 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                              <span style={{ fontSize: 13, fontWeight: 600, color: "var(--color-text)" }}>{v.vaccine_name}</span>
                              {group.type === "needs_review" ? (
                                <span style={{
                                  fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 8,
                                  background: "#EDE9FE", color: "#6B3FA0",
                                }}>No record</span>
                              ) : (
                                <span style={{
                                  fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 10,
                                  background: pill.bg, color: pill.color, whiteSpace: "nowrap",
                                }}>{pill.label}</span>
                              )}
                            </div>
                            {bucket === "Completed" && v.administered_date && (
                              <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 4, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                                <svg width="10" height="10" viewBox="0 0 10 10" fill="none" style={{ flexShrink: 0 }}>
                                  <rect x="0.5" y="1.5" width="9" height="7.5" rx="1" stroke="currentColor" strokeWidth="1"/>
                                  <path d="M3 0.5V2M7 0.5V2M0.5 4H9.5" stroke="currentColor" strokeWidth="1" strokeLinecap="round"/>
                                </svg>
                                {new Date(v.administered_date).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}
                                {v.verified_by_name && ` • ${v.verified_by_name}`}
                                {v.verification_status === "verified" && (
                                  <span style={{
                                    fontSize: 9, padding: "2px 7px", borderRadius: 5,
                                    background: "var(--color-info-light)", color: "var(--color-info)", fontWeight: 700,
                                  }}>✓ Verified</span>
                                )}
                              </div>
                            )}
                            {bucket === "Upcoming" && v.due_date && (
                              <div style={{ fontSize: 11, color: "var(--color-warning)", fontWeight: 600, marginTop: 4 }}>
                                Due on {new Date(v.due_date).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}
                              </div>
                            )}
                          </div>

                          <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
                            {v.has_certificate && v.record_id && <ViewCertificateButton recordId={v.record_id} />}
                            {showBook && (
                              <button
                                onClick={() => navigate(ROUTES.PATIENT.HOSPITALS)}
                                style={{
                                  padding: "5px 12px", fontSize: 11, fontWeight: 600, whiteSpace: "nowrap",
                                  background: "var(--color-primary)", color: "#fff",
                                  border: "none", borderRadius: 8, cursor: "pointer",
                                }}
                              >
                                Book Appointment
                              </button>
                            )}
                            {!showBook && canUpload && (
                              <button
                                onClick={() => { setUploadFor(v.vaccine_name); setUploadForLabel(v.scheduled_label || ""); }}
                                style={{
                                  padding: "5px 12px", fontSize: 11, fontWeight: 600,
                                  background: "transparent", color: "#6B3FA0",
                                  border: "1.5px solid #9B6FD4", borderRadius: 8, cursor: "pointer",
                                }}
                              >
                                Add Record
                              </button>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            );
          })}

          {(hiddenGroupCount > 0 || needsReviewHiddenCount > 0 || showAll) && (
            <button
              onClick={() => setShowAll(s => !s)}
              style={{
                display: "flex", alignItems: "center", gap: 6, margin: "16px auto 0",
                background: "var(--color-primary-light)", color: "var(--color-primary)",
                border: "1.5px solid var(--color-primary)", borderRadius: 20,
                padding: "7px 20px", fontSize: 12, fontWeight: 700, cursor: "pointer",
                transition: "background 0.15s",
              }}
            >
              {showAll
                ? "Show less"
                : hiddenGroupCount > 0
                ? `View full timeline (+${hiddenGroupCount} more)`
                : `View all vaccines (+${needsReviewHiddenCount})`}
              {showAll ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            </button>
          )}
          </>
            );
          })()}
        </div>
      )}

      {uploadFor && uploadFor !== "" && (
        <UploadVaccinationForm
          patientAwpid={patientAwpid}
          prefillVaccine={uploadFor}
          prefillLabel={uploadForLabel}
          onCancel={() => { setUploadFor(null); setUploadForLabel(""); }}
          onDone={() => { setUploadFor(null); setUploadForLabel(""); refetchVax(); }}
        />
      )}
      </>
      )}
    </div>
  );
}

// Tab definitions — id maps to the rendered panel below.
// The "vaccinations" tab is only shown for patients under 18.
const ALL_TABS = [
  { id: "vaccinations",    label: "Vaccinations",    icon: Syringe,   pediatricOnly: true },
  { id: "health-timeline", label: "Health Timeline",  icon: Activity,  pediatricOnly: false },
  { id: "visits",          label: "Visits",           icon: Building2, pediatricOnly: false },
  { id: "growth",          label: "Growth",           icon: TrendingUp, pediatricOnly: false },
];

function TabBar({ active, onChange, isAdult }) {
  const tabs = ALL_TABS.filter(t => !(isAdult && t.pediatricOnly));
  return (
    <div style={{
      background: "var(--color-surface)",
      border: "1px solid var(--color-border)",
      borderRadius: 14,
      padding: "6px 8px",
      display: "flex", gap: 4,
      marginBottom: 20,
      overflowX: "auto",
      boxShadow: "var(--shadow-card)",
    }}>
      {tabs.map(tab => {
        const isActive = tab.id === active;
        const Icon = tab.icon;
        return (
          <button
            key={tab.id}
            onClick={() => onChange(tab.id)}
            style={{
              padding: "8px 18px", fontSize: 13, fontWeight: isActive ? 700 : 500,
              cursor: "pointer", border: "none", borderRadius: 10,
              whiteSpace: "nowrap", transition: "all 0.15s ease",
              display: "inline-flex", alignItems: "center", gap: 7,
              background: isActive
                ? "linear-gradient(135deg, #1B5E43 0%, #123828 100%)"
                : "transparent",
              color: isActive ? "#F4F1E8" : "var(--color-text-muted)",
              boxShadow: isActive ? "0 2px 8px rgba(15,61,43,0.25)" : "none",
            }}
          >
            {Icon && <Icon size={15} />}
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

export default function PatientRecordsPage() {
  const [searchParams] = useSearchParams();
  const { selectedPatient, selectPatient, familyMembers } = usePatientContext();
  const [activeTab, setActiveTab] = useState("vaccinations");
  const [tabInitialized, setTabInitialized] = useState(false);

  useEffect(() => {
    const qAwpid = searchParams.get("patient_awpid") || "";
    const qName  = searchParams.get("patient_name") || "";
    if (qAwpid) selectPatient(qAwpid, qName);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const patientAwpid = selectedPatient.awpid || "";
  const patientName  = selectedPatient.isSelf ? "" : selectedPatient.name;
  const params = patientAwpid ? { patient_awpid: patientAwpid } : {};

  const [uploadFor, setUploadFor] = useState(null);
  // Which schedule slot (e.g. "Birth", "6 Weeks") the open upload form is
  // fulfilling, if any — see UploadVaccinationForm's scheduled_label note.
  // Free-form opens (sidebar Upload Card / Enter Manually / this page's
  // openVaccineUpload) always pass "" since they're not tied to a slot.
  const [uploadForLabel, setUploadForLabel] = useState("");
  const vaxSectionRef = useRef(null);

  function openVaccineUpload(vaccineName) {
    if (vaccineName != null) { setUploadFor(vaccineName); setUploadForLabel(""); }
    setActiveTab("vaccinations");
    setTimeout(() => vaxSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  }

  const { data: summary, isLoading: summaryLoading, error: summaryError } =
    useApi(API_ENDPOINTS.PORTAL.HEALTH_SUMMARY, { params });
  const { data: growth, isLoading: growthLoading } =
    useApi(API_ENDPOINTS.PORTAL.GROWTH, { params });

  // Vaccination schedule is only applicable for patients under 18.
  // Once age is known, redirect away from the vaccinations tab if adult.
  const ageYears = growth?.age_years ?? null;
  const isAdult  = ageYears !== null && ageYears >= 18;

  useEffect(() => {
    if (ageYears === null || tabInitialized) return;
    if (isAdult && activeTab === "vaccinations") setActiveTab("health-timeline");
    setTabInitialized(true);
  }, [ageYears]); // eslint-disable-line react-hooks/exhaustive-deps
  const { data: vax, isLoading: vaxLoading, refetch: refetchVax } =
    useApi(API_ENDPOINTS.PORTAL.VACCINATIONS, { params });
  const { data: profile } = useApi(API_ENDPOINTS.PORTAL.PROFILE, { skip: !selectedPatient.isSelf });

  const familyMember = !selectedPatient.isSelf
    ? (familyMembers || []).find(m => m.awpid === patientAwpid)
    : null;
  const heroGender = selectedPatient.isSelf ? (profile?.gender || "") : (familyMember?.gender || "");
  const heroPhoto  = selectedPatient.isSelf ? (profile?.photo || "") : "";

  const { items: records, isLoading: recordsLoading, isLoadingMore, hasMore, loadMore } =
    usePaginatedList(API_ENDPOINTS.PORTAL.MY_RECORDS, { pageSize: 20, params });

  return (
    <AppShell>
      <PageShell title={patientName ? `${patientName}'s Health Journey` : "My Health Journey"}>
        <style>{`
          @media (max-width: 900px) {
            .vax-stats-grid { grid-template-columns: repeat(2, 1fr) !important; }
            .vax-two-col    { grid-template-columns: 1fr !important; }
          }
        `}</style>

        {/* Patient profile header — always visible across all tabs */}
        <HealthSummaryCard
          patientAwpid={patientAwpid}
          displayName={patientName || summary?.patient_name}
          photo={heroPhoto}
          gender={heroGender}
          summary={summary}
          summaryLoading={summaryLoading}
          summaryError={summaryError}
          growth={growth}
          vax={vax}
          onAddRecords={() => openVaccineUpload("")}
        />

        {/* Tab switcher */}
        <TabBar active={activeTab} onChange={setActiveTab} isAdult={isAdult} />

        {/* ── Vaccinations tab (children under 18 only) ──────────── */}
        {activeTab === "vaccinations" && !isAdult && (
          <>
            <VaccinationStats vax={vax} />
            {/* One grid, two independently-flowing columns — each column is
                its own stack (Chart+Timeline on the left, Recommended by
                Doctor+rest of the sidebar on the right), not a synchronized
                2-row grid. A synchronized grid left a large empty gap under
                "Recommended by Doctor" whenever the chart (left column) was
                taller than it, because the second row couldn't start until
                the first row — sized to the taller left cell — finished.
                Independent column stacks let the right column's cards sit
                flush against each other regardless of the chart's height. */}
            <div className="vax-two-col" style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 20, alignItems: "start" }}>
              <div style={{ display: "grid", gap: 20 }}>
                <GrowthVaccinationChart
                  growth={growth}
                  growthLoading={growthLoading}
                  roadmap={vax?.roadmap}
                  roadmapLoading={vaxLoading}
                />
                <VaccinationTimeline
                  patientAwpid={patientAwpid}
                  vax={vax}
                  vaxLoading={vaxLoading}
                  refetchVax={refetchVax}
                  uploadFor={uploadFor}
                  setUploadFor={setUploadFor}
                  uploadForLabel={uploadForLabel}
                  setUploadForLabel={setUploadForLabel}
                  vaxSectionRef={vaxSectionRef}
                />
              </div>
              <div style={{ display: "grid", gap: 16, alignContent: "start" }}>
                <RecommendedByDoctor roadmap={vax?.roadmap} />
                <VaccinationSidebar
                  patientAwpid={patientAwpid}
                  onOpenUpload={openVaccineUpload}
                />
              </div>
            </div>
          </>
        )}

        {/* ── Health Timeline tab ────────────────────────────────── */}
        {activeTab === "health-timeline" && (
          <HealthTimeline patientAwpid={patientAwpid} />
        )}

        {/* ── Visits tab ────────────────────────────────────────── */}
        {activeTab === "visits" && (
          recordsLoading ? (
            <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>
              Loading visits…
            </div>
          ) : records.length === 0 ? (
            <div className="card" style={{ padding: 44, textAlign: "center" }}>
              <div style={{ fontFamily: "var(--font-display)", fontSize: 18, fontWeight: 600, marginBottom: 6 }}>
                No visits yet
              </div>
              <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
                Your consultation history will appear here after each hospital visit.
              </div>
            </div>
          ) : (
            <div style={{ display: "grid", gap: 12 }}>
              {records.map((r, i) => (
                <div key={i} style={{
                  background: "var(--color-surface)",
                  border: "1px solid var(--color-border)",
                  borderRadius: 16,
                  overflow: "hidden",
                  boxShadow: "var(--shadow-card)",
                }}>
                  {/* Card header strip */}
                  <div style={{
                    background: "linear-gradient(90deg, #F5F1E9 0%, var(--color-surface) 100%)",
                    borderBottom: "1px solid var(--color-border)",
                    padding: "12px 18px",
                    display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12,
                  }}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 15, color: "var(--color-text)" }}>
                        {r.hospital}
                      </div>
                      <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 2 }}>
                        Dr. {r.doctor} · {r.date}{r.time ? ` · ${r.time}` : ""}
                      </div>
                    </div>
                    <span className={`badge ${BADGE[r.status] || "badge--neutral"}`} style={{ flexShrink: 0 }}>
                      {r.status?.replace("_", " ")}
                    </span>
                  </div>

                  {/* Card body */}
                  <div style={{ padding: "12px 18px", display: "grid", gap: 8 }}>
                    {r.chief_complaint && (
                      <div style={{
                        fontSize: 13, fontStyle: "italic", color: "var(--color-text-secondary)",
                        borderLeft: "3px solid var(--color-accent)", paddingLeft: 10,
                      }}>
                        "{r.chief_complaint}"
                      </div>
                    )}

                    {r.vitals && (
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                        {[
                          r.vitals.bp          && `BP ${r.vitals.bp}`,
                          r.vitals.pulse       && `Pulse ${r.vitals.pulse}`,
                          r.vitals.spo2        && `SpO₂ ${r.vitals.spo2}%`,
                          r.vitals.temperature && `Temp ${r.vitals.temperature}°F`,
                          r.vitals.weight_kg   && `${r.vitals.weight_kg} kg`,
                        ].filter(Boolean).map(v => (
                          <span key={v} style={{
                            fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 20,
                            background: "var(--color-info-light)", color: "var(--color-info)",
                            border: "1px solid #AECAD8",
                          }}>{v}</span>
                        ))}
                      </div>
                    )}

                    {(r.diagnoses || []).length > 0 && (
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                        {r.diagnoses.map((d, di) => (
                          <span key={di} className="badge badge--primary">{d.code} — {d.description}</span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
              {hasMore && (
                <button
                  onClick={loadMore}
                  disabled={isLoadingMore}
                  className="btn-outline"
                  style={{ justifySelf: "center", padding: "9px 24px", fontSize: 13 }}
                >
                  {isLoadingMore ? "Loading…" : "Load more"}
                </button>
              )}
            </div>
          )
        )}

        {/* ── Growth tab ────────────────────────────────────────── */}
        {/* Same upgraded chart as the Vaccinations tab (gridlines, hover
            tooltips, latest-value readout) instead of the old bare-bones
            mini line charts with no axis at all — this tab is reachable by
            every patient, adult or pediatric, so vaccination markers are
            only passed through for minors (an adult's "roadmap" is just
            the reference schedule with no real relevance to them). */}
        {activeTab === "growth" && (
          <GrowthVaccinationChart
            growth={growth}
            growthLoading={growthLoading}
            roadmap={isAdult ? [] : vax?.roadmap}
            roadmapLoading={isAdult ? false : vaxLoading}
          />
        )}
      </PageShell>
    </AppShell>
  );
}
