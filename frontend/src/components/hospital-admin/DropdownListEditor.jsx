/** components/hospital-admin/DropdownListEditor.jsx */
import { useState, useEffect, useCallback, useRef } from "react";
import apiClient from "../../services/api.client";
import { useToast } from "../../hooks/useToast";
import { Lock, Pencil, Check, X } from "lucide-react";
import { KebabMenu } from "./KebabMenu";
import { editorInputStyle as inputStyle } from "../../styles/formStyles";


// Small pill toggle — same visual language as the bigger toggles elsewhere
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
    setTogglingId(item.option_list_id);
    try {
      await apiClient.patch(itemEndpoint(item.option_list_id), { is_active: !item.is_active });
      setItems(its => its.map(i => i.option_list_id === item.option_list_id ? { ...i, is_active: !i.is_active } : i));
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
      await apiClient.delete(itemEndpoint(item.option_list_id));
      toastSuccess("Removed.");
      load();
    } catch (err) {
      toastApiError(err, "Could not remove.");
    }
  }

  function startEdit(item) {
    setEditingId(item.option_list_id);
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
    const patchKey = identityField === "value" ? "label" : identityField;
    setEditSaving(true);
    try {
      await apiClient.patch(itemEndpoint(item.option_list_id), { [patchKey]: trimmed });
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
            const isEditing = editingId === item.option_list_id;
            const color = itemColor(index);
            return (
              <span key={item.option_list_id} style={{
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
                      <MiniToggle checked={item.is_active} disabled={togglingId === item.option_list_id}
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
