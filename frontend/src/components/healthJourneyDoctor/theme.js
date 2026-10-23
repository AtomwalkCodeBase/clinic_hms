// Chart colours come from CSS custom properties (see healthJourney.css) so light/dark
// are two *selected* palettes, not an automatic flip. ECharts needs literal values,
// so we read the tokens at render time and re-read when the colour scheme changes.
import { useEffect, useState } from 'react';

const TOKENS = [
  'surface-1', 'text-primary', 'text-secondary', 'text-muted', 'grid', 'axis',
  'chronic', 'acute', 'growth-line', 'band-outer', 'band-inner', 'band-median',
  'status-good', 'status-warning', 'status-serious', 'status-critical',
];

export function readTokens(el = document.documentElement) {
  const cs = getComputedStyle(el);
  return Object.fromEntries(TOKENS.map(t => [t, cs.getPropertyValue(`--dhj-${t}`).trim()]));
}

export function useChartTokens() {
  const [tokens, setTokens] = useState(() => readTokens());
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const refresh = () => setTokens(readTokens());
    mq.addEventListener('change', refresh);
    const obs = new MutationObserver(refresh); // portal theme toggle via data-theme
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => { mq.removeEventListener('change', refresh); obs.disconnect(); };
  }, []);
  return tokens;
}

// Severity / status -> colour token + shape + text, so meaning is never colour alone.
export const SEVERITY_STYLE = {
  CRITICAL: { token: 'status-critical', shape: 'diamond', icon: '◆' },
  ABNORMAL: { token: 'status-serious', shape: 'dot', icon: '●' },
  MILD:     { token: 'acute', shape: 'dot', icon: '●' },
  NORMAL:   { token: 'acute', shape: 'dot', icon: '●' },
};

export const VACCINE_STYLE = {
  GIVEN:     { token: 'status-good', shape: 'check', icon: '✓' },
  OVERDUE:   { token: 'status-critical', shape: 'cross', icon: '✕' },
  DUE:       { token: 'status-warning', shape: 'dot', icon: '!' },
  UPCOMING:  { token: 'text-muted', shape: 'ring', icon: '○' },
  SCHEDULED: { token: 'text-muted', shape: 'ring', icon: '○' },
};

export const GROWTH_FLAG_STYLE = {
  SEVERE_LOW:  { token: 'status-critical', label: 'Well below expected' },
  LOW:         { token: 'status-serious', label: 'Below expected' },
  HIGH:        { token: 'status-serious', label: 'Above expected' },
  SEVERE_HIGH: { token: 'status-critical', label: 'Well above expected' },
};

export const DAY_MS = 86400000;
export const toMs = (iso) => new Date(`${iso}T00:00:00`).getTime();

export function formatAgeDays(days) {
  if (days < 0) return 'before birth';
  if (days <= 28) return `${Math.round(days)} d`;
  const m = Math.round(days / 30.4375 * 100) / 100 | 0;
  if (m < 24) return `${m} m`;
  const y = Math.floor(m / 12), r = m % 12;
  return r ? `${y} y ${r} m` : `${y} y`;
}
