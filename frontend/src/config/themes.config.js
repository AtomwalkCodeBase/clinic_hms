/**
 * config/themes.config.js
 * ------------------------
 * Registry of selectable color themes. Each entry only defines the
 * hand-picked "source" colors (primary, sidebar/hero, text, border,
 * accent, ...) — everything else (light tints, hero gradient stop, muted
 * variants, hero-text contrast, etc.) is derived at apply-time in
 * utils/theme.js so we're not hand-authoring 20+ full token sets.
 *
 * Curated down to ~12 clearly distinct hues (from an earlier 32-theme list
 * that had up to 8 near-identical shades within a single family) so the
 * picker reads as a deliberate, professional set of choices rather than a
 * wall of barely-different swatches. Kept flat (no family grouping) since
 * there's no longer enough depth per hue to justify family tabs in the UI.
 *
 * "forest" is the original theme, already fully defined by the hand-tuned
 * values in styles/variables.css — ThemeProvider still special-cases it
 * (see ORIGINAL_STYLESHEET_THEME_ID in ThemeContext.jsx) so picking it
 * gets the exact original stylesheet, pixel for pixel, not a re-derived
 * approximation. It is no longer the app *default*, though — that's
 * DEFAULT_THEME_ID below, which a first-time user (or "Reset to default")
 * lands on.
 */

function theme(id, name, primary, sidebar, sidebarText, bg, border, text, muted, accent, serif) {
  return { id, name, primary, sidebar, sidebarText, bg, border, text, muted, accent, serif };
}

export const THEMES = [
  theme("forest", "Forest", "#1B5E43", "#0C2A1F", "#F4F1E8", "#FAF7F2", "#ECE7DE", "#1A1F1B", "#8A9088", "#C9A24B", true),
  theme("emerald", "Emerald", "#0F9D6E", "#073B2A", "#E7FBF2", "#F2FBF7", "#DCEFE6", "#1C1F1C", "#87897E", "#E0A72E", false),
  theme("clinical-teal", "Clinical teal", "#0E6E5A", "#0B4238", "#EAF5F1", "#F5FAF9", "#E1EAE7", "#152420", "#77918B", "#D9A441", false),
  theme("emerald-glass", "Emerald Glass", "#01D4C7", "#00665F", "#E7F9F6", "#F5FCFB", "#E1F3F0", "#152420", "#77918B", "#D9603B", false),
  theme("midnight", "Midnight", "#1E2761", "#141B42", "#E9ECF9", "#F4F6FB", "#E2E5F0", "#171B33", "#7C82A3", "#D9A441", false),
  theme("steel-blue", "Steel blue", "#2C5D7C", "#1C3C50", "#E7F0F5", "#F4F8FA", "#DEEAF0", "#171B33", "#7C82A3", "#D97757", false),
  theme("terracotta", "Terracotta", "#B85042", "#7A362B", "#F7EBE6", "#FBF8F3", "#EFE4D8", "#2B211C", "#9C8A7D", "#7C9885", true),
  theme("sand-sage", "Sand & sage", "#C98B5E", "#8C5A38", "#FBF3EA", "#FCF9F4", "#F2E7D9", "#2B211C", "#9C8A7D", "#6E8F73", false),
  theme("charcoal", "Charcoal", "#33393D", "#22262A", "#EDEDEC", "#F7F7F6", "#E4E4E2", "#1F2224", "#8B8E90", "#D9603B", false),
  theme("graphite-blue", "Graphite blue", "#3A4550", "#262E36", "#EAEDEF", "#F6F8F9", "#E2E6E9", "#1F2224", "#8B8E90", "#3B9E8C", false),
  theme("berry", "Berry", "#6D2E46", "#431C2B", "#F7E9EE", "#FCF6F8", "#F1DFE5", "#251820", "#96828C", "#C99A3A", true),
  theme("plum", "Plum", "#4A2F5C", "#2E1D3A", "#EFE8F3", "#F8F5FA", "#E7DDEE", "#251820", "#96828C", "#3B9E8C", true),
];

export const DEFAULT_THEME_ID = "emerald";

export function getThemeById(id) {
  return THEMES.find(t => t.id === id) || THEMES.find(t => t.id === DEFAULT_THEME_ID);
}
