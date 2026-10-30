import { useEffect, useState } from "react";
import { GripVertical } from "lucide-react";

// Doctors drag a section by its grip to where they want it. Sections that share a parent swap places (CSS order); the layout is remembered per browser.
const ORDER_KEY = "encounterSectionOrder";
const ORDER_EVENT = "encounter-section-order";
const readOrder = () => { try { return JSON.parse(localStorage.getItem(ORDER_KEY)) || {}; } catch { return {}; } };
const saveOrder = (o) => { try { localStorage.setItem(ORDER_KEY, JSON.stringify(o)); } catch { /* order just isn't remembered */ } window.dispatchEvent(new Event(ORDER_EVENT)); };

function useSectionOrder(id) {
  const [order, setOrder] = useState(readOrder);
  useEffect(() => {
    const sync = () => setOrder(readOrder());
    window.addEventListener(ORDER_EVENT, sync);
    return () => window.removeEventListener(ORDER_EVENT, sync);
  }, []);
  return id ? order[id] : undefined;
}

let draggedId = null;
function moveBefore(fromId, toEl) {
  const parent = toEl.parentElement;
  const siblings = [...parent.children].filter(c => c.dataset.sectionId);
  const from = siblings.find(c => c.dataset.sectionId === fromId);
  if (!from || from === toEl) return;
  const ids = siblings.sort((a, b) => (Number(a.style.order) || 0) - (Number(b.style.order) || 0)).map(c => c.dataset.sectionId).filter(x => x !== fromId);
  ids.splice(ids.indexOf(toEl.dataset.sectionId), 0, fromId);
  const next = readOrder();
  ids.forEach((x, i) => { next[x] = i; });
  saveOrder(next);
}

// ─── Tiny helpers ─────────────────────────────────────────────────────────────
export function SectionCard({ id, title, badge, extra, children }) {
  const order = useSectionOrder(id);
  const dragProps = id ? {
    "data-section-id": id,
    onDragOver: e => { if (draggedId && draggedId !== id) e.preventDefault(); },
    onDrop: e => { e.preventDefault(); if (draggedId) moveBefore(draggedId, e.currentTarget); draggedId = null; },
  } : {};
  return (
    <div className="card" style={{ padding: 0, overflow: "hidden", ...(order !== undefined ? { order } : {}) }} {...dragProps}>
      <div style={{
        padding: "10px 18px",
        borderBottom: "1px solid var(--color-border)",
        background: "#FAFAFA",
        fontWeight: 700, fontSize: 13,
        display: "flex", alignItems: "center", gap: 8,
      }}>
        {id && (
          <span draggable title="Drag to move this section" aria-label={`Move ${typeof title === "string" ? title : "section"}`}
            onDragStart={e => { draggedId = id; e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", id); e.dataTransfer.setDragImage(e.currentTarget.closest(".card"), 20, 20); }}
            onDragEnd={() => { draggedId = null; }}
            style={{ cursor: "grab", display: "inline-flex", color: "var(--color-text-muted)" }}><GripVertical size={16} /></span>
        )}
        {title}
        {badge !== undefined && (
          <span style={{
            padding: "2px 8px", borderRadius: 12, fontSize: 11, fontWeight: 700,
            background: badge > 0 ? "var(--color-primary)" : "var(--color-border)",
            color: badge > 0 ? "#fff" : "var(--color-text-muted)",
          }}>{badge}</span>
        )}
        {extra && <span style={{ marginLeft: "auto" }}>{extra}</span>}
      </div>
      <div style={{ padding: "16px 18px" }}>{children}</div>
    </div>
  );
}
