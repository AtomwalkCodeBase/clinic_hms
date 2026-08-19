/**
 * components/layout/AppShell.jsx
 * --------------------------------
 * Authenticated page shell — sidebar with grouped submenus + topbar + content.
 *
 * Nav item types:
 *   { type: "link",    label, icon, to }                       — direct NavLink
 *   { type: "group",   label, icon, children: [{label, to}] }  — expandable submenu
 *   { type: "section", label }                                  — non-clickable divider label
 */

import { useState, useEffect, useContext } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useAuth }   from "../../hooks/useAuth";
import { useToast }  from "../../hooks/useToast";
import { ROLES, ROLE_LABELS, ACTS_AS_PRIORITY } from "../../constants/roles";
import { ROUTES }    from "../../config/routes.config";
import APP_CONFIG    from "../../config/app.config";
import { PatientContext } from "../../context/PatientContext";
import { ThemeSwitcher } from "./ThemeSwitcher";

// ── Icons (inline SVG so no extra dep needed) ────────────────────────────────
const Icon = ({ d, size = 18, style = {}, className }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
    className={className}
    style={{ minWidth: size, ...style }}>
    <path d={d} />
  </svg>
);

const ICONS = {
  dashboard:  "M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z",
  staff:      "M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2M9 11a4 4 0 100-8 4 4 0 000 8zM23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75",
  branch:     "M3 9h18M3 15h18M9 3v18M15 3v18M3 3h18v18H3z",
  room:       "M4 21V7a2 2 0 012-2h8a2 2 0 012 2v14M4 21h16M9 21V11h4v10M14 7h4a2 2 0 012 2v12",
  opd:        "M20.84 4.61a5.5 5.5 0 00-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 00-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 000-7.78z",
  queue:      "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  patient:    "M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2M12 11a4 4 0 100-8 4 4 0 000 8z",
  appointments: "M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V6a2 2 0 012-2z",
  lab:        "M9 3H5a2 2 0 00-2 2v4m6-6h10a2 2 0 012 2v4M9 3v11l3 3 3-3V3M5 9H3m18 0h-2",
  pharmacy:   "M9 3h6l1 7H8L9 3zM8 10v9a1 1 0 001 1h6a1 1 0 001-1v-9",
  billing:    "M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8zM14 2v6h6M16 13H8M16 17H8M10 9H8",
  reports:    "M18 20V10M12 20V4M6 20v-6",
  settings:   "M12 15a3 3 0 100-6 3 3 0 000 6zM19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z",
  hospitals:  "M3 9h18M3 15h18M9 3v18M15 3v18",
  subscriptions: "M21 4H3a2 2 0 00-2 2v12a2 2 0 002 2h18a2 2 0 002-2V6a2 2 0 00-2-2zM1 10h22",
  vitals:     "M22 12h-4l-3 9L9 3l-3 9H2",
  tasks:      "M9 11l3 3L22 4M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11",
  prescription: "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01",
  stock:      "M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4",
  records:    "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z",
  logout:     "M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9",
  chevronDown:"M6 9l6 6 6-6",
  chevronRight:"M9 18l6-6-6-6",
  collapse:   "M11 19l-7-7 7-7m8 14l-7-7 7-7",
  expand:     "M13 5l7 7-7 7M5 5l7 7-7 7",
  platform:   "M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5",
  doctor:     "M22 12h-4l-3 9L9 3l-3 9H2",
  history:    "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z",
  analytics:  "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z",
  ai:         "M12 2a2 2 0 012 2v2a2 2 0 01-2 2 2 2 0 01-2-2V4a2 2 0 012-2zM12 16a2 2 0 012 2v2a2 2 0 01-2 2 2 2 0 01-2-2v-2a2 2 0 012-2zM4 12a2 2 0 012-2h2a2 2 0 010 4H6a2 2 0 01-2-2zM16 12a2 2 0 012-2h2a2 2 0 010 4h-2a2 2 0 01-2-2z",
  users:      "M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2M9 11a4 4 0 100-8 4 4 0 000 8zM23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75",
  vaccination: "M12 2L4 5v6c0 5.55 3.84 10.74 8 12 4.16-1.26 8-6.45 8-12V5l-8-3zm-1 14l-3-3 1.41-1.41L11 13.17l4.59-4.58L17 10l-6 6z",
  bell:       "M18 8a6 6 0 10-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 01-3.46 0",
  compliance: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
};

