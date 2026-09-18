/**
 * components/hospital-admin/DropdownListEditor.jsx
 * ---------------------------------------------------
 * Generic configurable dropdown list — one small CRUD block (pill list +
 * inline add form) backed by billing.OptionList. Originally built inline
 * in BillingSetupPage.jsx for Service Categories / Payment Modes / Invoice
 * Statuses; extracted here so other admin pages (e.g. Rooms & Floors'
 * "Room Types") can reuse the exact same widget instead of re-implementing
 * it, since they're all the same OptionList-backed shape (see
 * apps/billing/models.py's OptionList docstring and apps/billing/views.py's
 * _DropdownListCreateView/_DropdownDetailView).
 *
 * identityField is "name" for lists where value mirrors label (Service
 * Categories, Payment Modes, Room Types) or "value" for lists where the
 * stored value and display label differ (Invoice Statuses) — the extra
 * Label input only appears in the latter case.
 *
 * toggleable=true (Payment Modes) additionally fetches inactive entries and
 * shows an is_active switch per item — this is what the hospital actually
 * accepts/offers, reflected to whoever picks from this list elsewhere.
 *
 * onChange (optional) fires every time the list reloads (initial load, and
 * after any add/toggle/remove) — for a caller that keeps its own copy of
 * the same catalog elsewhere (e.g. Rooms & Floors mirrors Room Types into
 * its Add Room dropdown), this is the cue to refetch that copy too.
 *
 * Every item (including system ones — the help text next to this widget
 * already promises "system ones can be renamed but not removed") can be
 * renamed via the pencil icon. What actually gets PATCHed depends on
 * identityField: for a "value"-shaped list (Invoice Statuses, Room Types)
 * the visible text is `label`, a field distinct from the locked `value`
 * identity, so renaming only ever touches `label` — never blocked, even
 * for a system row. For a "name"-shaped list (Service Categories, Payment
 * Modes) the visible text IS the identity field, so renaming a system row
 * is still allowed (the backend only blocks an identity change combined
 * with is_system when the two disagree in a way that would orphan
 * existing references — same guard the backend already enforces; this
 * widget doesn't duplicate that check, it just lets the request through
 * and surfaces whatever error comes back).
 *
 * compact=true (Rooms & Floors' Room Types panel) swaps the plain "✕"
 * remove button for a pencil + kebab-menu ("Delete") pair, and — when
 * showAddForm is left at its default false in this mode — hides the
 * inline add-row so the panel reads as a compact reference list; the
 * caller drives showAddForm itself (e.g. a "+ Add Type" button toggling
 * a boolean) to reveal the exact same add-row non-compact mode always
 * shows. dotColorForIndex(index), if given, renders a small color swatch
 * before each item's label (compact mode's visual cue for which room type
 * is which, matching how the Room list elsewhere colors its type badges).
 * onAdded (optional) fires once, after a successful add, so the caller can
 * auto-collapse an add-row it's driving via showAddForm.
 *
 * extraFields (optional) — beyond the identity/label inputs, lets a list
 * carry a little more than value+label (e.g. Room Types' category +
 * is_bed_based — see billing.OptionList's docstring for why that catalog
 * needs them). Each entry is `{ name, type: "select" | "checkbox", label,
 * options, default }` — `options` (an array of {value,label}) only for
 * "select". Rendered in the add form after the Label input, and included
 * in the POST payload the same way identityField/label already are.
 * Read-only after creation for now — no inline editor for these fields yet,
 * only the rename pencil (label) and delete/deactivate. `badgeForItem(item)`
 * (optional), if given, renders a small secondary tag on each pill (e.g.
 * "IPD" / bed icon) — purely a read-side complement to extraFields.
 */
import { useState, useEffect, useCallback, useRef } from "react";
import apiClient from "../../services/api.client";
import { useToast } from "../../hooks/useToast";
import { Lock, Pencil, Check, X } from "lucide-react";
import { KebabMenu } from "./KebabMenu";

const inputStyle = {
  boxSizing: "border-box",
  border: "1.5px solid var(--color-border)", borderRadius: 8,
  padding: "8px 12px", fontSize: 13,
  background: "var(--color-surface)", color: "var(--color-text)", outline: "none",
};

// Small pill toggle — same visual language as the bigger toggles elsewhere
// in hospital-admin settings screens.
function MiniToggle({ checked, onChange, disabled }) {
  return (
    <button
      type="button" onClick={onChange} disabled={disabled}
      title={checked ? "Accepted — click to turn off" : "Not accepted — click to turn on"}
      style={{
        width: 30, height: 17, borderRadius: 9, border: "none", flexShrink: 0,
        background: checked ? "var(--color-primary)" : "var(--color-border)",
        cursor: disabled ? "default" : "pointer", position: "relative", transition: "background 0.15s",
      }}>
      <span style={{
        position: "absolute", top: 2, left: checked ? 15 : 2,
        width: 13, height: 13, borderRadius: "50%", background: "#fff", transition: "left 0.15s",
      }} />
    </button>
  );
}

