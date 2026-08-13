/**
 * components/layout/ThemeSwitcher.jsx
 * -------------------------------------
 * Palette-icon trigger in AppShell's topbar (present for every role, since
 * AppShell is the one shared shell) that opens a popover to browse and pick
 * a color theme — grouped into families (Green, Teal, Navy, ...), each with
 * a few shades, same browsing pattern as every other search/select dropdown
 * in this app (ref + mousedown-outside-closes).
 */
import { useState, useRef, useEffect } from "react";
import { useTheme } from "../../context/ThemeContext";
import { DEFAULT_THEME_ID } from "../../config/themes.config";

function PaletteIcon({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2a10 10 0 100 20 2 2 0 001.4-3.4 1.6 1.6 0 011.1-2.7H16a4 4 0 004-4c0-5-4.5-9-8-9z" />
      <circle cx="7.5" cy="10.5" r="1.2" fill="currentColor" stroke="none" />
      <circle cx="11" cy="7" r="1.2" fill="currentColor" stroke="none" />
      <circle cx="15.5" cy="8.5" r="1.2" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function ThemeSwitcher() {
  const { theme, families, setTheme } = useTheme();
  const [open, setOpen] = useState(false);
  const [browsingFamily, setBrowsingFamily] = useState(theme.family);
  const ref = useRef(null);

  useEffect(() => {
    function handler(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  useEffect(() => {
    if (open) setBrowsingFamily(theme.family);
  }, [open, theme.family]);

  const activeFamily = families.find(f => f.key === browsingFamily) || families[0];

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        title="Change color theme"
        aria-label="Change color theme"
        style={{
          width: 34, height: 34, borderRadius: "50%", flexShrink: 0,
          border: "1px solid color-mix(in srgb, var(--color-hero-text) 25%, transparent)", background: "color-mix(in srgb, var(--color-hero-text) 8%, transparent)",
          color: "var(--color-hero-text)", display: "flex", alignItems: "center", justifyContent: "center",
          cursor: "pointer",
        }}
      >
        <PaletteIcon />
      </button>

      {open && (
        <div style={{
          position: "absolute", top: "calc(100% + 10px)", right: 0, zIndex: 200,
          width: 320, background: "var(--color-surface)", border: "1px solid var(--color-border)",
          borderRadius: 12, boxShadow: "var(--shadow-dropdown)", padding: 14,
        }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text)" }}>Color theme</span>
            {theme.id !== DEFAULT_THEME_ID && (
              <button type="button" onClick={() => setTheme(DEFAULT_THEME_ID)}
                style={{ background: "none", border: "none", color: "var(--color-primary)", fontSize: 11, fontWeight: 600, cursor: "pointer", padding: 0 }}>
                Reset to default
              </button>
            )}
          </div>

          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
            {families.map(f => (
              <button key={f.key} type="button"
                onClick={() => setBrowsingFamily(f.key)}
                style={{
                  fontSize: 11, padding: "5px 10px", borderRadius: 20, cursor: "pointer",
                  border: f.key === browsingFamily ? "1.5px solid var(--color-primary)" : "1px solid var(--color-border)",
                  background: f.key === browsingFamily ? "var(--color-primary-light)" : "transparent",
                  color: f.key === browsingFamily ? "var(--color-primary)" : "var(--color-text-secondary)",
                  fontWeight: f.key === browsingFamily ? 600 : 400,
                }}>
                {f.label}
              </button>
            ))}
          </div>

          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {activeFamily.themes.map(t => {
              const active = t.id === theme.id;
              return (
                <button key={t.id} type="button"
                  onClick={() => setTheme(t.id)}
                  title={t.name}
                  style={{
                    display: "flex", alignItems: "center", gap: 6, fontSize: 11.5,
                    padding: "5px 10px 5px 6px", borderRadius: 20, cursor: "pointer",
                    border: active ? "1.5px solid var(--color-primary)" : "1px solid var(--color-border)",
                    background: active ? "var(--color-primary-light)" : "var(--color-surface)",
                    color: "var(--color-text)",
                  }}>
                  <span style={{ width: 13, height: 13, borderRadius: "50%", background: t.primary, flexShrink: 0 }} />
                  {t.name}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export default ThemeSwitcher;
