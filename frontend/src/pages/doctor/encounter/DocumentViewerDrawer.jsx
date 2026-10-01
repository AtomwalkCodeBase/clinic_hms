import { useState, useRef, useEffect } from "react";
import { useApi } from "../../../hooks/useApi";
import { DRAWER_DEFAULT_WIDTH, DRAWER_MIN_WIDTH } from "./constants";

export function DocumentViewerDrawer({ doc, onClose }) {
  const [width, setWidth] = useState(DRAWER_DEFAULT_WIDTH);
  const [dragging, setDragging] = useState(false);
  const [handleHover, setHandleHover] = useState(false);
  const draggingRef = useRef(false);

  const hasInlineData = !!doc?.file_data;
  const { data: fetched, isLoading: fetchLoading } = useApi(
    doc && !hasInlineData && doc.fetchUrl ? doc.fetchUrl : null,
    { skip: !doc || hasInlineData || !doc?.fetchUrl }
  );
  const full = hasInlineData ? doc : fetched;
  const isLoading = hasInlineData ? false : fetchLoading;

  useEffect(() => {
    function onMove(e) {
      if (!draggingRef.current) return;
      const next = window.innerWidth - e.clientX;
      setWidth(Math.min(Math.max(next, DRAWER_MIN_WIDTH), window.innerWidth - 200));
    }
    function onUp() {
      draggingRef.current = false;
      setDragging(false);
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  if (!doc) return null;

  const mime = full?.mime_type || "";
  const isPdf   = mime.includes("pdf");
  const isImage = mime.startsWith("image/");
  const handleActive = dragging || handleHover;

  return (
    <div style={{
      position: "fixed", top: 0, right: 0, bottom: 0, width,
      background: "var(--color-surface)", zIndex: 500,
      boxShadow: "-4px 0 24px rgba(0,0,0,0.18)",
      display: "flex", flexDirection: "column",
      userSelect: dragging ? "none" : undefined,
    }}>
      {/* Full-viewport overlay while dragging — keeps the mousemove/mouseup
          listeners reliable even when the cursor passes over the PDF <iframe>,
          which otherwise "eats" mouse events since it's a separate document. */}
      {dragging && (
        <div style={{ position: "fixed", inset: 0, zIndex: 600, cursor: "col-resize" }} />
      )}

      {/* Drag handle — an always-visible, Overleaf-style resize bar rather than
          an invisible hit zone, so it reads as adjustable at a glance. */}
      <div
        onMouseDown={() => { draggingRef.current = true; setDragging(true); }}
        onMouseEnter={() => setHandleHover(true)}
        onMouseLeave={() => setHandleHover(false)}
        onDoubleClick={() => setWidth(DRAWER_DEFAULT_WIDTH)}
        title="Drag to resize · double-click to reset"
        style={{
          position: "absolute", left: -7, top: 0, bottom: 0, width: 14,
          cursor: "col-resize", zIndex: 2,
          display: "flex", alignItems: "center", justifyContent: "center",
        }}
      >
        <div style={{
          width: handleActive ? 4 : 3, height: 56, borderRadius: 4,
          background: handleActive ? "var(--color-primary)" : "var(--color-border)",
          boxShadow: handleActive ? "0 0 0 3px color-mix(in srgb, var(--color-primary) 12%, transparent)" : "none",
          transition: "background 0.15s, width 0.1s, box-shadow 0.15s",
        }} />
      </div>

      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "12px 16px", borderBottom: "1px solid var(--color-border)", flexShrink: 0,
      }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: 14, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {doc.title}
          </div>
          <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
            {doc.doc_type?.replace("_", " ")}
            {doc.created_at && ` · ${new Date(doc.created_at).toLocaleDateString("en-IN")}`}
          </div>
        </div>
        <button
          onClick={onClose}
          style={{
            background: "none", border: "1px solid var(--color-border)", borderRadius: 8,
            width: 28, height: 28, cursor: "pointer", fontSize: 14, flexShrink: 0,
          }}
        >
          ✕
        </button>
      </div>

      {/* Scrollable viewer body — its own scroll container, independent of the page */}
      <div style={{ flex: 1, overflowY: "auto", overflowX: "hidden", background: "#525659" }}>
        {isLoading ? (
          <div style={{ padding: 40, textAlign: "center", color: "#fff", fontSize: 13 }}>Loading document…</div>
        ) : !full ? (
          <div style={{ padding: 40, textAlign: "center", color: "#fff", fontSize: 13 }}>Could not load this document.</div>
        ) : isPdf ? (
          <iframe
            title={doc.title}
            src={full.file_data}
            style={{ width: "100%", height: "100%", minHeight: "100%", border: "none", display: "block" }}
          />
        ) : isImage ? (
          <div style={{ padding: 16, display: "flex", justifyContent: "center" }}>
            <img src={full.file_data} alt={doc.title} style={{ maxWidth: "100%", height: "auto", borderRadius: 4 }} />
          </div>
        ) : (
          <div style={{ padding: 40, textAlign: "center", color: "#fff", fontSize: 13 }}>
            This file type can't be previewed.{" "}
            <a href={full.file_data} download={full.file_name || doc.title} style={{ color: "#93c5fd" }}>
              Download instead
            </a>
          </div>
        )}
      </div>
    </div>
  );
}
