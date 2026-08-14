/**
 * context/ThemeContext.jsx
 * --------------------------
 * Lets any logged-in user (any of the 8 roles) pick a color theme from
 * config/themes.config.js. Applied by setting CSS custom properties
 * directly on <html>, so every existing component that already reads
 * var(--color-primary) etc. re-themes for free — no component changes
 * needed anywhere else in the app.
 *
 * Persisted to localStorage only (no backend field for this yet) — which
 * actually suits this app well: the same browser is typically used to
 * switch between the different demo role logins, so the choice sticks
 * across all of them without needing a synced per-user setting.
 */
import { createContext, useContext, useState, useEffect, useMemo, useCallback } from "react";
import { THEMES, DEFAULT_THEME_ID, getThemeById } from "../config/themes.config";
import { deriveThemeVars } from "../utils/theme";

const STORAGE_KEY = "atomwalk_theme";
const ThemeContext = createContext(null);

// "forest" is the only theme with hand-tuned values baked directly into
// styles/variables.css (every other theme, including the app default, is
// derived at apply-time). Kept as its own constant — decoupled from
// DEFAULT_THEME_ID — so picking "Forest" from the switcher always gets the
// exact original stylesheet, regardless of which theme the app defaults to.
const ORIGINAL_STYLESHEET_THEME_ID = "forest";

function readStoredThemeId() {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return stored && THEMES.some(t => t.id === stored) ? stored : DEFAULT_THEME_ID;
  } catch {
    return DEFAULT_THEME_ID;
  }
}

export function ThemeProvider({ children }) {
  const [themeId, setThemeId] = useState(readStoredThemeId);

  useEffect(() => {
    const root = document.documentElement;
    const vars = deriveThemeVars(getThemeById(themeId));
    if (themeId === ORIGINAL_STYLESHEET_THEME_ID) {
      // Forest — clear any inline overrides so the hand-tuned values in
      // variables.css take over again, unmodified.
      Object.keys(vars).forEach(key => root.style.removeProperty(key));
    } else {
      Object.entries(vars).forEach(([key, value]) => root.style.setProperty(key, value));
    }
    try {
      window.localStorage.setItem(STORAGE_KEY, themeId);
    } catch {
      // Private browsing / storage disabled — theme still applies for
      // this session, it just won't persist across reloads.
    }
  }, [themeId]);

  const setTheme = useCallback((id) => {
    setThemeId(THEMES.some(t => t.id === id) ? id : DEFAULT_THEME_ID);
  }, []);

  const value = useMemo(() => ({
    themeId,
    theme: getThemeById(themeId),
    setTheme,
    themes: THEMES,
  }), [themeId, setTheme]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within a ThemeProvider");
  return ctx;
}
