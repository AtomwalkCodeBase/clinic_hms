/**
 * pages/hospital-admin/RoomsPage.jsx
 * ------------------------------------
 * Hospital admin: Floors, Rooms & Beds setup for a branch.
 *
 * Which doctor sits in which room and when is tagged from the doctor's own
 * profile (Staff → Profile → Working Hours & Rooms), not here — this page
 * is purely location setup (floors/rooms/beds), so it deliberately shows
 * no doctor-assignment column or control anywhere below.
 *
 * v8 unification: what used to be two separate concepts — Room (OPD
 * consultation/procedure space) and Ward (IPD bed space, with its own
 * Ward Type catalog and Bed) — are now one: Room, with a single
 * hospital-configurable Room Type catalog (billing.OptionList,
 * list_type="room_type") that spans both OPD types (Consultation,
 * Procedure, …) and bed-based IPD types (General Ward, Private, ICU, HDU,
 * Isolation, …). A room's type carries whether it's bed-based
 * (is_bed_based) and a category (OPD/IPD/Procedure/Other) — see
 * billing.OptionList's own docstring. "Add Room" asks for Bed Capacity
 * only when the picked Room Type is bed-based, and Department is always
 * optional. Floors organize every Room (OPD and bed-based alike) the same
 * way; Rooms created before a floor was ever picked for them (floor_obj is
 * nullable) surface in an always-visible "Unassigned Rooms" bucket rather
 * than silently vanishing from every floor's list.
 *
 * Bed *status* (available/occupied/…) is never edited here —
 * org.BedDetailView deliberately refuses it — that only ever changes
 * through IPD's assign-bed/release-bed flow, so a bed here always reflects
 * whether a patient is actually in it.
 *
 * Every bed-based room has a required Bed Capacity, set at Add Room time —
 * the backend (org.views.BedListCreateView.post / BedDetailView.patch)
 * refuses to add or move a bed into a room once its active bed count
 * reaches that number, so "+ Add Bed" is disabled here the moment a room
 * hits capacity rather than letting the request round-trip and fail.
 */

import { useState, useEffect, useCallback, useMemo } from "react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import apiClient     from "../../services/api.client";
import { useToast }  from "../../hooks/useToast";
import { useApi }    from "../../hooks/useApi";
import API_ENDPOINTS from "../../config/api.config";
import { DropdownListEditor } from "../../components/hospital-admin/DropdownListEditor";
import { KebabMenu } from "../../components/hospital-admin/KebabMenu";
import {
  Building2, DoorOpen, BedDouble, Bed as BedIcon, Tag, HelpCircle,
  ChevronRight, ChevronDown, ChevronLeft, Search, Pencil, Download, ListChecks,
  Check, X,
} from "lucide-react";

const EMPTY_ROOM = { branch: "", floor_obj: "", name: "", room_type: "consultation", capacity: "", department: "" };
const EMPTY_FLOOR = { branch: "", name: "", level: "0" };
const EMPTY_BED   = { room: "", bed_number: "" };

const ROOM_TYPE_CATEGORY_OPTIONS = [
  { value: "opd", label: "OPD" },
  { value: "ipd", label: "IPD" },
  { value: "procedure", label: "Procedure" },
  { value: "other", label: "Other" },
];

// Room Type is a single hospital-configurable catalog (billing.OptionList,
// list_type="room_type") spanning both OPD and bed-based IPD types —
// neither stores a color, so colors are assigned by position, stable as
// long as sort_order doesn't change, which matches how the compact catalog
// editor and the tables below read the same fetched array.
const TYPE_COLOR_PALETTE = [
  { bg: "#e8f0fe", text: "#3b6fd4" },
  { bg: "#f3e8fd", text: "#8b5cf6" },
  { bg: "#e3f7ec", text: "#16a34a" },
  { bg: "#fdf1e3", text: "#c2760c" },
  { bg: "#fde8ef", text: "#e11d48" },
  { bg: "#e3f7f7", text: "#0d9488" },
];
function roomTypeMeta(value, options) {
  const idx = options.findIndex(t => t.value === value);
  const opt = idx >= 0 ? options[idx] : null;
  const label = opt ? opt.label : (value || "—");
  const color = TYPE_COLOR_PALETTE[(idx >= 0 ? idx : 0) % TYPE_COLOR_PALETTE.length];
  return { label, ...color, isBedBased: !!opt?.is_bed_based, category: opt?.category || "" };
}

const BED_STATUSES = [
  { value: "available",      label: "Available",      color: "#1a7f37" },
  { value: "occupied",       label: "Occupied",        color: "#c0362c" },
  { value: "cleaning",       label: "Cleaning",        color: "#b8860b" },
  { value: "blocked",        label: "Blocked",         color: "#6b7280" },
  { value: "out_of_service", label: "Out of Service",  color: "#374151" },
];
const bedStatusMeta = (status) => BED_STATUSES.find(s => s.value === status) || BED_STATUSES[0];

// "12 Sep 2026" / "12 Sep 2026, 14:05" — used for a bed's current occupant
// (admitted date/time, expected discharge date), not on this page anywhere
// else, so this stays local rather than a shared date util.
function formatDate(value) {
  if (!value) return "";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });
}
function formatDateTime(value) {
  if (!value) return "";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString(undefined, { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

// 1 -> "1st", 2 -> "2nd", 3 -> "3rd", 4 -> "4th", 11 -> "11th", 21 -> "21st"...
function ordinal(n) {
  const j = n % 10, k = n % 100;
  if (j === 1 && k !== 11) return `${n}st`;
  if (j === 2 && k !== 12) return `${n}nd`;
  if (j === 3 && k !== 13) return `${n}rd`;
  return `${n}th`;
}

// ── Small shared bits ───────────────────────────────────────────────────

function Modal({ title, children, onClose, width = 480 }) {
  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 1000,
      background: "rgba(0,0,0,0.45)",
      display: "flex", alignItems: "center", justifyContent: "center", padding: 24,
    }}>
      <div style={{
        background: "var(--color-surface)", borderRadius: 16,
        width: "100%", maxWidth: width, padding: 32,
        boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
        maxHeight: "90vh", overflowY: "auto",
      }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
          <h2 style={{ margin: 0, fontSize: 18 }}>{title}</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer", color: "var(--color-text-muted)" }}>✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

function Field({ label, value, onChange, placeholder, required, type = "text", children, ...inputProps }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <label style={{ display: "block", fontSize: 13, fontWeight: 600, marginBottom: 5 }}>{label}</label>
      {children || (
        <input
          type={type} value={value} onChange={e => onChange(e.target.value)}
          placeholder={placeholder} required={required}
          style={{
            width: "100%", boxSizing: "border-box",
            border: "1.5px solid var(--color-border)", borderRadius: 8,
            padding: "9px 12px", fontSize: 14,
            background: "var(--color-surface)", color: "var(--color-text)", outline: "none",
          }}
          {...inputProps}
        />
      )}
    </div>
  );
}

function Select({ label, value, onChange, options, required, hint }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <label style={{ display: "block", fontSize: 13, fontWeight: 600, marginBottom: 5 }}>{label}</label>
      <select value={value} onChange={e => onChange(e.target.value)} required={required}
        style={{
          width: "100%", boxSizing: "border-box",
          border: "1.5px solid var(--color-border)", borderRadius: 8,
          padding: "9px 12px", fontSize: 14,
          background: "var(--color-surface)", color: "var(--color-text)", outline: "none",
        }}>
        <option value="">Select…</option>
        {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      {hint && <div style={{ fontSize: 11.5, color: "var(--color-text-muted)", marginTop: 4 }}>{hint}</div>}
    </div>
  );
}

function ModalActions({ onCancel, saving, disabled, submitLabel }) {
  return (
    <div style={{ display: "flex", gap: 10, marginTop: 8 }}>
      <button type="button" onClick={onCancel}
        style={{ flex: 1, padding: "9px 0", borderRadius: 8, border: "1.5px solid var(--color-border)", background: "none", cursor: "pointer", fontSize: 14, fontWeight: 600 }}>
        Cancel
      </button>
      <button type="submit" disabled={saving || disabled} className="btn-primary" style={{ flex: 2 }}>
        {saving ? "Saving…" : submitLabel}
      </button>
    </div>
  );
}

// Small filter <select> used throughout (search bars' companion dropdowns).
function FilterSelect({ value, onChange, options, width }) {
  return (
    <select value={value} onChange={e => onChange(e.target.value)}
      style={{
        padding: "9px 12px", borderRadius: 9, border: "1.5px solid var(--color-border)",
        fontSize: 12.5, fontWeight: 600, background: "var(--color-surface)", color: "var(--color-text)",
        cursor: "pointer", width, flexShrink: 0,
      }}>
      {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}

function SearchInput({ value, onChange, placeholder }) {
  return (
    <div style={{ position: "relative", flex: 1, minWidth: 160 }}>
      <Search size={14} style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "var(--color-text-muted)" }} />
      <input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
        style={{
          width: "100%", boxSizing: "border-box", padding: "9px 12px 9px 34px", borderRadius: 9,
          border: "1.5px solid var(--color-border)", fontSize: 13, background: "var(--color-surface)", color: "var(--color-text)", outline: "none",
        }} />
    </div>
  );
}

function StatusDot({ active, activeLabel = "Active", inactiveLabel = "Inactive" }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12.5, fontWeight: 600, color: active ? "#1a7f37" : "var(--color-text-muted)" }}>
      <span style={{ width: 7, height: 7, borderRadius: "50%", background: active ? "#1a7f37" : "#9ca3af", flexShrink: 0 }} />
      {active ? activeLabel : inactiveLabel}
    </span>
  );
}

