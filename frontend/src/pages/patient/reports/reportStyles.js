/** Inline styles shared by the My Reports screens. */
export const backdrop = {
  position: "fixed", inset: 0, background: "rgba(15,23,42,.45)", zIndex: 1000,
  display: "flex", alignItems: "center", justifyContent: "center", padding: 16,
};
export const sheet = { width: "min(560px, 96vw)", maxHeight: "88vh", overflowY: "auto", padding: 22 };
export const h3 = { fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 17, margin: 0 };
export const sub = { fontSize: 12.5, color: "var(--color-text-muted)", margin: "6px 0 0" };
export const iconBtn = { background: "none", border: "none", cursor: "pointer", color: "var(--color-text-muted)", padding: 4, display: "inline-flex" };
export const inputStyle = {
  padding: "7px 10px", border: "1px solid var(--color-border)", borderRadius: 8, fontSize: 13, background: "var(--color-surface, #fff)",
};

// Chip colours: what it is ("type"), who decided it, and the problem states.
const CHIP = {
  type:    { background: "#f5ead6", color: "#8a5a12" },
  neutral: { background: "var(--color-bg)", color: "var(--color-text-secondary)" },
  warn:    { background: "#fbf0dc", color: "#92400e" },
  bad:     { background: "#fdecec", color: "#b91c1c" },
};
export const chip = (tone) => ({
  display: "inline-flex", alignItems: "center", fontSize: 11.5, fontWeight: 600, padding: "3px 10px",
  borderRadius: 999, whiteSpace: "nowrap", ...(CHIP[tone] || CHIP.neutral),
});

// A file's icon tile, coloured by what kind of file it is.
export const FILE_TILE = {
  pdf:   { background: "#fdeaea", color: "#d93025" },
  image: { background: "#e5f5ea", color: "#1e8e3e" },
  other: { background: "#e8f0fe", color: "#1a73e8" },
};
export const TONE = { muted: "var(--color-text-muted)", warn: "var(--color-warning, #b45309)", error: "var(--color-error)" };