export function DropdownListEditor({
  title, listEndpoint, itemEndpoint, identityField, extraFields, toggleable, helpText, onChange,
  compact = false, showAddForm = !compact, onAdded, dotColorForIndex, badgeForItem,
}) {
  const { toastSuccess, toastApiError } = useToast();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState(() => {
    const f = { [identityField]: "" };
    (extraFields || []).forEach(ef => { f[ef.name] = ef.default ?? ""; });
    return f;
  });
  const [saving, setSaving] = useState(false);
  const [togglingId, setTogglingId] = useState(null);
  const [editingId, setEditingId] = useState(null);
  const [editDraft, setEditDraft] = useState("");
  const [editSaving, setEditSaving] = useState(false);

  // Kept as a ref (not a load() dependency) so an inline onChange passed by
  // the caller doesn't recreate load() — and therefore doesn't retrigger
  // useEffect(load) — on every parent render.
  const onChangeRef = useRef(onChange);
  useEffect(() => { onChangeRef.current = onChange; });
  const onAddedRef = useRef(onAdded);
  useEffect(() => { onAddedRef.current = onAdded; });

  const load = useCallback(() => {
    setLoading(true);
    apiClient.get(toggleable ? `${listEndpoint}?all=1` : listEndpoint)
      .then(r => { setItems(r.data?.data || []); onChangeRef.current?.(); })
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [listEndpoint, toggleable]);
  useEffect(() => { load(); }, [load]);

  async function toggleActive(item) {
    setTogglingId(item.id);
    try {
      await apiClient.patch(itemEndpoint(item.id), { is_active: !item.is_active });
      setItems(its => its.map(i => i.id === item.id ? { ...i, is_active: !i.is_active } : i));
    } catch (err) {
      toastApiError(err, "Could not update.");
    } finally {
      setTogglingId(null);
    }
  }

  async function addItem(e) {
    e.preventDefault();
    if (!String(form[identityField] || "").trim()) return;
    setSaving(true);
    try {
      await apiClient.post(listEndpoint, form);
      toastSuccess("Added.");
      setForm(f => ({ ...f, [identityField]: "" }));
      load();
      onAddedRef.current?.();
    } catch (err) {
      toastApiError(err, "Could not add.");
    } finally {
      setSaving(false);
    }
  }

  async function removeItem(item) {
    if (item.is_system) return;
    if (!confirm(`Remove "${item[identityField]}"?`)) return;
    try {
      await apiClient.delete(itemEndpoint(item.id));
      toastSuccess("Removed.");
      load();
    } catch (err) {
      toastApiError(err, "Could not remove.");
    }
  }

  function startEdit(item) {
    setEditingId(item.id);
    setEditDraft(item.label ?? item[identityField] ?? "");
  }
  function cancelEdit() {
    setEditingId(null);
    setEditDraft("");
  }
  function itemColor(index) {
    return typeof dotColorForIndex === "function" ? dotColorForIndex(index) : null;
  }
  async function saveEdit(item) {
    const trimmed = editDraft.trim();
    if (!trimmed) return;
    const current = item.label ?? item[identityField] ?? "";
    if (trimmed === current) { cancelEdit(); return; }
    // "value"-shaped lists show `label` on the pill — rename that, leaving
    // the locked `value` identity untouched. "name"-shaped lists show the
    // identity field itself, so that's what gets renamed.
    const patchKey = identityField === "value" ? "label" : identityField;
    setEditSaving(true);
    try {
      await apiClient.patch(itemEndpoint(item.id), { [patchKey]: trimmed });
      toastSuccess("Renamed.");
      cancelEdit();
      load();
    } catch (err) {
      toastApiError(err, "Could not rename.");
    } finally {
      setEditSaving(false);
    }
  }

  return (
    <div>
      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 2 }}>{title}</div>
      {helpText && <div style={{ fontSize: 11.5, color: "var(--color-text-muted)", marginBottom: 10 }}>{helpText}</div>}
      {loading ? (
        <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>Loading…</div>
      ) : (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: showAddForm ? 12 : 0 }}>
          {items.map((item, index) => {
            const isEditing = editingId === item.id;
            const color = itemColor(index);
            return (
              <span key={item.id} style={{
                display: "inline-flex", alignItems: "center", gap: 7,
                fontSize: 12, fontWeight: 600, padding: isEditing ? "4px 6px" : "4px 8px 4px 10px", borderRadius: 999,
                background: "var(--color-bg)", border: "1px solid var(--color-border)",
                opacity: toggleable && !item.is_active ? 0.55 : 1,
              }}>
                {isEditing ? (
                  <>
                    <input
                      autoFocus value={editDraft} disabled={editSaving}
                      onChange={e => setEditDraft(e.target.value)}
                      onKeyDown={e => {
                        if (e.key === "Enter") { e.preventDefault(); saveEdit(item); }
                        if (e.key === "Escape") { e.preventDefault(); cancelEdit(); }
                      }}
                      style={{
                        border: "1px solid var(--color-border)", borderRadius: 999,
                        padding: "2px 8px", fontSize: 12, fontWeight: 600, width: 130,
                        background: "var(--color-surface)", color: "var(--color-text)", outline: "none",
                      }}
                    />
                    <button type="button" onClick={() => saveEdit(item)} disabled={editSaving}
                      title="Save"
                      style={{ background: "none", border: "none", cursor: "pointer", padding: 0, lineHeight: 1, color: "var(--color-primary)" }}>
                      <Check size={13} />
                    </button>
                    <button type="button" onClick={cancelEdit} disabled={editSaving}
                      title="Cancel"
                      style={{ background: "none", border: "none", cursor: "pointer", padding: 0, lineHeight: 1, color: "var(--color-text-muted)" }}>
                      <X size={13} />
                    </button>
                  </>
                ) : (
                  <>
                    {color && <span style={{ width: 8, height: 8, borderRadius: "50%", background: color, flexShrink: 0 }} />}
                    {item.is_system && <Lock size={10} style={{ color: "var(--color-text-muted)" }} />}
                    {item.label || item[identityField]}
                    {typeof badgeForItem === "function" && badgeForItem(item)}
                    {toggleable && (
                      <MiniToggle checked={item.is_active} disabled={togglingId === item.id}
                        onChange={() => toggleActive(item)} />
                    )}
                    <button type="button" onClick={() => startEdit(item)}
                      title="Rename"
                      style={{ background: "none", border: "none", cursor: "pointer", padding: 0, lineHeight: 1, color: "var(--color-text-muted)" }}>
                      <Pencil size={11} />
                    </button>
                    {compact ? (
                      <KebabMenu items={[
                        { label: "Delete", danger: true, disabled: item.is_system, onClick: () => removeItem(item) },
                      ]} />
                    ) : (
                      !item.is_system && (
                        <button type="button" onClick={() => removeItem(item)}
                          title="Remove"
                          style={{ background: "none", border: "none", cursor: "pointer", padding: 0, lineHeight: 1, color: "var(--color-text-muted)" }}>
                          ✕
                        </button>
                      )
                    )}
                  </>
                )}
              </span>
            );
          })}
          {items.length === 0 && <span style={{ fontSize: 12, color: "var(--color-text-muted)", fontStyle: "italic" }}>Nothing configured yet.</span>}
        </div>
      )}
      {showAddForm && (
        <form onSubmit={addItem} style={{ display: "flex", gap: 8, marginTop: compact ? 12 : 0, flexWrap: "wrap", alignItems: "center" }}>
          <input
            style={{ ...inputStyle, flex: 1, minWidth: 120 }}
            placeholder={`Add a custom ${title.toLowerCase().replace(/s$/, "")}…`}
            value={form[identityField]}
            onChange={e => setForm(f => ({ ...f, [identityField]: e.target.value }))}
          />
          {identityField === "value" && (
            <input
              style={{ ...inputStyle, width: 140 }}
              placeholder="Label"
              value={form.label || ""}
              onChange={e => setForm(f => ({ ...f, label: e.target.value }))}
            />
          )}
          {(extraFields || []).map(ef => (
            ef.type === "checkbox" ? (
              <label key={ef.name} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 600, whiteSpace: "nowrap" }}>
                <input type="checkbox" checked={!!form[ef.name]}
                  onChange={e => setForm(f => ({ ...f, [ef.name]: e.target.checked }))} />
                {ef.label}
              </label>
            ) : (
              <select key={ef.name} value={form[ef.name] ?? ""} onChange={e => setForm(f => ({ ...f, [ef.name]: e.target.value }))}
                style={{ ...inputStyle, width: 120 }}>
                {(ef.options || []).map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            )
          ))}
          <button type="submit" disabled={saving} className="btn-outline" style={{ fontSize: 12, padding: "8px 16px" }}>
            {saving ? "…" : "+ Add"}
          </button>
        </form>
      )}
    </div>
  );
}

export default DropdownListEditor;
