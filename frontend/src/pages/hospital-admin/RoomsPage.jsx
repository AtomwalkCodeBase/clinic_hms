/**
 * pages/hospital-admin/RoomsPage.jsx
 * ------------------------------------
 * Hospital admin: manage rooms (per branch, per floor) — add, rename, move
 * floor, deactivate. Which doctor sits in which room and when is tagged
 * from the doctor's own profile (Staff → Profile → Working Hours & Rooms),
 * right on top of their weekly availability, not here — this page shows
 * the resulting weekly schedule read-only per room for visibility, and lets
 * you pull an assignment off a room in a pinch. Several doctors can share
 * the same room across the week (e.g. Dr. A 9-1, Dr. B 1-3, Dr. C 3-5) —
 * the backend rejects any overlapping time on the same room+day with a 409.
 */

import { useState, useEffect, useCallback } from "react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import apiClient     from "../../services/api.client";
import { useToast }  from "../../hooks/useToast";
import { useApi }    from "../../hooks/useApi";
import API_ENDPOINTS from "../../config/api.config";
import { DoorOpen } from "lucide-react";

const EMPTY_ROOM = { branch: "", floor: "", name: "", room_type: "consultation" };

const ROOM_TYPES = [
  { value: "consultation", label: "Consultation" },
  { value: "procedure",    label: "Procedure" },
  { value: "other",        label: "Other" },
];

function Modal({ title, children, onClose }) {
  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 1000,
      background: "rgba(0,0,0,0.45)",
      display: "flex", alignItems: "center", justifyContent: "center", padding: 24,
    }}>
      <div style={{
        background: "var(--color-surface)", borderRadius: 16,
        width: "100%", maxWidth: 480, padding: 32,
        boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
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

function Select({ label, value, onChange, options, required }) {
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
    </div>
  );
}

function RoomForm({ branches, initial, onSave, onCancel, saving }) {
  const [form, setForm] = useState(initial || EMPTY_ROOM);
  const set = (k) => (v) => setForm(f => ({ ...f, [k]: v }));

  function submit(e) {
    e.preventDefault();
    onSave(form);
  }

  return (
    <form onSubmit={submit}>
      <Select label="Branch *" value={form.branch} onChange={set("branch")}
        options={branches.map(b => ({ value: String(b.id), label: b.name }))} required />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <Field label="Floor" value={form.floor} onChange={set("floor")} placeholder="e.g. 2 or Ground" />
        <Field label="Room Name / Number *" value={form.name} onChange={set("name")} placeholder="e.g. Room 204" required />
      </div>
      <Select label="Room Type" value={form.room_type} onChange={set("room_type")} options={ROOM_TYPES} />
      <div style={{ display: "flex", gap: 10, marginTop: 8 }}>
        <button type="button" onClick={onCancel}
          style={{ flex: 1, padding: "9px 0", borderRadius: 8, border: "1.5px solid var(--color-border)", background: "none", cursor: "pointer", fontSize: 14, fontWeight: 600 }}>
          Cancel
        </button>
        <button type="submit" disabled={saving || !form.branch || !form.name} className="btn-primary" style={{ flex: 2 }}>
          {saving ? "Saving…" : (initial ? "Update Room" : "Create Room")}
        </button>
      </div>
    </form>
  );
}

function AssignmentRow({ a, onDelete }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "8px 12px", borderRadius: 8, background: "var(--color-bg)",
      border: "1px solid var(--color-border)", marginBottom: 6,
    }}>
      <div style={{ fontSize: 12.5 }}>
        <span style={{ fontWeight: 700 }}>{a.day_label}</span>
        <span style={{ color: "var(--color-text-muted)" }}> · {a.start_time?.slice(0, 5)}–{a.end_time?.slice(0, 5)} · </span>
        <span>Dr. {a.doctor_name}</span>
      </div>
      <button onClick={() => onDelete(a)}
        style={{ background: "none", border: "none", color: "var(--color-error)", cursor: "pointer", fontSize: 11, fontWeight: 600 }}>
        Remove
      </button>
    </div>
  );
}