// ── Hospital monogram (fallback logo) ────────────────────────────────────────
// Every hospital gets its own deterministic colored monogram (initials + a
// color derived from its own name/id) until it uploads a real logo file —
// distinct per hospital, unlike a single shared placeholder icon.
const MONOGRAM_COLORS = ["#1B5E43", "#0F766E", "#7C3AED", "#B45309", "#BE123C", "#0369A1", "#4D7C0F"];
const MONOGRAM_STOPWORDS = new Set(["hospital", "clinic", "multispecialty", "medical", "center", "centre", "care", "health", "the", "and"]);

function hospitalInitials(name) {
  const words = (name || "").split(/\s+/).filter(w => w && !MONOGRAM_STOPWORDS.has(w.toLowerCase()));
  const source = words.length ? words : (name || "H").split(/\s+/).filter(Boolean);
  return source.slice(0, 2).map(w => w[0]?.toUpperCase() || "").join("") || "H";
}

function HospitalMonogram({ name, tenantId }) {
  const seed = tenantId != null ? Number(tenantId) : (name || "").split("").reduce((a, c) => a + c.charCodeAt(0), 0);
  const color = MONOGRAM_COLORS[Math.abs(seed) % MONOGRAM_COLORS.length];
  return (
    <div style={{
      width: 38, height: 38, borderRadius: "50%",
      background: "#fff", overflow: "hidden", flexShrink: 0,
      display: "flex", alignItems: "center", justifyContent: "center",
    }}>
      <div style={{
        width: 32, height: 32, borderRadius: "50%", background: color,
        display: "flex", alignItems: "center", justifyContent: "center",
        color: "#fff", fontWeight: 700, fontSize: 13, fontFamily: "var(--font-display)",
      }}>
        {hospitalInitials(name)}
      </div>
    </div>
  );
}

// Real uploaded hospital logo (Tenant.logo, set via hospital-admin Settings)
// takes over from the monogram the moment one exists — same 38px badge
// footprint so the topbar layout doesn't shift either way.
function HospitalBadge({ logo, name, tenantId }) {
  if (!logo) return <HospitalMonogram name={name} tenantId={tenantId} />;
  return (
    <div style={{
      width: 38, height: 38, borderRadius: "50%",
      background: "#fff", overflow: "hidden", flexShrink: 0,
      display: "flex", alignItems: "center", justifyContent: "center",
    }}>
      <img src={logo} alt={name || "Hospital logo"}
        style={{ width: "84%", height: "84%", objectFit: "contain" }} />
    </div>
  );
}

