/**
 * config/themes.config.js
 * ------------------------
 * Registry of selectable color themes, grouped by family. Each entry only
 * defines the hand-picked "source" colors (primary, sidebar/hero, text,
 * border, accent, ...) — everything else (light tints, hero gradient
 * stop, muted variants, etc.) is derived at apply-time in
 * utils/theme.js so we're not hand-authoring 20+ full token sets.
 *
 * "forest" is the original/default theme, already fully defined by the
 * hand-tuned values in styles/variables.css. ThemeProvider treats it as
 * a special case — no inline overrides are applied for it — so a user
 * who never touches the switcher gets the exact original stylesheet,
 * pixel for pixel, not a re-derived approximation of it.
 */

function theme(id, family, name, primary, sidebar, sidebarText, bg, border, text, muted, accent, serif) {
  return { id, family, name, primary, sidebar, sidebarText, bg, border, text, muted, accent, serif };
}

export const THEME_FAMILIES = [
  {
    key: "green", label: "Green",
    themes: [
      theme("forest", "green", "Forest", "#1B5E43", "#0C2A1F", "#F4F1E8", "#FAF7F2", "#ECE7DE", "#1A1F1B", "#8A9088", "#C9A24B", true),
      theme("pine", "green", "Pine", "#14453A", "#081F1A", "#E7F0EC", "#F6F9F8", "#E2EAE7", "#1A1F1B", "#8A9088", "#C9A24B", true),
      theme("hunter", "green", "Hunter", "#2C4A3B", "#182D22", "#E9EFEA", "#F5F7F5", "#E3E8E3", "#1A1F1B", "#8A9088", "#C9A24B", true),
      theme("sage", "green", "Sage", "#5B7F63", "#33473A", "#F0F3EE", "#F7F8F4", "#E5E8E0", "#1C1F1C", "#87897E", "#C97B5A", false),
      theme("moss", "green", "Moss", "#6B7A3F", "#3E4623", "#F1F2E7", "#F8F9F1", "#E9EBDC", "#1C1F1C", "#87897E", "#C97B5A", false),
      theme("emerald", "green", "Emerald", "#0F9D6E", "#073B2A", "#E7FBF2", "#F2FBF7", "#DCEFE6", "#1C1F1C", "#87897E", "#E0A72E", false),
      theme("jade", "green", "Jade", "#1E8A6E", "#0E4A3B", "#E5F5F0", "#F2FAF7", "#DCEEE7", "#1C1F1C", "#87897E", "#E0A72E", false),
      theme("mint", "green", "Mint", "#3FAE85", "#0F4A36", "#E8FBF3", "#F2FCF8", "#DCF0E7", "#1C1F1C", "#87897E", "#E0714A", false),
      theme("pistachio", "green", "Pistachio", "#8FB996", "#3D5C43", "#EFF6EF", "#F8FBF6", "#E8F0E6", "#1C1F1C", "#87897E", "#D98B5F", false),
      theme("celadon", "green", "Celadon", "#9BC1A6", "#43614C", "#EEF5EF", "#F7FBF7", "#E7EFE6", "#1C1F1C", "#87897E", "#C9915A", false),
      theme("spring", "green", "Spring", "#6FC08B", "#1F5C3C", "#E9F8EE", "#F3FCF5", "#DFF0E4", "#1C1F1C", "#87897E", "#E0A72E", false),
      theme("eucalyptus", "green", "Eucalyptus", "#8FC9B0", "#2E5C4C", "#EAF6F1", "#F4FBF8", "#E1EEE8", "#1C1F1C", "#87897E", "#D97757", false),
    ],
  },
  {
    key: "teal", label: "Teal",
    themes: [
      theme("clinical-teal", "teal", "Clinical teal", "#0E6E5A", "#0B4238", "#EAF5F1", "#F5FAF9", "#E1EAE7", "#152420", "#77918B", "#D9A441", false),
      theme("seafoam", "teal", "Seafoam", "#178E76", "#0A5245", "#E8F7F2", "#F3FBF9", "#DBEEE7", "#152420", "#77918B", "#E0714A", false),
      theme("petrol", "teal", "Petrol", "#0B4F52", "#072F31", "#E4F1F1", "#F1F7F7", "#DCE9E9", "#152420", "#77918B", "#CBA135", true),
      theme("aqua", "teal", "Aqua", "#3FB8A6", "#0E5C50", "#E7F9F5", "#F2FCFA", "#DCF0EC", "#152420", "#77918B", "#E0A72E", false),
      theme("lagoon", "teal", "Lagoon", "#2E9C9C", "#0F4F4F", "#E6F6F6", "#F1FAFA", "#DCEEEE", "#152420", "#77918B", "#D97757", false),
      theme("turquoise", "teal", "Turquoise", "#1FB5A3", "#0A4A42", "#E5FAF6", "#F0FCFA", "#D9F0EA", "#152420", "#77918B", "#E0714A", false),
      theme("teal-mist", "teal", "Teal mist", "#9AD4C7", "#3D7369", "#EFFAF7", "#F7FDFB", "#E5F3EF", "#152420", "#77918B", "#C97B5A", false),
      theme("emerald-glass", "teal", "Emerald Glass", "#01D4C7", "#00665F", "#E7F9F6", "#F5FCFB", "#E1F3F0", "#152420", "#77918B", "#D9603B", false),
    ],
  },
  {
    key: "navy", label: "Navy",
    themes: [
      theme("midnight", "navy", "Midnight", "#1E2761", "#141B42", "#E9ECF9", "#F4F6FB", "#E2E5F0", "#171B33", "#7C82A3", "#D9A441", false),
      theme("steel-blue", "navy", "Steel blue", "#2C5D7C", "#1C3C50", "#E7F0F5", "#F4F8FA", "#DEEAF0", "#171B33", "#7C82A3", "#D97757", false),
      theme("royal", "navy", "Royal", "#1A3E8C", "#12295E", "#E6ECFA", "#F3F6FD", "#DDE5F8", "#171B33", "#7C82A3", "#E0A72E", true),
    ],
  },
  {
    key: "warm", label: "Warm / terracotta",
    themes: [
      theme("terracotta", "warm", "Terracotta", "#B85042", "#7A362B", "#F7EBE6", "#FBF8F3", "#EFE4D8", "#2B211C", "#9C8A7D", "#7C9885", true),
      theme("clay", "warm", "Clay", "#A6572E", "#6B3419", "#F7ECE3", "#FBF6F0", "#F0E3D6", "#2B211C", "#9C8A7D", "#4E8A82", false),
      theme("sand-sage", "warm", "Sand & sage", "#C98B5E", "#8C5A38", "#FBF3EA", "#FCF9F4", "#F2E7D9", "#2B211C", "#9C8A7D", "#6E8F73", false),
    ],
  },
  {
    key: "slate", label: "Slate / neutral",
    themes: [
      theme("charcoal", "slate", "Charcoal", "#33393D", "#22262A", "#EDEDEC", "#F7F7F6", "#E4E4E2", "#1F2224", "#8B8E90", "#D9603B", false),
      theme("graphite-blue", "slate", "Graphite blue", "#3A4550", "#262E36", "#EAEDEF", "#F6F8F9", "#E2E6E9", "#1F2224", "#8B8E90", "#3B9E8C", false),
      theme("warm-gray", "slate", "Warm gray", "#5C554D", "#3A362F", "#F2EFE9", "#F8F6F2", "#EBE7DF", "#1F2224", "#8B8E90", "#C97B4A", false),
    ],
  },
  {
    key: "berry", label: "Berry / plum",
    themes: [
      theme("berry", "berry", "Berry", "#6D2E46", "#431C2B", "#F7E9EE", "#FCF6F8", "#F1DFE5", "#251820", "#96828C", "#C99A3A", true),
      theme("plum", "berry", "Plum", "#4A2F5C", "#2E1D3A", "#EFE8F3", "#F8F5FA", "#E7DDEE", "#251820", "#96828C", "#3B9E8C", true),
      theme("lavender", "berry", "Lavender clinical", "#5B4B8A", "#392E5C", "#EFEBF7", "#F8F6FB", "#E6E1F2", "#251820", "#96828C", "#E0A72E", false),
    ],
  },
];

export const THEMES = THEME_FAMILIES.flatMap(f => f.themes);
export const DEFAULT_THEME_ID = "forest";

export function getThemeById(id) {
  return THEMES.find(t => t.id === id) || THEMES.find(t => t.id === DEFAULT_THEME_ID);
}
