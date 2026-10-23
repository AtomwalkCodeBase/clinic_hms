// Shared with the React Native app (health-journey-rn/src/healthJourney/format.js). Keep both copies identical.
// Date and age formatting. Dates from the API are ISO 'YYYY-MM-DD' (no time zone), so they are
// parsed as local calendar dates to avoid off-by-one-day shifts.
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DAY = 86400000;

export const parseISO = (iso) => {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  return new Date(y, m - 1, d);
};
export const toISO = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
export const daysBetween = (aIso, bIso) => Math.round((parseISO(bIso) - parseISO(aIso)) / DAY);

export const fmtDate = (iso) => {
  if (!iso) return '';
  const d = parseISO(iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
};
export const fmtMonthYear = (iso) => {
  const d = parseISO(iso);
  return `${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
};

// "14 Jan 2026", "3 – 9 Apr 2026", "28 Oct – 3 Nov 2025", "28 Dec 2025 – 3 Jan 2026"
export function fmtRange(startIso, endIso) {
  if (!endIso || endIso === startIso) return fmtDate(startIso);
  const a = parseISO(startIso);
  const b = parseISO(endIso);
  if (a.getFullYear() !== b.getFullYear()) return `${fmtDate(startIso)} – ${fmtDate(endIso)}`;
  if (a.getMonth() !== b.getMonth()) return `${a.getDate()} ${MONTHS[a.getMonth()]} – ${fmtDate(endIso)}`;
  return `${a.getDate()} – ${fmtDate(endIso)}`;
}

// Age the way pediatricians say it. long: "7 months", "2 y 3 m"; short (axes): "7 m", "2 y".
export function formatAge(days, short = false) {
  if (days == null) return '';
  if (days < 1) return 'Birth';
  if (days <= 28) return short ? `${days} d` : `${days} day${days === 1 ? '' : 's'}`;
  const m = Math.floor(days / 30.4375);
  if (m < 24) return short ? `${m} m` : `${m} month${m === 1 ? '' : 's'}`;
  const y = Math.floor(m / 12);
  const r = m % 12;
  if (short) return r ? `${y} y ${r} m` : `${y} y`;
  return r ? `${y} y ${r} m` : `${y} years`;
}
export const ageOn = (dobIso, iso) => formatAge(daysBetween(dobIso, iso));

export const PERIODS = [
  { key: '6m', label: '6 months', months: 6 },
  { key: '1y', label: '1 year', months: 12 },
  { key: '3y', label: '3 years', months: 36 },
  { key: 'all', label: 'Since birth', months: null, flex: 1.45 },
];

export function periodRange(key, today = new Date()) {
  const p = PERIODS.find((x) => x.key === key) || PERIODS[3];
  const to = toISO(today);
  if (!p.months) return { from: undefined, to };
  const f = new Date(today);
  f.setMonth(f.getMonth() - p.months);
  return { from: toISO(f), to };
}

const ANALYTES = {
  HEMOGLOBIN_G_DL: ['Haemoglobin', 'g/dL'], PLATELETS_PER_UL: ['Platelets', '/µL'],
  WBC_PER_UL: ['WBC', '/µL'], GLUCOSE_MG_DL: ['Glucose', 'mg/dL'], SODIUM_MMOL_L: ['Sodium', 'mmol/L'],
  POTASSIUM_MMOL_L: ['Potassium', 'mmol/L'], BILIRUBIN_TOTAL_MG_DL: ['Total bilirubin', 'mg/dL'],
  CREATININE_MG_DL: ['Creatinine', 'mg/dL'], CRP_MG_L: ['CRP', 'mg/L'],
};
export const analyteName = (code) => (ANALYTES[code] || [code.replace(/_/g, ' ').toLowerCase()])[0];
export const analyteUnit = (code) => (ANALYTES[code] || [null, ''])[1];
export const fmtNumber = (v) =>
  v >= 10000 ? Math.round(v).toLocaleString('en-IN') : String(Math.round(v * 100) / 100);