// ── Nav definitions ───────────────────────────────────────────────────────────
const NAV_BY_ROLE = {
  [ROLES.PLATFORM_ADMIN]: [
    { type: "link",  label: "Dashboard",     iconKey: "dashboard",     to: ROUTES.PLATFORM.DASHBOARD },
    { type: "link",  label: "Hospitals",      iconKey: "hospitals",     to: ROUTES.PLATFORM.HOSPITALS },
    { type: "link",  label: "Subscriptions",  iconKey: "subscriptions", to: ROUTES.PLATFORM.SUBSCRIPTIONS },
    { type: "link",  label: "Users",          iconKey: "users",         to: ROUTES.PLATFORM.USERS },
    { type: "link",  label: "Vaccination Templates", iconKey: "vaccination", to: ROUTES.PLATFORM.VACCINATION_TEMPLATES },
  ],

  [ROLES.HOSPITAL_ADMIN]: [
    { type: "link",    label: "Dashboard",    iconKey: "dashboard",  to: ROUTES.ADMIN.DASHBOARD },
    { type: "section", label: "Management" },
    { type: "group",   label: "Staff",        iconKey: "staff", children: [
      { label: "Staff List", iconKey: "staff",  to: ROUTES.ADMIN.STAFF },
      { label: "Branches",   iconKey: "branch", to: ROUTES.ADMIN.BRANCHES },
      { label: "Rooms & Floors", iconKey: "room", to: ROUTES.ADMIN.ROOMS },
      { label: "Roles & Permissions", iconKey: "settings", to: ROUTES.ADMIN.ROLES },
      { label: "Vaccination Schedule", iconKey: "settings", to: ROUTES.ADMIN.VACCINATION_SCHEDULE },
    ]},
    { type: "link",    label: "Billing Setup", iconKey: "billing", to: ROUTES.ADMIN.SERVICES },
    { type: "link",    label: "Billing Reports", iconKey: "reports", to: ROUTES.ADMIN.BILLING_REPORTS },
    { type: "link",    label: "Compliance",   iconKey: "compliance", to: ROUTES.ADMIN.COMPLIANCE },
    { type: "section", label: "System" },
    { type: "link",    label: "Settings",     iconKey: "settings", to: ROUTES.ADMIN.SETTINGS },
    { type: "link",    label: "My Profile",   iconKey: "settings", to: ROUTES.ADMIN.MY_PROFILE },
  ],

  [ROLES.DOCTOR]: [
    { type: "link",    label: "Dashboard",    iconKey: "dashboard", to: ROUTES.DOCTOR.DASHBOARD },
    { type: "section", label: "OPD" },
    { type: "link",    label: "My Queue",     iconKey: "queue",     to: ROUTES.DOCTOR.QUEUE },
    { type: "link",    label: "Patients",     iconKey: "patient",   to: ROUTES.DOCTOR.PATIENTS },
    { type: "link",    label: "History",      iconKey: "history",   to: ROUTES.DOCTOR.HISTORY },
    // NOTE: no separate "Laboratory" or "Prescriptions" links here — both
    // used to point at the lab-tech's and pharmacist's own working-queue
    // pages (ROUTES.LAB.REQUESTS/REPORTS, ROUTES.PHARMACIST.PRESCRIPTIONS),
    // which are role-gated to lab_tech/pharmacist (+ hospital_admin) only in
    // App.jsx. A doctor clicking either link got silently bounced back to
    // their dashboard by ProtectedRoute — and even with access, those pages
    // are lab-tech/pharmacist WRITE queues (mark collected, upload result,
    // dispense), not something a doctor should be driving. Doctors already
    // see lab results and write prescriptions in context, per-patient,
    // inside EncounterPage/HistoryPage — that's the correct doctor-facing
    // surface for both, so the dead links were removed rather than granted
    // write access to another role's queue.
    { type: "section", label: "Schedule" },
    { type: "link",    label: "Appointments",  iconKey: "appointments", to: ROUTES.FRONT_DESK.APPOINTMENTS },
    { type: "section", label: "Account" },
    { type: "link",    label: "My Profile",    iconKey: "settings",     to: ROUTES.DOCTOR.MY_PROFILE },
  ],

  [ROLES.NURSE]: [
    { type: "link",  label: "Dashboard",  iconKey: "dashboard", to: ROUTES.NURSE.DASHBOARD },
    { type: "link",  label: "Vitals",     iconKey: "vitals",    to: ROUTES.NURSE.VITALS },
    { type: "link",  label: "Tasks",      iconKey: "tasks",     to: ROUTES.NURSE.TASKS },
    { type: "link",  label: "History",    iconKey: "history",   to: ROUTES.NURSE.HISTORY },
    { type: "link",  label: "My Profile", iconKey: "settings",  to: ROUTES.NURSE.MY_PROFILE },
  ],

  [ROLES.FRONT_DESK]: [
    { type: "link",    label: "Dashboard",       iconKey: "dashboard",    to: ROUTES.FRONT_DESK.DASHBOARD },
    { type: "section", label: "Patients" },
    { type: "link",    label: "Register Patient", iconKey: "patient",      to: ROUTES.FRONT_DESK.REGISTER_PATIENT },
    { type: "link",    label: "All Patients",     iconKey: "users",        to: ROUTES.FRONT_DESK.PATIENTS },
    { type: "link",    label: "Appointments",     iconKey: "appointments", to: ROUTES.FRONT_DESK.APPOINTMENTS },
    { type: "link",    label: "OPD Queue",        iconKey: "queue",        to: ROUTES.FRONT_DESK.QUEUE },
    { type: "link",    label: "History",          iconKey: "history",      to: ROUTES.FRONT_DESK.HISTORY },
    { type: "section", label: "Finance" },
    { type: "link",    label: "Billing",          iconKey: "billing",      to: ROUTES.FRONT_DESK.BILLING },
    { type: "section", label: "Account" },
    { type: "link",    label: "My Profile",       iconKey: "settings",     to: ROUTES.FRONT_DESK.MY_PROFILE },
  ],

  [ROLES.LAB_TECH]: [
    { type: "link",    label: "Dashboard",  iconKey: "dashboard", to: ROUTES.LAB.DASHBOARD },
    { type: "section", label: "Work" },
    { type: "link",    label: "Requests",   iconKey: "lab",       to: ROUTES.LAB.REQUESTS },
    { type: "link",    label: "Reports",    iconKey: "reports",   to: ROUTES.LAB.REPORTS },
    { type: "section", label: "Catalogue" },
    { type: "link",    label: "Test Catalog", iconKey: "tasks",   to: ROUTES.LAB.CATALOG },
    { type: "section", label: "Account" },
    { type: "link",    label: "My Profile",   iconKey: "settings", to: ROUTES.LAB.MY_PROFILE },
  ],

  [ROLES.PHARMACIST]: [
    { type: "link",    label: "Dashboard",     iconKey: "dashboard",    to: ROUTES.PHARMACIST.DASHBOARD },
    { type: "section", label: "Dispensary" },
    { type: "link",    label: "Prescriptions", iconKey: "prescription", to: ROUTES.PHARMACIST.PRESCRIPTIONS },
    { type: "section", label: "Inventory" },
    { type: "link",    label: "Stock",         iconKey: "stock",        to: ROUTES.PHARMACIST.STOCK },
    { type: "section", label: "Catalogue" },
    { type: "link",    label: "Drug Catalog Setup", iconKey: "tasks",   to: ROUTES.PHARMACIST.CATALOG },
    { type: "link",    label: "Drug Form Setup", iconKey: "tasks",      to: ROUTES.PHARMACIST.DRUG_FORM_SETUP },
    { type: "section", label: "Account" },
    { type: "link",    label: "My Profile",    iconKey: "settings",     to: ROUTES.PHARMACIST.MY_PROFILE },
  ],

  [ROLES.PATIENT]: [
    { type: "section", label: "My Health" },
    { type: "link",  label: "Dashboard",     iconKey: "dashboard",    to: ROUTES.PATIENT.DASHBOARD },
    { type: "link",  label: "Appointments",  iconKey: "appointments", to: ROUTES.PATIENT.APPOINTMENTS },
    { type: "link",  label: "My Health Journey", iconKey: "records",  to: ROUTES.PATIENT.RECORDS },
    { type: "link",  label: "Prescriptions", iconKey: "prescription", to: ROUTES.PATIENT.PRESCRIPTIONS },
    { type: "link",  label: "Lab Reports",   iconKey: "lab",          to: ROUTES.PATIENT.LAB_REPORTS },
    { type: "link",  label: "Notifications", iconKey: "bell",         to: ROUTES.PATIENT.NOTIFICATIONS },
    { type: "section", label: "Family Members" },
    { type: "family-list" },
    { type: "section", label: "Account" },
    { type: "link",  label: "My Profile",    iconKey: "settings",     to: ROUTES.PATIENT.MY_PROFILE },
    { type: "link",  label: "Request a Correction", iconKey: "compliance", to: ROUTES.PATIENT.CORRECTION_REQUESTS },
  ],
};

