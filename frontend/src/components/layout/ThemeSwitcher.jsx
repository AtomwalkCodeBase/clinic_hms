/**
 * components/layout/ThemeSwitcher.jsx
 * -------------------------------------
 * Palette-icon trigger in AppShell's topbar (present for every role, since
 * AppShell is the one shared shell) that opens a popover to browse and pick
 * a color theme. Flat grid of ~12 curated swatches (no family tabs — the
 * list is short enough now that a second navigation layer just adds
 * clicks), same outside-click-closes pattern as every other dropdown in
 * this app.
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

function CheckIcon({ size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 6L9 17l-5-5" />
    </svg>
  );
}

export function ThemeSwitcher() {
  const { theme, themes, setTheme } = useTheme();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    function handler(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

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
          width: 292, background: "var(--color-surface)", border: "1px solid var(--color-border)",
          borderRadius: 14, boxShadow: "var(--shadow-dropdown)", padding: 16,
        }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: "var(--color-text)", letterSpacing: "-0.01em" }}>Color theme</span>
            {theme.id !== DEFAULT_THEME_ID && (
              <button type="button" onClick={() => setTheme(DEFAULT_THEME_ID)}
                style={{ background: "none", border: "none", color: "var(--color-primary)", fontSize: 11.5, fontWeight: 600, cursor: "pointer", padding: 0 }}>
                Reset to default
              </button>
            )}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10 }}>
            {themes.map(t => {
              const active = t.id === theme.id;
              return (
                <button key={t.id} type="button"
                  onClick={() => setTheme(t.id)}
                  title={t.name}
                  style={{
                    display: "flex", flexDirection: "column", alignItems: "center", gap: 5,
                    padding: 0, border: "none", background: "none", cursor: "pointer",
                  }}>
                  <span style={{
                    position: "relative", width: "100%", aspectRatio: "1 / 1", borderRadius: 10,
                    background: t.primary, flexShrink: 0,
                    boxShadow: active
                      ? "0 0 0 2px var(--color-surface), 0 0 0 4px var(--color-primary)"
                      : "0 0 0 1px color-mix(in srgb, var(--color-text) 12%, transparent)",
                    display: "flex", alignItems: "center", justifyContent: "center",
                  }}>
                    {active && (
                      <span style={{
                        width: 20, height: 20, borderRadius: "50%",
                        background: "color-mix(in srgb, black 22%, transparent)",
                        color: "#fff", display: "flex", alignItems: "center", justifyContent: "center",
                      }}>
                        <CheckIcon size={12} />
                      </span>
                    )}
                  </span>
                  <span style={{
                    fontSize: 10.5, fontWeight: active ? 700 : 500, lineHeight: 1.2, textAlign: "center",
                    color: active ? "var(--color-primary)" : "var(--color-text-secondary)",
                  }}>
                    {t.name}
                  </span>
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
