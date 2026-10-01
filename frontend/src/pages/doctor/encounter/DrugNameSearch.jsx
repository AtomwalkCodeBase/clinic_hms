import { useApi } from "../../../hooks/useApi";
import API_ENDPOINTS from "../../../config/api.config";
import { useState, useRef, useEffect } from "react";

// Searchable dropdown over the pharmacist-maintained drug catalog (see
// pages/pharmacist/CatalogPage.jsx) — same load-once-then-client-filter
// pattern as LabOrderSection's test picker just above. Selecting an entry
// fills in the name and its catalogued dosage; free text is still allowed
// for a drug the pharmacist hasn't added yet (drug stays null in that case).
export function DrugNameSearch({ value, onChange, onSelectCatalog, disabled }) {
  const { data: catalogData } = useApi(API_ENDPOINTS.PRESCRIPTIONS.DRUGS);
  const catalog = catalogData || [];
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    function handler(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const q = value.trim().toLowerCase();
  const results = q.length === 0 ? catalog.slice(0, 15) : catalog
    .filter(c => c.name.toLowerCase().includes(q) || (c.generic_name || "").toLowerCase().includes(q))
    .slice(0, 15);

  function select(c) {
    onSelectCatalog(c);
    setOpen(false);
  }

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <input
        className="form-input"
        value={value}
        onChange={e => { onChange(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        placeholder="e.g. Amoxicillin"
        required
        disabled={disabled}
        autoComplete="off"
      />
      {open && (
        <div style={{
          position: "absolute", zIndex: 100, top: "calc(100% + 4px)", left: 0, right: 0,
          background: "#fff", border: "1px solid var(--color-border)", borderRadius: 8,
          boxShadow: "0 4px 24px rgba(0,0,0,0.12)", maxHeight: 220, overflowY: "auto", minWidth: 260,
        }}>
          {catalog.length === 0 ? (
            <div style={{ padding: "10px 14px", fontSize: 12, color: "var(--color-text-muted)" }}>
              No drugs in the catalog yet — ask the pharmacist to add drugs under "Drug Catalog", or type a name to prescribe free-text.
            </div>
          ) : results.length === 0 ? (
            <div style={{ padding: "10px 14px", fontSize: 12, color: "var(--color-text-muted)" }}>
              No matching drugs — you can still prescribe this by name.
            </div>
          ) : results.map(c => (
            <div key={c.id}
              onMouseDown={() => select(c)}
              style={{ padding: "9px 14px", cursor: "pointer", borderBottom: "1px solid var(--color-border)", display: "flex", justifyContent: "space-between", gap: 8 }}
              className="hover-row"
            >
              <span style={{ fontSize: 13 }}>
                {c.name}
                {c.generic_name && <span style={{ color: "var(--color-text-muted)" }}> ({c.generic_name})</span>}
              </span>
              <span style={{ fontSize: 11, color: "var(--color-text-muted)", whiteSpace: "nowrap", textTransform: "capitalize" }}>
                {c.strength && `${c.strength} · `}{c.form}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