// ── Helpers ──────────────────────────────────────────────────────────────────
/** Given a group's children, return true if any child path matches current location */
function isGroupActive(children, pathname) {
  return children.some(c => pathname.startsWith(c.to));
}

// Priority order for picking which single role's Dashboard link leads a
// custom-role user's sidebar — hospital_admin's is the fullest overview, so
// it wins if present; otherwise whichever operational role comes first.
// Shared with App.jsx (default-route selection) so both agree on the same
// "primary" hat — see constants/roles.js.
const ACTS_AS_NAV_PRIORITY = ACTS_AS_PRIORITY;

/**
 * Builds the sidebar for a role="custom" staff member (e.g. a solo-clinic
 * role acting as doctor+nurse+front_desk) by unioning each acts_as role's
 * own nav — reusing every page already built for that role rather than
 * needing dedicated custom-role pages. De-dupes by route so a link/child
 * shared across roles (rare, but "My Profile" style routes can collide)
 * only appears once; only the first role keeps its own "Dashboard" link
 * and un-namespaced section headers, later roles get a labeled section so
 * it's clear which hat each group of links belongs to.
 */
function buildCustomNav(actsAs) {
  const roles = ACTS_AS_NAV_PRIORITY.filter(r => (actsAs || []).includes(r));
  if (roles.length === 0) return [];

  const seenRoutes = new Set();
  const items = [];

  roles.forEach((role, idx) => {
    const roleNav = NAV_BY_ROLE[role] || [];
    if (idx > 0) items.push({ type: "section", label: ROLE_LABELS[role] });

    roleNav.forEach(item => {
      if (item.type === "link") {
        if (idx > 0 && item.label === "Dashboard") return; // one Dashboard link total
        if (seenRoutes.has(item.to)) return;
        seenRoutes.add(item.to);
        items.push(item);
      } else if (item.type === "group") {
        const children = item.children.filter(c => {
          if (seenRoutes.has(c.to)) return false;
          seenRoutes.add(c.to);
          return true;
        });
        if (children.length) items.push({ ...item, children });
      } else if (item.type === "section" && idx === 0) {
        items.push(item); // only the lead role's own section headers
      }
    });
  });

  return items;
}

