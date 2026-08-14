/**
 * utils/theme.js
 * ---------------
 * Turns a small hand-picked theme entry (config/themes.config.js) into the
 * full set of CSS custom properties styles/variables.css expects, by
 * mixing/lightening the source colors rather than hand-authoring every
 * derived shade for every theme.
 *
 * Deliberately left untouched by theming: --color-success/warning/error/info
 * (and their *-light pairs) stay the fixed semantic colors from
 * variables.css — status colors shouldn't shift with the brand palette, or
 * "success" and "warning" stop being recognizable at a glance. Same for
 * --font-family (body text), spacing, radius, and shadow tokens.
 */

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

/**
 * Perceived brightness (YIQ) of a hex color, 0-255. Used to decide whether
 * hero text should be light or dark when the hero background is the theme's
 * primary color itself (which ranges from near-black to near-white across
 * the palette, unlike the old hand-picked-always-dark sidebar color).
 */
function yiq(hex) {
  const [r, g, b] = hexToRgb(hex);
  return (r * 299 + g * 587 + b * 114) / 1000;
}

/** The full CSS-variable name -> value map for a theme, ready to apply. */
export function deriveThemeVars(t) {
  // Hero (sidebar/topbar/hero-card) now uses the primary color directly,
  // not a separately hand-picked darker shade — so light chips (Aqua,
  // Teal Mist, Spring, ...) need dark text, and dark chips need light text.
  const heroIsLight = yiq(t.primary) >= 145;
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