function Pill({ label, bg, text }) {
  return (
    <span style={{
      display: "inline-block", padding: "3px 10px", borderRadius: 999,
      fontSize: 11.5, fontWeight: 700, background: bg, color: text, whiteSpace: "nowrap",
    }}>
      {label}
    </span>
  );
}

function Pagination({ page, pageCount, onChange }) {
  if (pageCount <= 1) return null;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <button type="button" onClick={() => onChange(Math.max(1, page - 1))} disabled={page <= 1}
        style={{ width: 28, height: 28, borderRadius: 7, border: "1.5px solid var(--color-border)", background: "none", cursor: page <= 1 ? "default" : "pointer", opacity: page <= 1 ? 0.4 : 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <ChevronLeft size={14} />
      </button>
      <span style={{
        width: 28, height: 28, borderRadius: 7, background: "var(--color-primary)", color: "#fff",
        fontSize: 12.5, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center",
      }}>
        {page}
      </span>
      <button type="button" onClick={() => onChange(Math.min(pageCount, page + 1))} disabled={page >= pageCount}
        style={{ width: 28, height: 28, borderRadius: 7, border: "1.5px solid var(--color-border)", background: "none", cursor: page >= pageCount ? "default" : "pointer", opacity: page >= pageCount ? 0.4 : 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <ChevronRight size={14} />
      </button>
    </div>
  );
}

function StatCard({ icon: Icon, value, label, iconBg, iconColor }) {
  return (
    <div className="card" style={{ padding: "14px 18px", display: "flex", alignItems: "center", gap: 12, flex: 1, minWidth: 0 }}>
      <div style={{
        width: 40, height: 40, borderRadius: 10, background: iconBg || "var(--color-primary-light)",
        display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
      }}>
        <Icon size={19} style={{ color: iconColor || "var(--color-primary)" }} />
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 22, fontWeight: 800, lineHeight: 1.1 }}>{value}</div>
        <div style={{ fontSize: 11.5, color: "var(--color-text-muted)", marginTop: 2, whiteSpace: "nowrap" }}>{label}</div>
      </div>
    </div>
  );
}

// Bordered box wrapping a real (invisible, overlaid) <select> so the
// branch switcher reads as a two-line "BRANCH / Sparsh Hospital — Yelahanka"
// control while staying a normal, accessible <select> underneath.
function BranchSelector({ branches, value, onChange }) {
  const selected = branches.find(b => String(b.id) === String(value));
  return (
    <div style={{
      position: "relative", display: "flex", alignItems: "center", gap: 10,
      padding: "8px 14px", borderRadius: 10, border: "1.5px solid var(--color-border)",
      background: "var(--color-surface)", minWidth: 240,
    }}>
      <div style={{ width: 34, height: 34, borderRadius: 8, background: "var(--color-primary-light)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
        <Building2 size={17} style={{ color: "var(--color-primary)" }} />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Branch</div>
        <div style={{ fontSize: 13.5, fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{selected?.name || "Select branch"}</div>
      </div>
      <ChevronDown size={16} style={{ color: "var(--color-text-muted)", flexShrink: 0 }} />
      <select value={value} onChange={e => onChange(e.target.value)}
        style={{ position: "absolute", inset: 0, opacity: 0, cursor: "pointer", width: "100%", height: "100%" }}>
        {branches.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
      </select>
    </div>
  );
}

// ── Floors ──────────────────────────────────────────────────────────────

function FloorForm({ initial, onSave, onGenerate, onCancel, saving }) {
  const [mode, setMode] = useState("single"); // "single" | "quick" — quick only offered when creating fresh
  const [form, setForm] = useState(initial || EMPTY_FLOOR);
  const [floorCount, setFloorCount] = useState("4");
  const set = (k) => (v) => setForm(f => ({ ...f, [k]: v }));

  function submit(e) {
    e.preventDefault();
    if (mode === "quick") onGenerate(Number(floorCount) || 0);
    else onSave(form);
  }

  const preview = mode === "quick"
    ? ["Ground", ...Array.from({ length: Math.max(0, Number(floorCount) || 0) }, (_, i) => `${ordinal(i + 1)} Floor`)]
    : [];

  return (
    <form onSubmit={submit}>
      {!initial && (
        <div style={{ display: "flex", gap: 8, marginBottom: 18 }}>
          <button type="button" onClick={() => setMode("single")}
            style={{
              flex: 1, padding: "8px 0", borderRadius: 8, cursor: "pointer", fontSize: 12.5, fontWeight: 700,
              border: mode === "single" ? "1.5px solid var(--color-primary)" : "1.5px solid var(--color-border)",
              background: mode === "single" ? "var(--color-primary-light)" : "none",
              color: mode === "single" ? "var(--color-primary)" : "var(--color-text)",
            }}>
            Add One Floor
          </button>
          <button type="button" onClick={() => setMode("quick")}
            style={{
              flex: 1, padding: "8px 0", borderRadius: 8, cursor: "pointer", fontSize: 12.5, fontWeight: 700,
              border: mode === "quick" ? "1.5px solid var(--color-primary)" : "1.5px solid var(--color-border)",
              background: mode === "quick" ? "var(--color-primary-light)" : "none",
              color: mode === "quick" ? "var(--color-primary)" : "var(--color-text)",
            }}>
            Quick Setup
          </button>
        </div>
      )}

      {mode === "single" ? (
        <>
          <Field label="Floor Name *" value={form.name} onChange={set("name")} placeholder="e.g. Ground, 1st Floor, Basement" required />
          <Field label="Sort Order" type="number" value={form.level} onChange={set("level")} placeholder="0"
            hint="Lower numbers list first — e.g. Basement -1, Ground 0, 1st Floor 1, 2nd Floor 2." />
        </>
      ) : (
        <>
          <Field label="How many floors above Ground? *" type="number" min="0" max="50"
            value={floorCount} onChange={setFloorCount} placeholder="e.g. 4"
            hint="Ground is always created first (Sort Order 0) — this adds that many numbered floors above it." />
          {preview.length > 0 && (
            <div style={{ marginBottom: 6 }}>
              <div style={{ fontSize: 11.5, color: "var(--color-text-muted)", marginBottom: 6 }}>Will create:</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {preview.map(p => (
                  <span key={p} style={{ fontSize: 11.5, fontWeight: 600, padding: "3px 9px", borderRadius: 999, background: "var(--color-bg)", border: "1px solid var(--color-border)" }}>{p}</span>
                ))}
              </div>
            </div>
          )}
          <div style={{ fontSize: 11.5, color: "var(--color-text-muted)", margin: "10px 0 14px" }}>
            Safe to run again later — floors that already exist are skipped, not duplicated.
          </div>
        </>
      )}
      <ModalActions onCancel={onCancel} saving={saving}
        disabled={mode === "single" ? !form.name : floorCount === "" || Number(floorCount) < 0}
        submitLabel={initial ? "Update Floor" : mode === "quick" ? "Create Floors" : "Create Floor"} />
    </form>
  );
}

function FloorListItem({ floor, roomCount, selected, onSelect, icon: Icon = Building2 }) {
  const hasLevel = floor.level !== null && floor.level !== undefined;
  return (
    <button type="button" onClick={onSelect} style={{
      display: "flex", alignItems: "center", gap: 10, width: "100%", textAlign: "left",
      padding: "12px 14px", borderRadius: 10, cursor: "pointer", marginBottom: 8,
      border: selected ? "1.5px solid var(--color-primary)" : "1.5px solid var(--color-border)",
      background: selected ? "var(--color-primary-light)" : "var(--color-surface)",
    }}>
      <div style={{
        width: 32, height: 32, borderRadius: 8, background: selected ? "#fff" : "var(--color-bg)",
        display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, border: "1px solid var(--color-border)",
      }}>
        <Icon size={15} style={{ color: selected ? "var(--color-primary)" : "var(--color-text-muted)" }} />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontWeight: 700, fontSize: 13.5 }}>{floor.name}</span>
          {hasLevel && (
            <span style={{ fontSize: 10.5, fontWeight: 700, padding: "2px 8px", borderRadius: 999, background: "var(--color-surface)", border: "1px solid var(--color-border)", color: "var(--color-text-muted)" }}>
              Level {floor.level}
            </span>
          )}
        </div>
        <div style={{ fontSize: 11.5, color: "var(--color-text-muted)", marginTop: 2 }}>{roomCount} room{roomCount === 1 ? "" : "s"}</div>
      </div>
      <ChevronRight size={15} style={{ color: "var(--color-text-muted)", flexShrink: 0 }} />
    </button>
  );
}

// Per-night price for each bed-based Room Type — billing.OptionList.daily_rate,
// added specifically so IPD's Generate Invoice action (front-desk/
// AdmissionDetailPage.jsx) has a real rate to price room charges from; that
// action hard-errors on any bed-based type left at "—" here. Deliberately a
// small bespoke list rather than another DropdownListEditor extraFields
// entry — that widget's extra fields are create-time-only (see its own
// docstring), but a rate has to stay editable long after the type exists.
function RoomTypeRatesEditor({ roomTypes, onSaved }) {
  const { toastSuccess, toastApiError } = useToast();
  const [editingId, setEditingId] = useState(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  const bedBased = (roomTypes || []).filter(t => t.is_bed_based);
  if (bedBased.length === 0) return null;

  function startEdit(t) {
    setEditingId(t.id);
    setDraft(t.daily_rate ?? "");
  }
  function cancelEdit() {
    setEditingId(null);
    setDraft("");
  }
  async function save(t) {
    const value = draft === "" ? null : Number(draft);
    if (value !== null && (Number.isNaN(value) || value < 0)) {
      toastApiError({ message: "Enter a valid rate." });
      return;
    }
    setSaving(true);
    try {
      await apiClient.patch(API_ENDPOINTS.BILLING.ROOM_TYPE(t.id), { daily_rate: value });
      toastSuccess(`Daily rate updated for ${t.label}.`);
      cancelEdit();
      onSaved();
    } catch (err) {
      toastApiError(err, "Could not update daily rate.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--color-border)" }}>
      <div style={{ fontSize: 11.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.03em", color: "var(--color-text-muted)", marginBottom: 8 }}>
        Daily rates (bed-based types)
      </div>
      <div style={{ display: "grid", gap: 6 }}>
        {bedBased.map(t => (
          <div key={t.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, fontSize: 12.5 }}>
            <span>{t.label}</span>
            {editingId === t.id ? (
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <input
                  autoFocus type="number" min="0" step="0.01" value={draft} disabled={saving}
                  onChange={e => setDraft(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === "Enter") { e.preventDefault(); save(t); }
                    if (e.key === "Escape") { e.preventDefault(); cancelEdit(); }
                  }}
                  style={{
                    width: 90, border: "1.5px solid var(--color-border)", borderRadius: 6, padding: "3px 8px",
                    fontSize: 12.5, background: "var(--color-surface)", color: "var(--color-text)", outline: "none",
                  }}
                />
                <button type="button" onClick={() => save(t)} disabled={saving}
                  style={{ background: "none", border: "none", cursor: "pointer", padding: 0, lineHeight: 1, color: "var(--color-primary)" }}>
                  <Check size={13} />
                </button>
                <button type="button" onClick={cancelEdit} disabled={saving}
                  style={{ background: "none", border: "none", cursor: "pointer", padding: 0, lineHeight: 1, color: "var(--color-text-muted)" }}>
                  <X size={13} />
                </button>
              </span>
            ) : (
              <button type="button" onClick={() => startEdit(t)}
                style={{
                  background: "none", border: "none", cursor: "pointer", padding: 0,
                  fontSize: 12.5, fontWeight: 700,
                  color: t.daily_rate ? "var(--color-text)" : "var(--color-error)",
                }}>
                {t.daily_rate ? `₹${Number(t.daily_rate).toLocaleString("en-IN")}/night` : "Set rate →"}
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Rooms ───────────────────────────────────────────────────────────────

// "3 of 5 beds" for a bed-based room with capacity set, "3 beds" (uncapped)
// for one created before capacity was required, "—" for a non-bed-based
// (OPD) room. This is a *setup* fact (how many bed records exist against
// the room's configured capacity) — it says nothing about whether a
// patient is in any of those beds. See roomOccupancy() for that.
function bedsLabel(room, isBedBased) {
  if (!isBedBased) return "—";
  if (room.capacity == null) return `${room.bed_count} bed${room.bed_count === 1 ? "" : "s"}`;
  return `${room.bed_count} of ${room.capacity} bed${room.capacity === 1 ? "" : "s"}`;
}
// Whether every bed slot the room's capacity allows has already been
// created — used only to gate the "+ Add Bed" action (you can't create
// more bed records than the configured capacity). Deliberately NOT used
// to mean "no vacancy" — a room can have all its bed *records* created
// and still have every one of them empty and available for a patient.
function bedCapacityReached(room, isBedBased) {
  return isBedBased && room.capacity != null && room.bed_count >= room.capacity;
}
// Real, patient-facing occupancy for a room, computed from its actual
// beds' statuses (not from bed_count/capacity — see bedCapacityReached
// for why those are a different question). available/occupied here match
// the same "available"/"occupied" bed statuses the top stat row and the
// Beds table use, so a room only ever shows "Full" when none of its beds
// can actually take a new patient right now.
function roomOccupancy(roomBeds) {
  const total = roomBeds.length;
  const available = roomBeds.filter((b) => b.status === "available").length;
  const occupied = roomBeds.filter((b) => b.status === "occupied").length;
  return { total, available, occupied };
}

function RoomForm({ branches, floors, roomTypes, departments, initial, onSave, onCancel, saving }) {
  const [form, setForm] = useState(initial || EMPTY_ROOM);
  const set = (k) => (v) => setForm(f => ({ ...f, [k]: v }));
  const typeMeta = roomTypeMeta(form.room_type, roomTypes);
  const isBedBased = typeMeta.isBedBased;
  const currentBeds = initial?.bed_count ?? 0;
  const capacityTooLow = isBedBased && form.capacity !== "" && Number(form.capacity) < currentBeds;

  function submit(e) {
    e.preventDefault();
    onSave(form, isBedBased);
  }

  return (
    <form onSubmit={submit}>
      <Select label="Branch *" value={form.branch} onChange={set("branch")}
        options={branches.map(b => ({ value: String(b.id), label: b.name }))} required />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <Select label="Floor" value={form.floor_obj} onChange={set("floor_obj")}
          options={floors.map(f => ({ value: String(f.id), label: f.name }))}
          hint={floors.length === 0 ? "No floors set up yet — add one first." : undefined} />
        <Field label="Room Number / Name *" value={form.name} onChange={set("name")} placeholder="e.g. OPD-01, Ward 1, ICU-A" required />
      </div>
      <Select label="Room Type *" value={form.room_type} onChange={set("room_type")}
        options={roomTypes.map(t => ({ value: t.value, label: t.label }))}
        hint={roomTypes.length === 0 ? "No room types configured yet." : undefined} required />
      {isBedBased && (
        <Field label="Bed Capacity *" type="number" min="1" value={form.capacity} onChange={set("capacity")}
          placeholder="e.g. 5"
          hint={capacityTooLow
            ? `This room already has ${currentBeds} bed${currentBeds === 1 ? "" : "s"} — capacity can't be set lower. Remove a bed first if you need to shrink it.`
            : "Maximum number of beds this room can hold — beds can't be added past this."} required />
      )}
      <Select label="Department (optional)" value={form.department} onChange={set("department")}
        options={departments.map(d => ({ value: String(d.id), label: d.name }))}
        hint="Only needed if this room belongs to a specific clinical department." />
      <ModalActions onCancel={onCancel} saving={saving}
        disabled={!form.branch || !form.name || !form.room_type || (isBedBased && (!form.capacity || Number(form.capacity) < 1 || capacityTooLow))}
        submitLabel={initial ? "Update Room" : "Create Room"} />
    </form>
  );
}

function BedForm({ initial, onSave, onCancel, saving }) {
  const [form, setForm] = useState(initial || EMPTY_BED);
  const set = (k) => (v) => setForm(f => ({ ...f, [k]: v }));
  const isEdit = !!initial;

  function submit(e) {
    e.preventDefault();
    onSave(form);
  }

  return (
    <form onSubmit={submit}>
      <Field label="Bed Number / Label *" value={form.bed_number} onChange={set("bed_number")} placeholder="e.g. A-01, 12" required />
      {isEdit && (
        <div style={{ fontSize: 11.5, color: "var(--color-text-muted)", marginBottom: 14 }}>
          Status ({bedStatusMeta(initial.status).label}) isn't editable here — it only changes when front desk
          assigns or releases this bed for an admission.
        </div>
      )}
      <ModalActions onCancel={onCancel} saving={saving} disabled={!form.bed_number} submitLabel={isEdit ? "Update Bed" : "Add Bed"} />
    </form>
  );
}

function RoomsTable({ rooms, roomTypes, bedsByRoom, onEdit, onDeactivate, onManageBeds }) {
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [activeFilter, setActiveFilter] = useState("active");
  const [page, setPage] = useState(1);
  const pageSize = 10;

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rooms.filter(r => {
      if (q) {
        const typeLabel = roomTypeMeta(r.room_type, roomTypes).label.toLowerCase();
        if (!r.name.toLowerCase().includes(q) && !typeLabel.includes(q)) return false;
      }
      if (typeFilter && r.room_type !== typeFilter) return false;
      if (activeFilter === "active" && !r.is_active) return false;
      if (activeFilter === "inactive" && r.is_active) return false;
      return true;
    });
  }, [rooms, roomTypes, search, typeFilter, activeFilter]);

  useEffect(() => { setPage(1); }, [search, typeFilter, activeFilter, rooms.length]);
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const pageRows = filtered.slice((page - 1) * pageSize, page * pageSize);

  return (
    <div>
      <div style={{ display: "flex", gap: 10, marginBottom: 16, flexWrap: "wrap" }}>
        <SearchInput value={search} onChange={setSearch} placeholder="Search rooms by name or type…" />
        <FilterSelect value={typeFilter} onChange={setTypeFilter} width={160}
          options={[{ value: "", label: "All Room Types" }, ...roomTypes.map(t => ({ value: t.value, label: t.label }))]} />
        <FilterSelect value={activeFilter} onChange={setActiveFilter} width={130}
          options={[{ value: "active", label: "Active Only" }, { value: "all", label: "All Rooms" }, { value: "inactive", label: "Inactive Only" }]} />
      </div>

      {rooms.length === 0 ? (
        <div style={{ textAlign: "center", padding: "40px 0", color: "var(--color-text-muted)" }}>
          <DoorOpen size={32} style={{ marginBottom: 10 }} />
          <div style={{ fontWeight: 600, marginBottom: 4 }}>No rooms on this floor yet</div>
          <div style={{ fontSize: 12.5 }}>Add the first room using the button above.</div>
        </div>
      ) : (
        <>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "1.5px solid var(--color-border)" }}>
                  {["Room", "Room Type", "Beds", "Actions"].map((h, i) => (
                    <th key={h} style={{
                      textAlign: i === 3 ? "right" : "left", padding: "0 8px 10px", fontSize: 11, fontWeight: 700,
                      color: "var(--color-text-muted)", letterSpacing: "0.04em", textTransform: "uppercase",
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pageRows.map(room => {
                  const meta = roomTypeMeta(room.room_type, roomTypes);
                  const roomBeds = (bedsByRoom && bedsByRoom[room.id]) || [];
                  const occ = roomOccupancy(roomBeds);
                  // "Full" here means real, patient-facing occupancy — every
                  // bed this room actually has is currently occupied — not
                  // that all of the room's capacity has been provisioned
                  // with bed records (that's a setup fact, shown below).
                  const noVacancy = meta.isBedBased && occ.total > 0 && occ.available === 0;
                  return (
                    <tr key={room.id} style={{ borderBottom: "1px solid var(--color-border)" }}>
                      <td style={{ padding: "12px 8px" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                          <div style={{ width: 30, height: 30, borderRadius: 8, background: "var(--color-bg)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                            {meta.isBedBased ? <BedDouble size={14} style={{ color: "var(--color-text-muted)" }} /> : <DoorOpen size={14} style={{ color: "var(--color-text-muted)" }} />}
                          </div>
                          <div>
                            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                              <span style={{ fontWeight: 700, fontSize: 13.5 }}>{room.name}</span>
                              {noVacancy && <Pill label="Full" bg="#fde8ef" text="#e11d48" />}
                            </div>
                            {room.department_name && <div style={{ fontSize: 11.5, color: "var(--color-text-muted)" }}>{room.department_name}</div>}
                          </div>
                        </div>
                      </td>
                      <td style={{ padding: "12px 8px" }}><Pill label={meta.label} bg={meta.bg} text={meta.text} /></td>
                      <td style={{ padding: "12px 8px", fontSize: 12.5, fontWeight: 700 }}>
                        {!meta.isBedBased ? (
                          <span style={{ color: "var(--color-text-muted)", fontWeight: 600 }}>—</span>
                        ) : occ.total === 0 ? (
                          <span style={{ color: "var(--color-text-muted)", fontWeight: 600 }}>No beds set up</span>
                        ) : (
                          <span style={{ color: occ.available > 0 ? "#1a7f37" : "#e11d48" }}>
                            {occ.available} of {occ.total} available
                          </span>
                        )}
                      </td>
                      <td style={{ padding: "12px 8px" }}>
                        <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 4 }}>
                          {meta.isBedBased && (
                            <button type="button" onClick={() => onManageBeds(room)} title="Manage Beds"
                              style={{ background: "none", border: "none", cursor: "pointer", padding: 6, color: "var(--color-text-muted)" }}>
                              <BedIcon size={14} />
                            </button>
                          )}
                          <button type="button" onClick={() => onEdit(room)} title="Edit"
                            style={{ background: "none", border: "none", cursor: "pointer", padding: 6, color: "var(--color-text-muted)" }}>
                            <Pencil size={14} />
                          </button>
                          <KebabMenu items={[{ label: "Remove Room", danger: true, onClick: () => onDeactivate(room) }]} />
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 14 }}>
            <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
              Showing {pageRows.length} of {filtered.length} room{filtered.length === 1 ? "" : "s"}
            </span>
            <Pagination page={page} pageCount={pageCount} onChange={setPage} />
          </div>
        </>
      )}
    </div>
  );
}

function BedsTable({ beds, onEdit, onRemove }) {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [sort, setSort] = useState("number_asc");
  const [page, setPage] = useState(1);
  const pageSize = 8;

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    let list = beds.filter(b => {
      if (q && !b.bed_number.toLowerCase().includes(q)) return false;
      if (statusFilter && b.status !== statusFilter) return false;
      return true;
    });
    list = [...list].sort((a, b) => {
      if (sort === "number_desc") return b.bed_number.localeCompare(a.bed_number, undefined, { numeric: true });
      if (sort === "status") return a.status.localeCompare(b.status);
      return a.bed_number.localeCompare(b.bed_number, undefined, { numeric: true });
    });
    return list;
  }, [beds, search, statusFilter, sort]);

  useEffect(() => { setPage(1); }, [search, statusFilter, sort, beds.length]);
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const pageRows = filtered.slice((page - 1) * pageSize, page * pageSize);

  return (
    <div>
      <div style={{ display: "flex", gap: 10, marginBottom: 16, flexWrap: "wrap" }}>
        <SearchInput value={search} onChange={setSearch} placeholder="Search beds by number…" />
        <FilterSelect value={statusFilter} onChange={setStatusFilter} width={140}
          options={[{ value: "", label: "All Statuses" }, ...BED_STATUSES.map(s => ({ value: s.value, label: s.label }))]} />
        <FilterSelect value={sort} onChange={setSort} width={170}
          options={[
            { value: "number_asc", label: "Bed Number (A – Z)" },
            { value: "number_desc", label: "Bed Number (Z – A)" },
            { value: "status", label: "Status" },
          ]} />
      </div>

      {beds.length === 0 ? (
        <div style={{ textAlign: "center", padding: "40px 0", color: "var(--color-text-muted)" }}>
          <BedIcon size={32} style={{ marginBottom: 10 }} />
          <div style={{ fontWeight: 600, marginBottom: 4 }}>No beds in this room yet</div>
          <div style={{ fontSize: 12.5 }}>Add the first bed using the button above.</div>
        </div>
      ) : (
        <>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "1.5px solid var(--color-border)" }}>
                  {["Bed Number", "Status", "Occupied By", "Is Active", "Actions"].map((h, i) => (
                    <th key={h} style={{
                      textAlign: i === 4 ? "right" : "left", padding: "0 8px 10px", fontSize: 11, fontWeight: 700,
                      color: "var(--color-text-muted)", letterSpacing: "0.04em", textTransform: "uppercase",
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pageRows.map(bed => {
                  const meta = bedStatusMeta(bed.status);
                  const occ = bed.current_admission;
                  return (
                    <tr key={bed.id} style={{ borderBottom: "1px solid var(--color-border)" }}>
                      <td style={{ padding: "10px 8px", fontWeight: 700, fontSize: 13.5 }}>{bed.bed_number}</td>
                      <td style={{ padding: "10px 8px" }}>
                        <Pill label={meta.label} bg={`${meta.color}1c`} text={meta.color} />
                      </td>
                      <td style={{ padding: "10px 8px" }}>
                        {occ ? (
                          <div>
                            <div style={{ fontWeight: 700, fontSize: 12.5 }}>{occ.patient_name}</div>
                            <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
                              UHID {occ.patient_uhid} · Admitted {formatDateTime(occ.admitted_at)}
                            </div>
                            {occ.expected_discharge_date && (
                              <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
                                Exp. discharge {formatDate(occ.expected_discharge_date)}
                              </div>
                            )}
                          </div>
                        ) : (
                          <span style={{ color: "var(--color-text-muted)" }}>—</span>
                        )}
                      </td>
                      <td style={{ padding: "10px 8px" }}><StatusDot active={bed.is_active} /></td>
                      <td style={{ padding: "10px 8px" }}>
                        <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 4 }}>
                          <button type="button" onClick={() => onEdit(bed)} title="Edit"
                            style={{ background: "none", border: "none", cursor: "pointer", padding: 6, color: "var(--color-text-muted)" }}>
                            <Pencil size={14} />
                          </button>
                          <KebabMenu items={[{ label: "Remove Bed", danger: true, onClick: () => onRemove(bed) }]} />
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 14 }}>
            <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
              Showing {pageRows.length} of {filtered.length} bed{filtered.length === 1 ? "" : "s"}
            </span>
            <Pagination page={page} pageCount={pageCount} onChange={setPage} />
          </div>
        </>
      )}
    </div>
  );
}

// ── Page ────────────────────────────────────────────────────────────────

export default function RoomsPage() {
  const { toastSuccess, toastApiError } = useToast();
  const [branchId, setBranchId] = useState("");

  const [rooms, setRooms] = useState([]);
  const [beds, setBeds] = useState([]);
  const [loadingRooms, setLoadingRooms] = useState(true);
  const [floors, setFloors] = useState([]);
  const [loadingFloors, setLoadingFloors] = useState(true);
  const [roomTypes, setRoomTypes] = useState([]);
  const [roomTypeAddOpen, setRoomTypeAddOpen] = useState(false);
  const [departments, setDepartments] = useState([]);

  const [selectedFloorId, setSelectedFloorId] = useState("");

  const [modal, setModal] = useState(null); // "room" | "floor" | "beds" | "bed"
  const [editing, setEditing] = useState(null);
  const [bedsModalRoom, setBedsModalRoom] = useState(null);
  const [saving, setSaving] = useState(false);

  const { data: branchData } = useApi(API_ENDPOINTS.ORG.BRANCHES);
  const branches = branchData || [];

  useEffect(() => {
    if (!branchId && branches.length) setBranchId(String(branches[0].id));
  }, [branches, branchId]);

  // Branch switch resets whichever floor was selected for the old branch —
  // the auto-select effect below immediately picks a fresh first one once
  // the new branch's data has loaded.
  function handleBranchChange(id) {
    setBranchId(id);
    setSelectedFloorId("");
  }

  const fetchFloors = useCallback(async () => {
    if (!branchId) { setFloors([]); setLoadingFloors(false); return; }
    setLoadingFloors(true);
    try {
      const { data: res } = await apiClient.get(API_ENDPOINTS.ORG.FLOORS, { params: { branch_id: branchId } });
      setFloors(res.data || []);
    } catch { setFloors([]); }
    finally { setLoadingFloors(false); }
  }, [branchId]);

  const fetchRoomsAndBeds = useCallback(async () => {
    if (!branchId) { setRooms([]); setBeds([]); setLoadingRooms(false); return; }
    setLoadingRooms(true);
    try {
      const [{ data: roomRes }, { data: bedRes }] = await Promise.all([
        apiClient.get(API_ENDPOINTS.ORG.ROOMS, { params: { branch_id: branchId } }),
        apiClient.get(API_ENDPOINTS.ORG.BEDS, { params: { branch_id: branchId } }),
      ]);
      setRooms(roomRes.data || []);
      setBeds(bedRes.data || []);
    } catch { setRooms([]); setBeds([]); }
    finally { setLoadingRooms(false); }
  }, [branchId]);

  const fetchRoomTypes = useCallback(() => {
    apiClient.get(API_ENDPOINTS.BILLING.ROOM_TYPES)
      .then(r => setRoomTypes(r.data?.data || []))
      .catch(() => setRoomTypes([]));
  }, []);

  const fetchDepartments = useCallback(async () => {
    if (!branchId) { setDepartments([]); return; }
    try {
      const { data: res } = await apiClient.get(API_ENDPOINTS.ORG.DEPARTMENTS, { params: { branch_id: branchId } });
      setDepartments(res.data || []);
    } catch { setDepartments([]); }
  }, [branchId]);

  useEffect(() => { fetchFloors(); fetchRoomsAndBeds(); fetchDepartments(); }, [fetchFloors, fetchRoomsAndBeds, fetchDepartments]);
  useEffect(() => { fetchRoomTypes(); }, [fetchRoomTypes]);

  useEffect(() => {
    if (!selectedFloorId && floors.length) setSelectedFloorId(String(floors[0].id));
  }, [floors, selectedFloorId]);

  const bedsByRoom = useMemo(() => {
    const map = {};
    for (const b of beds) (map[b.room] = map[b.room] || []).push(b);
    return map;
  }, [beds]);

  const selectedFloor = floors.find(f => String(f.id) === String(selectedFloorId)) || null;
  const isUnassignedView = selectedFloorId === "unassigned";
  // Rooms created before a Floor was picked for them (or from data that
  // predates the Floor model) have floor_obj = null — rather than silently
  // dropping them from every floor's list, they surface in this always-visible
  // bucket so nothing "disappears"; picking a floor for them here is the fix.
  const unassignedRooms = useMemo(() => rooms.filter(r => !r.floor_obj), [rooms]);
  const roomsOnFloor = useMemo(() => {
    if (isUnassignedView) return unassignedRooms;
    return rooms.filter(r => selectedFloor && String(r.floor_obj) === String(selectedFloor.id));
  }, [rooms, selectedFloor, isUnassignedView, unassignedRooms]);

  const bedsModalRoomTypeMeta = bedsModalRoom ? roomTypeMeta(bedsModalRoom.room_type, roomTypes) : null;
  const bedsInModalRoom = useMemo(
    () => (bedsModalRoom ? (bedsByRoom[bedsModalRoom.id] || []) : []),
    [bedsModalRoom, bedsByRoom],
  );

  // Branch-wide bed status totals for the top stat row.
  const bedStatusTotals = useMemo(() => {
    const t = { available: 0, occupied: 0, cleaning: 0, blocked: 0, out_of_service: 0 };
    beds.forEach(b => { if (t[b.status] !== undefined) t[b.status]++; });
    return t;
  }, [beds]);

  // ── Floor CRUD ──
  async function handleCreateFloor(form) {
    setSaving(true);
    try {
      await apiClient.post(API_ENDPOINTS.ORG.FLOORS, { ...form, branch: Number(branchId), level: Number(form.level) || 0 });
      toastSuccess(`Floor "${form.name}" created.`);
      setModal(null); fetchFloors();
    } catch (err) { toastApiError(err, "Failed to create floor."); }
    finally { setSaving(false); }
  }
  async function handleUpdateFloor(form) {
    setSaving(true);
    try {
      await apiClient.patch(API_ENDPOINTS.ORG.FLOOR(editing.id), { name: form.name, level: Number(form.level) || 0 });
      toastSuccess("Floor updated.");
      setModal(null); setEditing(null); fetchFloors(); fetchRoomsAndBeds();
    } catch (err) { toastApiError(err, "Failed to update floor."); }
    finally { setSaving(false); }
  }
  async function handleRemoveFloor(floor) {
    if (!confirm(`Remove floor "${floor.name}"? Rooms on it will keep their name but show no floor until reassigned.`)) return;
    try {
      await apiClient.delete(API_ENDPOINTS.ORG.FLOOR(floor.id));
      toastSuccess("Floor removed.");
      if (String(selectedFloorId) === String(floor.id)) setSelectedFloorId("");
      fetchFloors();
    } catch (err) { toastApiError(err, "Failed to remove floor."); }
  }
  async function handleGenerateFloors(count) {
    setSaving(true);
    const toCreate = [
      { name: "Ground", level: 0 },
      ...Array.from({ length: Math.max(0, count) }, (_, i) => ({ name: `${ordinal(i + 1)} Floor`, level: i + 1 })),
    ];
    let created = 0, skipped = 0, failed = 0;
    for (const f of toCreate) {
      try {
        await apiClient.post(API_ENDPOINTS.ORG.FLOORS, { branch: Number(branchId), name: f.name, level: f.level });
        created++;
      } catch (err) {
        if (err?.response?.status === 400 || err?.response?.status === 409) skipped++;
        else { failed++; toastApiError(err, `Failed to create "${f.name}".`); }
      }
    }
    setSaving(false);
    setModal(null);
    fetchFloors();
    if (created > 0) toastSuccess(`Created ${created} floor${created === 1 ? "" : "s"}.${skipped > 0 ? ` ${skipped} already existed.` : ""}`);
    else if (skipped > 0 && failed === 0) toastSuccess("Those floors already exist.");
  }

  // ── Room CRUD ──
  async function handleCreateRoom(form, isBedBased) {
    setSaving(true);
    try {
      await apiClient.post(API_ENDPOINTS.ORG.ROOMS, {
        branch: Number(form.branch), name: form.name, room_type: form.room_type,
        floor_obj: form.floor_obj ? Number(form.floor_obj) : null,
        department: form.department ? Number(form.department) : null,
        capacity: isBedBased && form.capacity ? Number(form.capacity) : null,
      });
      toastSuccess(`Room "${form.name}" created.`);
      setModal(null); fetchRoomsAndBeds();
    } catch (err) { toastApiError(err, "Failed to create room."); }
    finally { setSaving(false); }
  }
  async function handleUpdateRoom(form, isBedBased) {
    setSaving(true);
    try {
      await apiClient.patch(API_ENDPOINTS.ORG.ROOM(editing.id), {
        branch: Number(form.branch), name: form.name, room_type: form.room_type,
        floor_obj: form.floor_obj ? Number(form.floor_obj) : null,
        department: form.department ? Number(form.department) : null,
        capacity: isBedBased && form.capacity ? Number(form.capacity) : null,
      });
      toastSuccess("Room updated.");
      setModal(null); setEditing(null); fetchRoomsAndBeds();
    } catch (err) { toastApiError(err, "Failed to update room."); }
    finally { setSaving(false); }
  }
  async function handleDeactivateRoom(room) {
    if (!confirm(`Remove room "${room.name}"? Any doctor assignments or beds for it will be left as-is.`)) return;
    try {
      await apiClient.delete(API_ENDPOINTS.ORG.ROOM(room.id));
      toastSuccess("Room removed.");
      fetchRoomsAndBeds();
    } catch (err) { toastApiError(err, "Failed to remove room."); }
  }

  // ── Bed CRUD ──
  async function handleCreateBed(form) {
    setSaving(true);
    try {
      await apiClient.post(API_ENDPOINTS.ORG.BEDS, { room: Number(bedsModalRoom.id), bed_number: form.bed_number });
      toastSuccess(`Bed "${form.bed_number}" added to ${bedsModalRoom.name}.`);
      setModal("beds"); setEditing(null); fetchRoomsAndBeds();
    } catch (err) { toastApiError(err, "Failed to add bed."); }
    finally { setSaving(false); }
  }
  async function handleUpdateBed(form) {
    setSaving(true);
    try {
      await apiClient.patch(API_ENDPOINTS.ORG.BED(editing.id), { bed_number: form.bed_number });
      toastSuccess("Bed updated.");
      setModal("beds"); setEditing(null); fetchRoomsAndBeds();
    } catch (err) { toastApiError(err, "Failed to update bed."); }
    finally { setSaving(false); }
  }
  async function handleRemoveBed(bed) {
    if (!confirm(`Remove bed "${bed.bed_number}"?`)) return;
    try {
      await apiClient.delete(API_ENDPOINTS.ORG.BED(bed.id));
      toastSuccess("Bed removed.");
      fetchRoomsAndBeds();
    } catch (err) { toastApiError(err, "Failed to remove bed."); }
  }

  function handleExportBedList() {
    if (!bedsModalRoom) return;
    const rows = [
      ["Bed Number", "Status", "Is Active", "Patient", "UHID", "Admitted", "Expected Discharge"],
      ...bedsInModalRoom.map(b => [
        b.bed_number,
        bedStatusMeta(b.status).label,
        b.is_active ? "Active" : "Inactive",
        b.current_admission?.patient_name || "",
        b.current_admission?.patient_uhid || "",
        b.current_admission ? formatDateTime(b.current_admission.admitted_at) : "",
        b.current_admission?.expected_discharge_date ? formatDate(b.current_admission.expected_discharge_date) : "",
      ]),
    ];
    const csv = rows.map(r => r.map(v => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${bedsModalRoom.name.replace(/\s+/g, "_")}_beds.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  // Room Type add-form's extra fields (category + bed-based) — see
  // billing.OptionList's docstring for why this one catalog now carries
  // both OPD and bed-based IPD types.
  const roomTypeExtraFields = [
    { name: "category", type: "select", label: "Category", options: ROOM_TYPE_CATEGORY_OPTIONS, default: "opd" },
    { name: "is_bed_based", type: "checkbox", label: "Bed-based (IPD)", default: false },
  ];

  return (
    <AppShell>
      <PageShell title="Rooms & Floors">
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 4, gap: 16, flexWrap: "wrap" }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 26, fontWeight: 800 }}>Rooms & Floors</h1>
            <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginTop: 4 }}>
              Manage floors, rooms and beds{branches.find(b => String(b.id) === String(branchId)) ? ` for ${branches.find(b => String(b.id) === String(branchId)).name}` : ""}
            </div>
          </div>
          <BranchSelector branches={branches} value={branchId} onChange={handleBranchChange} />
        </div>

        <div style={{ display: "flex", gap: 16, margin: "20px 0", flexWrap: "wrap" }}>
          <StatCard icon={Building2} value={floors.length} label="Total Floors" />
          <StatCard icon={DoorOpen} value={rooms.length} label="Total Rooms" />
          <StatCard icon={BedIcon} value={beds.length} label="Total Beds" />
          <StatCard icon={BedIcon} value={bedStatusTotals.available} label="Available Beds" iconBg="#e3f7ec" iconColor="#1a7f37" />
          <StatCard icon={BedIcon} value={bedStatusTotals.occupied} label="Occupied Beds" iconBg="#fde8e8" iconColor="#c0362c" />
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "340px 1fr", gap: 20, alignItems: "start" }}>
          {/* Left column: Floors + Room Types */}
          <div>
            <div className="card" style={{ padding: 18, marginBottom: 20 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
                <h3 style={{ margin: 0, fontSize: 15.5 }}>Floors</h3>
                <button onClick={() => { setEditing(null); setModal("floor"); }} disabled={!branchId}
                  className="btn-outline" style={{ fontSize: 12, padding: "6px 14px" }}>
                  + Add Floor
                </button>
              </div>
              {loadingFloors ? (
                <div style={{ fontSize: 12.5, color: "var(--color-text-muted)" }}>Loading…</div>
              ) : floors.length === 0 ? (
                <div style={{ fontSize: 12.5, color: "var(--color-text-muted)", fontStyle: "italic" }}>
                  No floors set up yet — add one, or use Quick Setup to create several at once.
                </div>
              ) : (
                floors.map(f => (
                  <FloorListItem key={f.id} floor={f}
                    roomCount={rooms.filter(r => String(r.floor_obj) === String(f.id)).length}
                    selected={String(selectedFloorId) === String(f.id)}
                    onSelect={() => setSelectedFloorId(String(f.id))} />
                ))
              )}
              {unassignedRooms.length > 0 && (
                <FloorListItem
                  floor={{ id: "unassigned", name: "Unassigned Rooms", level: null }}
                  icon={HelpCircle}
                  roomCount={unassignedRooms.length}
                  selected={isUnassignedView}
                  onSelect={() => setSelectedFloorId("unassigned")} />
              )}
            </div>

            <div className="card" style={{ padding: 18 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 2 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                  <Tag size={15} style={{ color: "var(--color-text-muted)" }} />
                  <h3 style={{ margin: 0, fontSize: 15.5 }}>Room Types</h3>
                </div>
                <button onClick={() => setRoomTypeAddOpen(o => !o)} className="btn-outline" style={{ fontSize: 12, padding: "6px 14px" }}>
                  + Add Type
                </button>
              </div>
              <div style={{ fontSize: 11.5, color: "var(--color-text-muted)", margin: "4px 0 14px" }}>
                One catalog for every kind of room — OPD (Consultation, Procedure…) and bed-based IPD (General Ward, ICU…) alike.
              </div>
              <DropdownListEditor
                title="" compact
                listEndpoint={API_ENDPOINTS.BILLING.ROOM_TYPES}
                itemEndpoint={API_ENDPOINTS.BILLING.ROOM_TYPE}
                identityField="value"
                extraFields={roomTypeExtraFields}
                showAddForm={roomTypeAddOpen}
                onAdded={() => setRoomTypeAddOpen(false)}
                onChange={fetchRoomTypes}
                dotColorForIndex={(i) => TYPE_COLOR_PALETTE[i % TYPE_COLOR_PALETTE.length].text}
                badgeForItem={(item) => (
                  <span style={{
                    fontSize: 9.5, fontWeight: 700, padding: "1px 6px", borderRadius: 999,
                    background: "var(--color-bg)", border: "1px solid var(--color-border)", color: "var(--color-text-muted)",
                    textTransform: "uppercase", letterSpacing: "0.03em",
                  }}>
                    {item.is_bed_based ? "Beds" : (item.category || "OPD")}
                  </span>
                )}
              />
              <RoomTypeRatesEditor roomTypes={roomTypes} onSaved={fetchRoomTypes} />
            </div>
          </div>

          {/* Right column: selected floor's rooms */}
          <div className="card" style={{ padding: 22 }}>
            {!selectedFloor && !isUnassignedView ? (
              <div style={{ textAlign: "center", padding: "60px 0", color: "var(--color-text-muted)" }}>
                <Building2 size={36} style={{ marginBottom: 12 }} />
                <div style={{ fontWeight: 600, fontSize: 15, marginBottom: 6 }}>No floor selected</div>
                <div style={{ fontSize: 12.5 }}>Add a floor on the left to get started.</div>
              </div>
            ) : (
              <>
                <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 18, gap: 12, flexWrap: "wrap" }}>
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <h2 style={{ margin: 0, fontSize: 20, fontWeight: 800 }}>
                        {isUnassignedView ? "Unassigned Rooms" : selectedFloor.name}
                      </h2>
                      {!isUnassignedView && (
                        <span style={{ fontSize: 11, fontWeight: 700, padding: "3px 10px", borderRadius: 999, background: "var(--color-bg)", border: "1px solid var(--color-border)", color: "var(--color-text-muted)" }}>
                          Level {selectedFloor.level}
                        </span>
                      )}
                    </div>
                    <div style={{ fontSize: 12.5, color: "var(--color-text-muted)", marginTop: 4 }}>
                      {isUnassignedView
                        ? `${roomsOnFloor.length} room${roomsOnFloor.length === 1 ? "" : "s"} not yet assigned to a floor — edit a room to move it`
                        : `${roomsOnFloor.length} room${roomsOnFloor.length === 1 ? "" : "s"} in this floor`}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 8 }}>
                    {!isUnassignedView && (
                      <>
                        <button className="btn-outline" style={{ fontSize: 12.5, padding: "8px 14px" }}
                          onClick={() => { setEditing(selectedFloor); setModal("floor"); }}>
                          <Pencil size={13} style={{ marginRight: 6, verticalAlign: -2 }} /> Edit Floor
                        </button>
                        <button style={{ fontSize: 12.5, padding: "8px 14px", borderRadius: 8, border: "1.5px solid var(--color-error)", background: "none", color: "var(--color-error)", cursor: "pointer", fontWeight: 600 }}
                          onClick={() => handleRemoveFloor(selectedFloor)}>
                          Delete
                        </button>
                      </>
                    )}
                    <button className="btn-primary" style={{ fontSize: 12.5, padding: "8px 16px" }}
                      onClick={() => { setEditing(null); setModal("room"); }}>
                      + Add Room
                    </button>
                  </div>
                </div>

                {loadingRooms ? (
                  <div style={{ textAlign: "center", padding: 40, color: "var(--color-text-muted)" }}>Loading…</div>
                ) : (
                  <RoomsTable rooms={roomsOnFloor} roomTypes={roomTypes} bedsByRoom={bedsByRoom}
                    onEdit={(r) => { setEditing(r); setModal("room"); }}
                    onDeactivate={handleDeactivateRoom}
                    onManageBeds={(r) => { setBedsModalRoom(r); setModal("beds"); }} />
                )}
              </>
            )}
          </div>
        </div>

        {modal === "room" && (
          <Modal title={editing ? "Edit Room" : "Add Room"} onClose={() => { setModal(null); setEditing(null); }}>
            <RoomForm branches={branches} floors={floors} roomTypes={roomTypes} departments={departments}
              initial={editing
                ? { ...editing, branch: String(editing.branch), floor_obj: editing.floor_obj ? String(editing.floor_obj) : "",
                    department: editing.department ? String(editing.department) : "",
                    capacity: editing.capacity != null ? String(editing.capacity) : "" }
                : { ...EMPTY_ROOM, branch: branchId, floor_obj: isUnassignedView ? "" : selectedFloorId }}
              onSave={editing ? handleUpdateRoom : handleCreateRoom}
              onCancel={() => { setModal(null); setEditing(null); }} saving={saving} />
          </Modal>
        )}

        {modal === "floor" && (
          <Modal title={editing ? "Edit Floor" : "Add Floor"} onClose={() => { setModal(null); setEditing(null); }}>
            <FloorForm initial={editing ? { ...editing, level: String(editing.level) } : { ...EMPTY_FLOOR, branch: branchId }}
              onSave={editing ? handleUpdateFloor : handleCreateFloor}
              onGenerate={handleGenerateFloors}
              onCancel={() => { setModal(null); setEditing(null); }} saving={saving} />
          </Modal>
        )}

        {modal === "beds" && bedsModalRoom && (
          <Modal title={`${bedsModalRoom.name} — Beds`} width={720} onClose={() => { setModal(null); setBedsModalRoom(null); }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16, flexWrap: "wrap", gap: 10 }}>
              <div style={{ fontSize: 12.5, color: "var(--color-text-muted)" }}>
                {bedsModalRoomTypeMeta?.label} · {bedsLabel(bedsModalRoom, true)}
                {bedCapacityReached(bedsModalRoom, true) && <span style={{ color: "var(--color-text-muted)", fontWeight: 700 }}> · At capacity</span>}
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button type="button" onClick={handleExportBedList}
                  style={{ display: "flex", alignItems: "center", gap: 6, padding: "7px 12px", borderRadius: 8, border: "1.5px solid var(--color-border)", background: "none", cursor: "pointer", fontSize: 12.5, fontWeight: 600 }}>
                  <Download size={13} /> Export
                </button>
                <button className="btn-primary" style={{ fontSize: 12.5, padding: "7px 14px", opacity: bedCapacityReached(bedsModalRoom, true) ? 0.5 : 1, cursor: bedCapacityReached(bedsModalRoom, true) ? "default" : "pointer" }}
                  disabled={bedCapacityReached(bedsModalRoom, true)}
                  title={bedCapacityReached(bedsModalRoom, true) ? "This room is at full capacity — increase its capacity or remove a bed first." : undefined}
                  onClick={() => { setEditing(null); setModal("bed"); }}>
                  + Add Bed
                </button>
              </div>
            </div>
            <BedsTable beds={bedsInModalRoom}
              onEdit={(b) => { setEditing(b); setModal("bed"); }}
              onRemove={handleRemoveBed} />
          </Modal>
        )}

        {modal === "bed" && (
          <Modal title={editing ? "Edit Bed" : `Add Bed — ${bedsModalRoom?.name || ""}`} onClose={() => { setModal("beds"); setEditing(null); }}>
            <BedForm initial={editing || null}
              onSave={editing ? handleUpdateBed : handleCreateBed}
              onCancel={() => { setModal("beds"); setEditing(null); }} saving={saving} />
          </Modal>
        )}
      </PageShell>
    </AppShell>
  );
}