function RoomCard({ room, onEdit, onDeactivate }) {
  const { toastSuccess, toastApiError } = useToast();
  const [expanded, setExpanded] = useState(false);
  const [assignments, setAssignments] = useState([]);
  const [loadingAssignments, setLoadingAssignments] = useState(false);

  const fetchAssignments = useCallback(async () => {
    setLoadingAssignments(true);
    try {
      const { data: res } = await apiClient.get(API_ENDPOINTS.ORG.ROOM_ASSIGNMENTS, { params: { room_id: room.id } });
      setAssignments(res.data || []);
    } catch { setAssignments([]); }
    finally { setLoadingAssignments(false); }
  }, [room.id]);

  useEffect(() => { if (expanded) fetchAssignments(); }, [expanded, fetchAssignments]);

  async function removeAssignment(a) {
    if (!confirm(`Remove Dr. ${a.doctor_name}'s ${a.day_label} slot from ${room.name}?`)) return;
    try {
      await apiClient.delete(API_ENDPOINTS.ORG.ROOM_ASSIGNMENT(a.id));
      toastSuccess("Assignment removed.");
      fetchAssignments();
    } catch (err) { toastApiError(err, "Could not remove assignment."); }
  }

  return (
    <div className="card" style={{ padding: 0, overflow: "hidden" }}>
      <div style={{ padding: "14px 18px", display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ flex: 1, cursor: "pointer" }} onClick={() => setExpanded(e => !e)}>
          <div style={{ fontWeight: 700, fontSize: 15 }}>{room.name}</div>
          <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 2 }}>
            Floor {room.floor || "—"} · {ROOM_TYPES.find(t => t.value === room.room_type)?.label || room.room_type}
          </div>
        </div>
        <button onClick={() => onEdit(room)}
          style={{ padding: "5px 12px", borderRadius: 7, border: "1.5px solid var(--color-border)", background: "none", cursor: "pointer", fontSize: 12, fontWeight: 600 }}>
          Edit
        </button>
        <button onClick={() => onDeactivate(room)}
          style={{ padding: "5px 12px", borderRadius: 7, border: "1.5px solid var(--color-error)", background: "none", cursor: "pointer", fontSize: 12, fontWeight: 600, color: "var(--color-error)" }}>
          Remove
        </button>
        <span style={{ cursor: "pointer", color: "var(--color-text-muted)" }} onClick={() => setExpanded(e => !e)}>
          {expanded ? "▾" : "▸"}
        </span>
      </div>

      {expanded && (
        <div style={{ padding: "0 18px 16px", borderTop: "1px solid var(--color-border)", paddingTop: 12 }}>
          <div style={{ marginBottom: 10 }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", letterSpacing: "0.05em" }}>
              WEEKLY SCHEDULE
            </span>
            <div style={{ fontSize: 11.5, color: "var(--color-text-muted)", marginTop: 4 }}>
              To assign a doctor to this room, open their profile from Staff → Profile → Working Hours & Rooms.
            </div>
          </div>

          {loadingAssignments ? (
            <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>Loading…</div>
          ) : assignments.length === 0 ? (
            <div style={{ fontSize: 12, color: "var(--color-text-muted)", fontStyle: "italic" }}>
              No doctors assigned to this room yet.
            </div>
          ) : (
            assignments
              .slice()
              .sort((a, b) => a.day_of_week - b.day_of_week || a.start_time.localeCompare(b.start_time))
              .map(a => <AssignmentRow key={a.id} a={a} onDelete={removeAssignment} />)
          )}
        </div>
      )}
    </div>
  );
}

