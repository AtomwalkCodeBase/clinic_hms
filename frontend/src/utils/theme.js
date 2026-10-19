/** utils/theme.js */

function hexToRgb(hex) {
  const h = hex.replace("#", "");
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

function rgbToHex([r, g, b]) {
  return "#" + [r, g, b]
    .map(v => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, "0"))
    .join("");
}

/** t=0 -> hexA, t=1 -> hexB */
function mix(hexA, hexB, t) {
  const a = hexToRgb(hexA);
  const b = hexToRgb(hexB);
  return rgbToHex(a.map((v, i) => v + (b[i] - v) * t));
}

const lighten = (hex, t) => mix(hex, "#FFFFFF", t);
const darken = (hex, t) => mix(hex, "#000000", t);

/** Perceived brightness (YIQ) of a hex color, 0-255. Used to decide whether */
function yiq(hex) {
  const [r, g, b] = hexToRgb(hex);
  return (r * 299 + g * 587 + b * 114) / 1000;
}

/** The full CSS-variable name -> value map for a theme, ready to apply. */
export function deriveThemeVars(t) {
  // Hero (sidebar/topbar/hero-card) now uses the primary color directly,
  const heroIsLight = yiq(t.primary) >= 150;
  const heroText = heroIsLight ? t.text : t.sidebarText;

  return {
    "--color-primary": t.primary,
    "--color-primary-light": lighten(t.primary, 0.88),
    "--color-primary-dark": t.sidebar,
    "--color-accent": t.accent,
    "--color-accent-light": lighten(t.accent, 0.85),
    "--color-hero": t.primary,
    "--color-hero-2": darken(t.primary, 0.15),
    "--color-hero-text": heroText,
    "--color-hero-muted": mix(heroText, t.primary, 0.5),
    "--color-bg": t.bg,
    "--color-surface": "#FFFFFF",
    "--color-border": t.border,
    "--color-table-header": mix(t.bg, t.border, 0.4),
    "--color-text": t.text,
    "--color-text-secondary": mix(t.text, t.muted, 0.3),
    "--color-text-muted": t.muted,
    "--color-text-disabled": lighten(t.muted, 0.35),
    "--font-display": t.serif
      ? "'Fraunces', 'Playfair Display', Georgia, serif"
      : "'Inter', 'Segoe UI', Arial, sans-serif",
  };
}
