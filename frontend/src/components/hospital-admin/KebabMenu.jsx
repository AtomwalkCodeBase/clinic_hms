/**
 * components/hospital-admin/KebabMenu.jsx
 * -----------------------------------------
 * Small "⋮" icon button that opens a floating action menu — shared by
 * RoomsPage's Rooms/Beds tables and DropdownListEditor's compact variant
 * (Room Types) so all three get the same look/behavior instead of three
 * one-off implementations.
 */
import { useState, useRef, useEffect } from "react";
import { MoreVertical } from "lucide-react";

export function KebabMenu({ items }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    function onDocClick(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  return (
    <div ref={ref} style={{ position: "relative", display: "inline-block" }}>
      <button
        type="button" onClick={() => setOpen(o => !o)}
        style={{ background: "none", border: "none", cursor: "pointer", padding: 4, display: "flex", color: "var(--color-text-muted)" }}
      >
        <MoreVertical size={15} />
      </button>
      {open && (
        <div style={{
          position: "absolute", right: 0, top: "calc(100% + 4px)", zIndex: 50,
          background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: 8,
          boxShadow: "0 8px 24px rgba(0,0,0,0.14)", minWidth: 150, overflow: "hidden",
        }}>
          {items.map((it, i) => (
            <button
              key={i} type="button" disabled={it.disabled}
              onClick={() => { setOpen(false); it.onClick(); }}
              style={{
                display: "block", width: "100%", textAlign: "left", padding: "8px 12px",
                background: "none", border: "none", cursor: it.disabled ? "default" : "pointer",
                fontSize: 12.5, fontWeight: 600,
                color: it.disabled ? "var(--color-text-muted)" : (it.danger ? "var(--color-error)" : "var(--color-text)"),
                opacity: it.disabled ? 0.5 : 1,
              }}
            >
              {it.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default KebabMenu;
