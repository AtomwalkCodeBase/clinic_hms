/**
 * One report in the list: file icon, name, date and size, what it is, how sure we are, and a menu.
 * What a problem report needs (try again, keep a duplicate…) is in the menu and in the details panel.
 */
import { useEffect, useRef, useState } from "react";
import { FileText, Image as ImageIcon, MoreVertical } from "lucide-react";
import { NEEDS_ATTENTION, chipsFor, fileKind, fmtDate, formatSize, stateOf, statusLine } from "../../../utils/reports";
import { FILE_TILE, TONE, chip, iconBtn } from "./reportStyles";

function Menu({ items }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  return (
    <div ref={ref} style={{ position: "relative" }} onClick={e => e.stopPropagation()}>
      <button aria-label="More actions" style={iconBtn} onClick={() => setOpen(o => !o)}><MoreVertical size={18} /></button>
      {open && (
        <div role="menu" className="card" style={{ position: "absolute", right: 0, top: "100%", zIndex: 20, minWidth: 190, padding: 6, boxShadow: "0 8px 24px rgba(0,0,0,.14)" }}>
          {items.map(it => (
            <button key={it.label} role="menuitem" onClick={() => { setOpen(false); it.onClick(); }}
              style={{ display: "block", width: "100%", textAlign: "left", background: "none", border: "none", padding: "8px 10px", borderRadius: 6,
                       fontSize: 13, cursor: "pointer", color: it.danger ? "var(--color-danger)" : "var(--color-text)" }}>
              {it.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ReportRow({ doc, active, selectMode, selected, onClick, onOpen, onAct, onDelete, priv, onLock }) {
  const state = stateOf(doc);
  const kind = fileKind(doc);
  const chips = chipsFor(doc);
  const line = statusLine(doc);
  const Icon = kind === "image" ? ImageIcon : FileText;
  const hospital = !!doc.source_tenant_id || doc.uploaded_by === "staff";

  const items = [
    { label: "Open", onClick: onOpen },
    ...(state === "failed" ? [{ label: "Try again", onClick: () => onAct(doc, { action: "retry" }, "Trying again…") }] : []),
    ...(state === "duplicate" ? [{ label: "Keep anyway", onClick: () => onAct(doc, { action: "keep" }, "Keeping it — reading it now.") }] : []),
    ...(!hospital && state !== "duplicate" && state !== "processing" ? [{ label: "Change type", onClick: onOpen }] : []),
    ...(priv && onLock && state !== "processing" ? [{ label: priv.private ? "Share with doctors" : "Hide from doctors", onClick: () => onLock(doc) }] : []),
    { label: "Delete", danger: true, onClick: () => onDelete([doc]) },
  ];

  return (
    <div className="card" onClick={onClick}
      style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 14px", marginBottom: 8, cursor: "pointer",
               borderColor: active || selected ? "var(--color-primary)" : undefined,
               background: active ? "var(--color-primary-light, #eef7f3)" : undefined }}>
      {selectMode && <input type="checkbox" checked={selected} readOnly aria-label={`Select ${doc.title}`} />}
      <span style={{ width: 40, height: 40, borderRadius: 10, flexShrink: 0, display: "inline-flex", alignItems: "center", justifyContent: "center", ...FILE_TILE[kind] }}>
        <Icon size={19} />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600, fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{doc.title}</div>
        <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
          {fmtDate(doc.created_at)}{doc.size ? ` • ${formatSize(doc.size)}` : ""}
        </div>
        {NEEDS_ATTENTION.has(state) && state !== "unclassified" && (
          <div style={{ fontSize: 12, color: TONE[line.tone], marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{line.text}</div>
        )}
      </div>
      <span style={chip(chips.type.tone)}>{chips.type.text}</span>
      {chips.extra && <span style={chip(chips.extra.tone)}>{chips.extra.text}</span>}
      {!selectMode && <Menu items={items} />}
    </div>
  );
}