// ── Sub-components ───────────────────────────────────────────────────────────
// Dark-sidebar palette
const SB = {
  text:       "var(--color-hero-muted)",
  textActive: "var(--color-hero-text)",
  bgActive:   "color-mix(in srgb, var(--color-hero-text) 12%, transparent)",
  caption:    "color-mix(in srgb, var(--color-hero-muted) 75%, black 25%)",
  border:     "color-mix(in srgb, var(--color-hero-text) 10%, transparent)",
};

function SidebarLink({ label, iconKey, to, collapsed, indent = false }) {
  return (
    <NavLink to={to}
      className={({ isActive }) =>
        `sb-link${isActive ? " sb-link--active" : ""}${indent ? " sb-link--indent" : ""}`
      }
      title={collapsed ? label : undefined}>
      {iconKey && !indent && (
        <Icon d={ICONS[iconKey]} size={17} className="sb-icon" style={{ minWidth: 17, opacity: 0.75 }} />
      )}
      {indent && (
        <span style={{
          width: 5, height: 5, minWidth: 5, borderRadius: "50%",
          background: "currentColor", opacity: 0.5,
        }} />
      )}
      {!collapsed && <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{label}</span>}
    </NavLink>
  );
}

function SidebarGroup({ label, iconKey, children, collapsed, pathname }) {
  const active = isGroupActive(children, pathname);
  const [open, setOpen] = useState(active);

  // Keep open if a child becomes active
  useEffect(() => {
    if (active) setOpen(true);
  }, [active]);

  return (
    <div style={{ marginBottom: 2 }}>
      {/* Group header button */}
      <button
        onClick={() => !collapsed && setOpen(o => !o)}
        title={collapsed ? label : undefined}
        className={`sb-link${active ? " sb-link--active" : ""}`}
      >
        <Icon d={ICONS[iconKey]} size={17} className="sb-icon" style={{ minWidth: 17, opacity: 0.75 }} />
        {!collapsed && (
          <>
            <span style={{ flex: 1, whiteSpace: "nowrap" }}>{label}</span>
            <Icon
              d={open ? ICONS.chevronDown : ICONS.chevronRight}
              size={14}
              style={{ minWidth: 14, opacity: 0.5, transition: "transform 150ms ease" }}
            />
          </>
        )}
      </button>

      {/* Children — slide open/closed */}
      {!collapsed && open && (
        <div style={{ overflow: "hidden", marginTop: 1 }}>
          {children.map(child => (
            <SidebarLink key={child.to} label={child.label} iconKey={child.iconKey}
              to={child.to} collapsed={false} indent />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Family Members nav list (patient portal only) ───────────────────────────
// Renders each linked family member as a clickable nav item — selecting one
// sets the shared "which patient am I viewing" context and jumps to Records
// (no separate per-member routes needed). Falls back to nothing if this
// AppShell instance has no PatientProvider ancestor (i.e. any non-patient
// role), so it's safe to reference from the shared NAV_BY_ROLE renderer.
function FamilyNavList({ collapsed }) {
  const ctx = useContext(PatientContext);
  const navigate = useNavigate();

  if (!ctx) return null;
  const { familyMembers, isLoadingFamily, selectedPatient, selectPatient } = ctx;

  function viewMember(member) {
    selectPatient(member.awpid, member.full_name);
    navigate(ROUTES.PATIENT.RECORDS);
  }

  if (collapsed) return null;

  return (
    <div style={{ marginBottom: 2 }}>
      {isLoadingFamily ? (
        <div style={{ padding: "6px 12px", fontSize: 11, color: SB.caption }}>Loading…</div>
      ) : familyMembers.length === 0 ? (
        <div style={{ padding: "6px 12px", fontSize: 11, color: SB.caption }}>No family members added yet</div>
      ) : (
        familyMembers.map(m => {
          const active = !selectedPatient.isSelf && selectedPatient.awpid === m.awpid;
          return (
            <button
              key={m.awpid}
              onClick={() => viewMember(m)}
              className={`sb-link${active ? " sb-link--active" : ""}`}
              title={m.full_name}
              style={{ width: "100%" }}
            >
              <span style={{
                width: 5, height: 5, minWidth: 5, borderRadius: "50%",
                background: "currentColor", opacity: 0.5,
              }} />
              <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{m.full_name}</span>
            </button>
          );
        })
      )}
      <div style={{ borderTop: `1px solid ${SB.border}`, marginTop: 4, paddingTop: 4 }}>
        <SidebarLink label="Manage Family" iconKey="settings" to={ROUTES.PATIENT.MY_PROFILE} collapsed={collapsed} />
      </div>
    </div>
  );
}

// ── "Viewing: <name>" indicator (patient portal only) ───────────────────────
// Always-visible reminder of whose records are currently on screen — with a
// one-click way back to self when a dependent is selected.
function ViewingIndicator({ collapsed }) {
  const ctx = useContext(PatientContext);
  if (!ctx || collapsed) return null;
  const { selectedPatient, selectPatient } = ctx;

  return (
    <div style={{
      margin: "8px 8px 0", padding: "8px 10px", borderRadius: 8,
      background: selectedPatient.isSelf ? "color-mix(in srgb, var(--color-hero-text) 12%, transparent)" : "color-mix(in srgb, var(--color-accent) 28%, transparent)",
      border: `1px solid ${selectedPatient.isSelf ? SB.border : "color-mix(in srgb, var(--color-accent) 35%, transparent)"}`,
      display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8,
    }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: SB.caption }}>
          Viewing
        </div>
        <div style={{
          fontSize: 12, fontWeight: 600, color: SB.textActive,
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }}>
          {selectedPatient.isSelf ? "Myself" : selectedPatient.name}
        </div>
      </div>
      {!selectedPatient.isSelf && (
        <button
          onClick={() => selectPatient(null, null)}
          title="Switch back to my own records"
          style={{
            background: "none", border: `1px solid ${SB.border}`, color: SB.text,
            borderRadius: 6, fontSize: 10, fontWeight: 600, padding: "4px 8px",
            cursor: "pointer", whiteSpace: "nowrap", flexShrink: 0,
          }}
        >
          Switch to self
        </button>
      )}
    </div>
  );
}

// ── AppShell ──────────────────────────────────────────────────────────────────
export function AppShell({ children }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const { toastSuccess } = useToast();
  const [collapsed, setCollapsed] = useState(false);

  // role="custom" staff (a hospital-defined Role — see apps/org/rbac.py)
  // get the union of every role their acts_as claim includes, e.g. a
  // solo-clinic role acting as doctor+nurse+front_desk sees all three
  // roles' nav merged into one sidebar. See buildCustomNav() above.
  const navItems = user?.role === "custom"
    ? buildCustomNav(user?.acts_as)
    : (NAV_BY_ROLE[user?.role] || []);

  function handleLogout() {
    logout();
    toastSuccess("Logged out.");
    navigate("/login");
  }

  const sidebarW = collapsed ? 60 : 240;
  const initials = (user?.full_name || user?.email || "U")[0].toUpperCase();
  const displayName = user?.full_name || user?.email?.split("@")[0] || "User";
  // role="custom" has no fixed label of its own — the JWT carries the
  // actual Role name (custom_role_name) precisely so this doesn't have to
  // fall back to a generic placeholder. See StaffLoginView.
  const roleLabel = user?.role === "custom"
    ? (user?.custom_role_name || "Custom Role")
    : (ROLE_LABELS[user?.role] || "Staff");

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden", background: "var(--color-bg)" }}>

      {/* ── Sidebar ──────────────────────────────────────────────────────── */}
      <aside style={{
        width: sidebarW, minWidth: sidebarW,
        background: "linear-gradient(180deg, var(--color-hero) 0%, var(--color-hero-2) 100%)",
        display: "flex", flexDirection: "column",
        transition: "width 200ms ease, min-width 200ms ease",
        overflow: "hidden",
        zIndex: 10,
        position: "relative",
      }}>

        {/* Brand — plain, no tinted/bordered chip around it (that just
            boxed in and shrank the logo) — the white logo card is enough
            visual weight of its own sitting straight on the sidebar
            gradient. Taller row than before so the logo actually reads. */}
        <div style={{
          height: 76, display: "flex", alignItems: "center",
          padding: collapsed ? "0 11px" : "0 16px",
          margin: collapsed ? "8px 0 4px" : "10px 0 4px",
          gap: 10, flexShrink: 0,
          position: "relative", zIndex: 1,
        }}>
          <div style={{
            display: "flex", alignItems: "center", justifyContent: collapsed ? "center" : "flex-start",
            flex: collapsed ? undefined : 1, minWidth: collapsed ? 34 : undefined, overflow: "hidden",
          }}>
            <div style={{
              display: "inline-flex", alignItems: "center", background: "#fff",
              borderRadius: 9, padding: collapsed ? "6px 8px" : "9px 14px", maxWidth: "100%",
              boxShadow: "0 2px 8px rgba(0,0,0,0.15)",
            }}>
              <img src="/branding/atomwalk-full.png" alt="Atomwalk Technologies"
                style={{ height: collapsed ? 20 : 34, maxWidth: "100%", width: "auto", objectFit: "contain", display: "block" }} />
            </div>
          </div>
          {!collapsed && (
            <span style={{
              fontFamily: "var(--font-display)", fontWeight: 600, fontSize: 18,
              color: SB.textActive, letterSpacing: "0.08em", flexShrink: 0,
            }}>
              HMS
            </span>
          )}
        </div>

        {/* "Viewing: <name>" indicator — patient portal only (no-op elsewhere) */}
        <ViewingIndicator collapsed={collapsed} />

        {/* Nav */}
        <nav style={{ flex: 1, padding: "10px 8px", overflowY: "auto", overflowX: "hidden" }}>
          {navItems.map((item, i) => {
            if (item.type === "section") {
              if (collapsed) return null;
              return (
                <div key={i} className="sb-section">
                  {item.label}
                </div>
              );
            }
            if (item.type === "group") {
              return (
                <SidebarGroup key={i}
                  label={item.label} iconKey={item.iconKey}
                  children={item.children}
                  collapsed={collapsed} pathname={location.pathname}
                />
              );
            }
            if (item.type === "family-list") {
              return <FamilyNavList key={i} collapsed={collapsed} />;
            }
            return (
              <SidebarLink key={i}
                label={item.label} iconKey={item.iconKey}
                to={item.to} collapsed={collapsed}
              />
            );
          })}
        </nav>

        {/* Bottom: user info + logout + collapse toggle */}
        <div style={{
          flexShrink: 0,
          background: "rgba(0, 0, 0, 0.12)",
        }}>
          {/* User chip */}
          {!collapsed && (
            <div className="sb-user-chip">
              <div className="sb-avatar-ring">
                {user?.photo
                  ? <img src={user.photo} alt="" style={{ width: "100%", height: "100%", borderRadius: "50%", objectFit: "cover" }} />
                  : initials}
              </div>
              <div style={{ overflow: "hidden" }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: SB.textActive,
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {displayName}
                </div>
                <div style={{ fontSize: 10, color: "var(--color-accent)", fontWeight: 600, letterSpacing: "0.02em" }}>
                  {roleLabel}
                </div>
              </div>
            </div>
          )}

          <div style={{ padding: "4px 8px 10px" }}>
            <button onClick={handleLogout} className="sb-logout-btn">
              <Icon d={ICONS.logout} size={16} />
              {!collapsed && "Sign Out"}
            </button>

            <button onClick={() => setCollapsed(c => !c)} className="sb-collapse-btn">
              <Icon d={collapsed ? ICONS.expand : ICONS.collapse} size={16} />
              {!collapsed && "Collapse"}
            </button>
          </div>
        </div>
      </aside>

      {/* ── Main area ────────────────────────────────────────────────────── */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0 }}>

        {/* Topbar — same height as the sidebar's brand row above, so the
            two sit flush as one continuous band instead of a jagged
            skyline where the sidebar logo block used to be taller. */}
        <header style={{
          height: 76, flexShrink: 0,
          background: "linear-gradient(90deg, var(--color-hero) 0%, var(--color-hero-2) 100%)",
          display: "flex", alignItems: "center",
          justifyContent: "space-between",
          padding: "0 24px",
          position: "relative", zIndex: 2,
        }}>
          {/* Left: tenant logo + clinic name — driven by the logged-in staff
              member's own hospital (from user.hospital_name/.logo, fetched
              via /me/), not a fixed hospital. Falls back to a monogram
              derived from the hospital's own name/id until it uploads a
              real logo via Settings (see HospitalLogoUpload.jsx), rather
              than all hospitals sharing one hardcoded icon. */}
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {user?.db_name ? (
              <>
                <div style={{ boxShadow: "0 0 0 2px color-mix(in srgb, var(--color-accent) 30%, transparent)", borderRadius: "50%" }}>
                  <HospitalBadge logo={user.logo} name={user.hospital_name} tenantId={user.tenant_id} />
                </div>
                <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.25 }}>
                  <span style={{
                    fontFamily: "var(--font-display)", fontWeight: 600, fontSize: 17,
                    color: "var(--color-hero-text)", letterSpacing: "0.01em",
                  }}>
                    {user.hospital_name || "Hospital"}
                  </span>
                  <span style={{
                    fontSize: 10, fontWeight: 600, color: "var(--color-accent)",
                    letterSpacing: "0.08em", textTransform: "uppercase",
                  }}>
                    {roleLabel}
                  </span>
                </div>
              </>
            ) : (
              <span style={{
                fontSize: 11, fontWeight: 700,
                background: "color-mix(in srgb, var(--color-hero-text) 12%, transparent)",
                color: "var(--color-hero-text)",
                padding: "3px 12px", borderRadius: 20,
                letterSpacing: "0.06em", textTransform: "uppercase",
              }}>
                {ROLE_LABELS[user?.role] || "Portal"}
              </span>
            )}
          </div>

          {/* Right: email + theme switcher — the user's own avatar/name/role
              already lives in one place, the sidebar's bottom chip (which
              also carries Sign Out/Collapse right next to it), so it isn't
              repeated here too. */}
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{
              fontSize: 12, color: "var(--color-hero-muted)",
              maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}>
              {user?.email}
            </div>
            <ThemeSwitcher />
          </div>
        </header>

        {/* Page content */}
        <main style={{ flex: 1, overflowY: "auto", background: "var(--color-bg)" }}>
          {children}
        </main>
      </div>
    </div>
  );
}

export default AppShell;
