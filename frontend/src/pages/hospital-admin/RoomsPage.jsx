/** pages/hospital-admin/RoomsPage.jsx */

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

const EMPTY_ROOM = { branch: "", floor_obj: "", name: "", room_type: "consultation", department: "" };
const EMPTY_FLOOR = { branch: "", name: "", level: "0" };

// Room Type is a single hospital-configurable catalog (billing.OptionList,
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
  return { label, ...color };
}

// 1 -> "1st", 2 -> "2nd", 3 -> "3rd", 4 -> "4th", 11 -> "11th", 21 -> "21st"...
function ordinal(n) {
  const j = n % 10, k = n % 100;
  if (j === 1 && k !== 11) return `${n}st`;
  if (j === 2 && k !== 12) return `${n}nd`;
  if (j === 3 && k !== 13) return `${n}rd`;
  return `${n}th`;
}

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
function BranchSelector({ branches, value, onChange }) {
  const selected = branches.find(b => String(b.branch_id) === String(value));
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
        {branches.map(b => <option key={b.branch_id} value={b.branch_id}>{b.name}</option>)}
      </select>
    </div>
  );
}

// ── Floors ──────────────────────────────────────────────────────────────

function FloorForm({ initial, onSave, onGenerate, onCancel, saving }) {
  const [mode, setMode] = useState("single");
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

function RoomForm({ branches, floors, roomTypes, departments, initial, onSave, onCancel, saving }) {
  const [form, setForm] = useState(initial || EMPTY_ROOM);
  const set = (k) => (v) => setForm(f => ({ ...f, [k]: v }));

  function submit(e) {
    e.preventDefault();
    onSave(form);
  }

  return (
    <form onSubmit={submit}>
      <Select label="Branch *" value={form.branch} onChange={set("branch")}
        options={branches.map(b => ({ value: String(b.branch_id), label: b.name }))} required />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <Select label="Floor *" value={form.floor_obj} onChange={set("floor_obj")}
          options={floors.map(f => ({ value: String(f.floor_id), label: f.name }))}
          hint={floors.length === 0 ? "No floors set up yet — add one first." : "The room is at this floor's branch."} required />
        <Field label="Room Number / Name *" value={form.name} onChange={set("name")} placeholder="e.g. OPD-01, Ward 1, ICU-A" required />
      </div>
      <Select label="Room Type *" value={form.room_type} onChange={set("room_type")}
        options={roomTypes.map(t => ({ value: t.value, label: t.label }))}
        hint={roomTypes.length === 0 ? "No room types configured yet." : undefined} required />
      <Select label="Department (optional)" value={form.department} onChange={set("department")}
        options={departments.map(d => ({ value: String(d.department_id), label: d.name }))}
        hint="Only needed if this room belongs to a specific clinical department." />
      <ModalActions onCancel={onCancel} saving={saving}
        disabled={!form.branch || !form.floor_obj || !form.name || !form.room_type}
        submitLabel={initial ? "Update Room" : "Create Room"} />
    </form>
  );
}

function RoomsTable({ rooms, roomTypes, onEdit, onDeactivate }) {
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
                  {["Room", "Room Type", "Actions"].map((h, i) => (
                    <th key={h} style={{
                      textAlign: i === 2 ? "right" : "left", padding: "0 8px 10px", fontSize: 11, fontWeight: 700,
                      color: "var(--color-text-muted)", letterSpacing: "0.04em", textTransform: "uppercase",
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pageRows.map(room => {
                  const meta = roomTypeMeta(room.room_type, roomTypes);
                  return (
                    <tr key={room.room_id} style={{ borderBottom: "1px solid var(--color-border)" }}>
                      <td style={{ padding: "12px 8px" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                          <div style={{ width: 30, height: 30, borderRadius: 8, background: "var(--color-bg)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                            <DoorOpen size={14} style={{ color: "var(--color-text-muted)" }} />
                          </div>
                          <div>
                            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                              <span style={{ fontWeight: 700, fontSize: 13.5 }}>{room.name}</span>
                            </div>
                            {room.department_name && <div style={{ fontSize: 11.5, color: "var(--color-text-muted)" }}>{room.department_name}</div>}
                          </div>
                        </div>
                      </td>
                      <td style={{ padding: "12px 8px" }}><Pill label={meta.label} bg={meta.bg} text={meta.text} /></td>
                      <td style={{ padding: "12px 8px" }}>
                        <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 4 }}>
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

export default function RoomsPage() {
  const { toastSuccess, toastApiError } = useToast();
  const [branchId, setBranchId] = useState("");

  const [rooms, setRooms] = useState([]);
  const [loadingRooms, setLoadingRooms] = useState(true);
  const [floors, setFloors] = useState([]);
  const [loadingFloors, setLoadingFloors] = useState(true);
  const [roomTypes, setRoomTypes] = useState([]);
  const [roomTypeAddOpen, setRoomTypeAddOpen] = useState(false);
  const [departments, setDepartments] = useState([]);

  const [selectedFloorId, setSelectedFloorId] = useState("");

  const [modal, setModal] = useState(null); // "room" | "floor"
  const [editing, setEditing] = useState(null);
  const [saving, setSaving] = useState(false);

  const { data: branchData } = useApi(API_ENDPOINTS.ORG.BRANCHES);
  const branches = useMemo(() => branchData || [], [branchData]);

  useEffect(() => {
    if (!branchId && branches.length) setBranchId(String(branches[0].branch_id));
  }, [branches, branchId]);

  // Branch switch resets whichever floor was selected for the old branch —
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

  const fetchRooms = useCallback(async () => {
    if (!branchId) { setRooms([]); setLoadingRooms(false); return; }
    setLoadingRooms(true);
    try {
      const { data: roomRes } = await apiClient.get(API_ENDPOINTS.ORG.ROOMS, { params: { branch_id: branchId } });
      setRooms(roomRes.data || []);
    } catch { setRooms([]); }
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

  useEffect(() => { fetchFloors(); fetchRooms(); fetchDepartments(); }, [fetchFloors, fetchRooms, fetchDepartments]);
  useEffect(() => { fetchRoomTypes(); }, [fetchRoomTypes]);

  useEffect(() => {
    if (!selectedFloorId && floors.length) setSelectedFloorId(String(floors[0].floor_id));
  }, [floors, selectedFloorId]);

  const selectedFloor = floors.find(f => String(f.floor_id) === String(selectedFloorId)) || null;
  const roomsOnFloor = useMemo(
    () => rooms.filter(r => selectedFloor && String(r.floor_obj) === String(selectedFloor.floor_id)),
    [rooms, selectedFloor],
  );

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
      await apiClient.patch(API_ENDPOINTS.ORG.FLOOR(editing.floor_id), { name: form.name, level: Number(form.level) || 0 });
      toastSuccess("Floor updated.");
      setModal(null); setEditing(null); fetchFloors(); fetchRooms();
    } catch (err) { toastApiError(err, "Failed to update floor."); }
    finally { setSaving(false); }
  }
  async function handleRemoveFloor(floor) {
    if (!confirm(`Remove floor "${floor.name}"? Rooms on it will keep their name but show no floor until reassigned.`)) return;
    try {
      await apiClient.delete(API_ENDPOINTS.ORG.FLOOR(floor.floor_id));
      toastSuccess("Floor removed.");
      if (String(selectedFloorId) === String(floor.floor_id)) setSelectedFloorId("");
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
  async function handleCreateRoom(form) {
    setSaving(true);
    try {
      await apiClient.post(API_ENDPOINTS.ORG.ROOMS, {
        branch: Number(form.branch), name: form.name, room_type: form.room_type,
        floor_obj: Number(form.floor_obj),
        department: form.department ? Number(form.department) : null,
      });
      toastSuccess(`Room "${form.name}" created.`);
      setModal(null); fetchRooms();
    } catch (err) { toastApiError(err, "Failed to create room."); }
    finally { setSaving(false); }
  }
  async function handleUpdateRoom(form) {
    setSaving(true);
    try {
      await apiClient.patch(API_ENDPOINTS.ORG.ROOM(editing.room_id), {
        branch: Number(form.branch), name: form.name, room_type: form.room_type,
        floor_obj: Number(form.floor_obj),
        department: form.department ? Number(form.department) : null,
      });
      toastSuccess("Room updated.");
      setModal(null); setEditing(null); fetchRooms();
    } catch (err) { toastApiError(err, "Failed to update room."); }
    finally { setSaving(false); }
  }
  async function handleDeactivateRoom(room) {
    if (!confirm(`Remove room "${room.name}"? Any doctor assignments for it will be left as-is.`)) return;
    try {
      await apiClient.delete(API_ENDPOINTS.ORG.ROOM(room.room_id));
      toastSuccess("Room removed.");
      fetchRooms();
    } catch (err) { toastApiError(err, "Failed to remove room."); }
  }

  return (
    <AppShell>
      <PageShell title="Rooms & Floors">
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 4, gap: 16, flexWrap: "wrap" }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 26, fontWeight: 800 }}>Rooms & Floors</h1>
            <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginTop: 4 }}>
              Manage floors and rooms{branches.find(b => String(b.branch_id) === String(branchId)) ? ` for ${branches.find(b => String(b.branch_id) === String(branchId)).name}` : ""}
            </div>
          </div>
          <BranchSelector branches={branches} value={branchId} onChange={handleBranchChange} />
        </div>

        <div style={{ display: "flex", gap: 16, margin: "20px 0", flexWrap: "wrap" }}>
          <StatCard icon={Building2} value={floors.length} label="Total Floors" />
          <StatCard icon={DoorOpen} value={rooms.length} label="Total Rooms" />
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
                  <FloorListItem key={f.floor_id} floor={f}
                    roomCount={rooms.filter(r => String(r.floor_obj) === String(f.floor_id)).length}
                    selected={String(selectedFloorId) === String(f.floor_id)}
                    onSelect={() => setSelectedFloorId(String(f.floor_id))} />
                ))
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
                One catalog for every kind of room — Consultation, Procedure and so on.
              </div>
              <DropdownListEditor
                title="" compact
                listEndpoint={API_ENDPOINTS.BILLING.ROOM_TYPES}
                itemEndpoint={API_ENDPOINTS.BILLING.ROOM_TYPE}
                identityField="value"
                showAddForm={roomTypeAddOpen}
                onAdded={() => setRoomTypeAddOpen(false)}
                onChange={fetchRoomTypes}
                dotColorForIndex={(i) => TYPE_COLOR_PALETTE[i % TYPE_COLOR_PALETTE.length].text}
              />
            </div>
          </div>

          {/* Right column: selected floor's rooms */}
          <div className="card" style={{ padding: 22 }}>
            {!selectedFloor ? (
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
                        {selectedFloor.name}
                      </h2>
                      <span style={{ fontSize: 11, fontWeight: 700, padding: "3px 10px", borderRadius: 999, background: "var(--color-bg)", border: "1px solid var(--color-border)", color: "var(--color-text-muted)" }}>
                        Level {selectedFloor.level}
                      </span>
                    </div>
                    <div style={{ fontSize: 12.5, color: "var(--color-text-muted)", marginTop: 4 }}>
                      {`${roomsOnFloor.length} room${roomsOnFloor.length === 1 ? "" : "s"} in this floor`}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button className="btn-outline" style={{ fontSize: 12.5, padding: "8px 14px" }}
                      onClick={() => { setEditing(selectedFloor); setModal("floor"); }}>
                      <Pencil size={13} style={{ marginRight: 6, verticalAlign: -2 }} /> Edit Floor
                    </button>
                    <button style={{ fontSize: 12.5, padding: "8px 14px", borderRadius: 8, border: "1.5px solid var(--color-error)", background: "none", color: "var(--color-error)", cursor: "pointer", fontWeight: 600 }}
                      onClick={() => handleRemoveFloor(selectedFloor)}>
                      Delete
                    </button>
                    <button className="btn-primary" style={{ fontSize: 12.5, padding: "8px 16px" }}
                      onClick={() => { setEditing(null); setModal("room"); }}>
                      + Add Room
                    </button>
                  </div>
                </div>

                {loadingRooms ? (
                  <div style={{ textAlign: "center", padding: 40, color: "var(--color-text-muted)" }}>Loading…</div>
                ) : (
                  <RoomsTable rooms={roomsOnFloor} roomTypes={roomTypes}
                    onEdit={(r) => { setEditing(r); setModal("room"); }}
                    onDeactivate={handleDeactivateRoom} />
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
                    department: editing.department ? String(editing.department) : "" }
                : { ...EMPTY_ROOM, branch: branchId, floor_obj: selectedFloorId }}
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

      </PageShell>
    </AppShell>
  );
}