export default function RoomsPage() {
  const { toastSuccess, toastApiError } = useToast();
  const [branchId, setBranchId] = useState("");
  const [rooms, setRooms] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [editing, setEditing] = useState(null);
  const [saving, setSaving] = useState(false);

  const { data: branchData } = useApi(API_ENDPOINTS.ORG.BRANCHES);
  const branches = branchData || [];

  useEffect(() => {
    if (!branchId && branches.length) setBranchId(String(branches[0].id));
  }, [branches, branchId]);

  const fetchRooms = useCallback(async () => {
    if (!branchId) { setRooms([]); setLoading(false); return; }
    setLoading(true);
    try {
      const { data: res } = await apiClient.get(API_ENDPOINTS.ORG.ROOMS, { params: { branch_id: branchId } });
      setRooms(res.data || []);
    } catch { setRooms([]); }
    finally { setLoading(false); }
  }, [branchId]);

  useEffect(() => { fetchRooms(); }, [fetchRooms]);

  async function handleCreate(form) {
    setSaving(true);
    try {
      await apiClient.post(API_ENDPOINTS.ORG.ROOMS, { ...form, branch: Number(form.branch) });
      toastSuccess(`Room "${form.name}" created.`);
      setModal(null); fetchRooms();
    } catch (err) { toastApiError(err, "Failed to create room."); }
    finally { setSaving(false); }
  }

  async function handleUpdate(form) {
    setSaving(true);
    try {
      await apiClient.patch(API_ENDPOINTS.ORG.ROOM(editing.id), { ...form, branch: Number(form.branch) });
      toastSuccess("Room updated.");
      setModal(null); setEditing(null); fetchRooms();
    } catch (err) { toastApiError(err, "Failed to update room."); }
    finally { setSaving(false); }
  }

  async function handleDeactivate(room) {
    if (!confirm(`Remove room "${room.name}"? Any doctor assignments for it will also be cleared.`)) return;
    try {
      await apiClient.delete(API_ENDPOINTS.ORG.ROOM(room.id));
      toastSuccess("Room removed.");
      fetchRooms();
    } catch (err) { toastApiError(err, "Failed to remove room."); }
  }

  // Group by floor for display
  const byFloor = rooms.reduce((acc, r) => {
    const key = r.floor || "Unspecified";
    (acc[key] = acc[key] || []).push(r);
    return acc;
  }, {});

  return (
    <AppShell>
      <PageShell title="Rooms & Floors">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20, gap: 12, flexWrap: "wrap" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <label style={{ fontSize: 13, fontWeight: 600 }}>Branch:</label>
            <select value={branchId} onChange={e => setBranchId(e.target.value)}
              style={{ padding: "7px 12px", borderRadius: 8, border: "1.5px solid var(--color-border)", fontSize: 13 }}>
              {branches.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
          </div>
          <button className="btn-primary" onClick={() => setModal("create")} disabled={!branchId}>
            + Add Room
          </button>
        </div>

        {loading ? (
          <div style={{ textAlign: "center", padding: 60, color: "var(--color-text-muted)" }}>Loading…</div>
        ) : rooms.length === 0 ? (
          <div className="card" style={{ textAlign: "center", padding: 60 }}>
            <DoorOpen size={40} style={{ color: "var(--color-text-muted)", marginBottom: 12 }} />
            <div style={{ fontWeight: 600, fontSize: 16, marginBottom: 8 }}>No rooms yet</div>
            <div style={{ color: "var(--color-text-muted)", marginBottom: 20 }}>
              Add rooms for this branch, then tag doctors to them from each doctor's profile.
            </div>
            <button className="btn-primary" onClick={() => setModal("create")} disabled={!branchId}>
              Add First Room
            </button>
          </div>
        ) : (
          Object.entries(byFloor)
            .sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true }))
            .map(([floor, floorRooms]) => (
              <div key={floor} style={{ marginBottom: 24 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text-muted)", letterSpacing: "0.05em", marginBottom: 10 }}>
                  FLOOR {floor.toUpperCase()}
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {floorRooms.map(room => (
                    <RoomCard key={room.id} room={room}
                      onEdit={(r) => { setEditing(r); setModal("edit"); }}
                      onDeactivate={handleDeactivate} />
                  ))}
                </div>
              </div>
            ))
        )}

        {modal === "create" && (
          <Modal title="Add Room" onClose={() => setModal(null)}>
            <RoomForm branches={branches} initial={{ ...EMPTY_ROOM, branch: branchId }}
              onSave={handleCreate} onCancel={() => setModal(null)} saving={saving} />
          </Modal>
        )}
        {modal === "edit" && editing && (
          <Modal title="Edit Room" onClose={() => { setModal(null); setEditing(null); }}>
            <RoomForm branches={branches} initial={{ ...editing, branch: String(editing.branch) }}
              onSave={handleUpdate} onCancel={() => { setModal(null); setEditing(null); }} saving={saving} />
          </Modal>
        )}
      </PageShell>
    </AppShell>
  );
}
