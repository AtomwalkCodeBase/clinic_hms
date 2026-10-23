// Shared with the React Native app (health-journey-rn/src/healthJourney/derive.js). Keep both copies identical,
// or move them into one small package both apps import.
// Pure functions that turn the existing timeline / immunization API responses into what each
// screen needs. No network, no React: easy to unit test and identical for guardian and doctor
// (the doctor payload simply carries extra fields: icd10, evidence, event ids, flag ids, labs).
import { ageOn, analyteName, analyteUnit, daysBetween, fmtDate, fmtMonthYear, fmtNumber, fmtRange, parseISO } from './format';

const SEV_RANK = { NORMAL: 0, MILD: 1, ABNORMAL: 2, CRITICAL: 3 };
const VAX_RANK = { OVERDUE: 0, DUE: 1, UPCOMING: 2, SCHEDULED: 3, GIVEN: 4 };

export const isDoctor = (payload) => payload?.audience === 'doctor';
// "Wheezing episode" -> "Wheezing", "Cold / upper respiratory infection" -> "Cold": fits a lane label
export const shortLabel = (label) => label.split(' / ')[0].replace(/ episode$/, '');
const recurrentLabel = (doctor) => (doctor ? 'RECURRENT' : 'Happens often');

// ------------------------------------------------------------------ lanes (chart)
// Every mark has a date range, a shape and a tone; the chart maps dates to x itself.
export function laneMarks(payload) {
  const doctor = isDoctor(payload);
  const out = [];
  for (const lane of payload.lanes) {
    const marks = [];
    const add = (start, end, shape, toneName, meta) => marks.push({ start, end: end || start, shape, tone: toneName, meta });
    switch (lane.type) {
      case 'birth': {
        const b = lane.items[0];
        add(b.date, null, b.nicu_admission ? 'diamond' : 'dot', b.nicu_admission ? 'serious' : 'acute', { kind: 'birth', ...b });
        break;
      }
      case 'growth': {
        const byDate = {};
        Object.entries(lane.series).forEach(([ind, pts]) => pts.forEach((p) => {
          (byDate[p.date] = byDate[p.date] || { date: p.date, readings: {} }).readings[ind] = p;
        }));
        lane.alerts.forEach((a) => add(a.from, a.to, 'band', 'serious', { kind: 'faltering', ...a }));
        Object.values(byDate).forEach((d) => {
          const flags = Object.values(d.readings).map((r) => r.flag).filter(Boolean);
          const worst = flags.find((f) => f.startsWith('SEVERE')) || flags[0];
          add(d.date, null, worst ? 'diamond' : 'dot', worst ? (worst.startsWith('SEVERE') ? 'critical' : 'serious') : 'ink',
            { kind: 'growth', ...d, flag: worst });
        });
        break;
      }
      case 'immunization': {
        const byDate = {};
        lane.items.forEach((r) => { (byDate[r.date] = byDate[r.date] || []).push(r); });
        Object.entries(byDate).forEach(([date, rows]) => {
          const worst = rows.reduce((a, b) => (VAX_RANK[b.status] < VAX_RANK[a.status] ? b : a));
          const map = { GIVEN: ['check', 'good'], OVERDUE: ['cross', 'critical'], DUE: ['dot', 'warning'] };
          const [shape, t] = map[worst.status] || ['ring', 'muted'];
          add(date, null, shape, t, { kind: 'vaccines', date, rows, document_id: worst.document_id });
        });
        break;
      }
      case 'chronic': {
        const ep = lane.episode;
        add(ep.start, ep.end || payload.period.to, 'bar', 'chronic', { kind: 'chronic', laneId: lane.id, label: lane.label, ...ep });
        break;
      }
      case 'acute':
        lane.episodes.forEach((ep) => {
          const sev = ep.peak_severity;
          const multi = ep.end && ep.end !== ep.start;
          const shape = multi ? 'bar' : sev === 'CRITICAL' ? 'diamond' : 'dot';
          const t = sev === 'CRITICAL' ? 'critical' : sev === 'ABNORMAL' ? 'serious' : 'acute';
          add(ep.start, ep.end, shape, t, { kind: 'acute', laneId: lane.id, label: lane.label, recurrent: lane.is_recurrent, ...ep });
        });
        break;
      case 'hospital':
        lane.items.forEach((h) => add(h.start, h.end, h.kind === 'ADMISSION' ? 'bar' : 'diamond',
          h.is_critical ? 'critical' : 'serious', { kind: h.kind === 'ADMISSION' ? 'admission' : 'lab', ...h }));
        break;
      default:
    }
    const provisional = lane.type === 'chronic' ? lane.episode.is_provisional
      : lane.type === 'acute' ? lane.episodes.every((e) => e.is_provisional) : false;
    out.push({
      id: lane.id, type: lane.type, label: shortLabel(lane.label), marks,
      recurrent: !!lane.is_recurrent, provisional,
      sublabel: doctor && lane.type === 'chronic' ? (lane.episode.icd10_codes || []).join(', ') : null,
    });
  }
  return out;
}

// Overview "At a glance": ongoing conditions, conditions that keep returning, hospital care.
export function miniLanes(payload, max = 4) {
  const all = laneMarks(payload);
  const pick = [
    ...all.filter((l) => l.type === 'chronic'),
    ...all.filter((l) => l.type === 'acute' && l.recurrent),
    ...all.filter((l) => l.type === 'hospital'),
  ];
  return pick.slice(0, max).map((l) => (l.type === 'hospital' ? { ...l, label: 'Hospital' } : l));
}

// ------------------------------------------------------------------ feed (list)
const docFields = (ev) => (ev ? {
  icd10: ev.icd10, evidence: ev.evidence, severity: ev.severity, verified: ev.verified,
  provisional: ev.is_provisional, eventId: ev.id,
} : null);

export function feedItems(payload) {
  const doctor = isDoctor(payload);
  const dob = payload.patient.dob;
  const items = [];
  const push = (o) => items.push({ ageLabel: ageOn(dob, o.date), chips: [], ...o });

  for (const lane of payload.lanes) {
    if (lane.type === 'birth') {
      const b = lane.items[0];
      const parts = [b.gestation_weeks && `${b.gestation_weeks} weeks`, b.birth_weight_kg && `${b.birth_weight_kg} kg`,
        b.nicu_admission && `NICU ${b.nicu_days ?? '?'} days`].filter(Boolean);
      push({ id: 'birth', date: b.date, kind: 'birth', filter: 'hospital', marker: { shape: b.nicu_admission ? 'diamond' : 'dot', tone: b.nicu_admission ? 'serious' : 'acute' },
        title: 'Born', detail: parts.join(' · '),
        chips: b.preterm ? [{ tone: 'serious', text: doctor ? 'PRETERM' : 'Born early' }] : [], documentId: b.document_id });
    }
    if (lane.type === 'growth') {
      const w = lane.series.weight_kg || [];
      const last = w[w.length - 1];
      if (last) {
        const h = (lane.series.height_cm || []).find((p) => p.date === last.date);
        const hc = (lane.series.head_circ_cm || []).find((p) => p.date === last.date);
        const flags = [last, h, hc].filter((p) => p && p.flag);
        const vals = [`${last.value} kg`, h && `${h.value} cm`, hc && `head ${hc.value} cm`].filter(Boolean).join(' · ');
        push({ id: `growth:${last.date}`, date: last.date, kind: 'growth', filter: 'growth', marker: { shape: 'dot', tone: 'ink' },
          title: 'Latest growth check',
          detail: doctor ? `${vals}\nWFA z ${last.z} (P${Math.round(last.percentile)})` : vals,
          chips: flags.length ? [{ tone: 'serious', text: doctor ? flags.map((f) => f.flag).join(', ') : 'Outside usual range' }]
            : [{ tone: 'good', text: doctor ? 'Within ±2 SD' : 'Within expected range' }],
          documentId: last.document_id, target: 'growth' });
      }
      lane.alerts.forEach((a) => push({ id: `falter:${a.from}`, date: a.to, kind: 'alert', filter: 'growth',
        marker: { shape: 'diamond', tone: 'serious' }, title: doctor ? 'Growth faltering (WFA)' : 'Weight dropped',
        detail: doctor ? `z ${a.z_from} → ${a.z_to} (Δ ${a.drop} SD), ${fmtDate(a.from)} – ${fmtDate(a.to)}`
          : `Weight fell across centile lines between ${fmtMonthYear(a.from)} and ${fmtMonthYear(a.to)}.`,
        chips: [], target: 'growth' }));
    }
    if (lane.type === 'immunization') {
      const byDate = {};
      lane.items.forEach((r) => { (byDate[r.date] = byDate[r.date] || []).push(r); });
      Object.entries(byDate).forEach(([date, rows]) => {
        const pending = rows.filter((r) => r.status !== 'GIVEN');
        const given = rows.filter((r) => r.status === 'GIVEN');
        if (given.length) {
          push({ id: `vax:${date}`, date, kind: 'vaccine', filter: 'vaccines', marker: { shape: 'check', tone: 'good' },
            title: given.length === 1 ? 'Vaccine given' : `${given.length} vaccines given`,
            detail: given.map((r) => (doctor ? `${r.code}` : `${r.vaccine}${r.dose > 1 ? ` ${r.dose}` : ''}`)).join(', '),
            chips: given.some((r) => r.late) ? [{ tone: 'warning', text: doctor ? 'LATE' : 'Given late' }] : [],
            documentId: given[0].document_id, target: 'vaccines' });
        }
        pending.filter((r) => r.status === 'OVERDUE' || r.status === 'DUE').forEach((r) => push({
          id: `vax:${r.code}`, date: r.due_on, kind: 'vaccine', filter: 'vaccines',
          marker: { shape: r.status === 'OVERDUE' ? 'cross' : 'dot', tone: r.status === 'OVERDUE' ? 'critical' : 'warning' },
          title: `${r.vaccine} dose ${r.dose}`, detail: doctor ? `${r.code} · due ${fmtDate(r.due_on)} (${r.due_age})` : `Due ${fmtDate(r.due_on)}`,
          chips: [{ tone: r.status === 'OVERDUE' ? 'critical' : 'warning', text: doctor ? r.status : r.status_label }],
          target: 'vaccines' }));
      });
    }
    if (lane.type === 'chronic') {
      const ep = lane.episode;
      const first = ep.events[0];
      push({ id: `chronic:${ep.key}`, date: ep.start, kind: 'chronic', filter: 'illness',
        marker: { shape: 'bar', tone: 'chronic' }, title: `${lane.label} diagnosed`,
        detail: doctor ? `CHRONIC · ${ep.event_count} encounter${ep.event_count === 1 ? '' : 's'} · last seen ${fmtDate(ep.last_seen)}`
          : `Ongoing condition, since ${fmtDate(ep.start)}.`,
        chips: [ep.is_provisional ? { tone: 'warning', text: 'PROVISIONAL' } : { tone: 'info', text: doctor ? 'CHRONIC' : 'Ongoing' }],
        documentId: ep.document_ids[0], laneId: lane.id, episodeKey: ep.key,
        doctor: doctor ? { ...docFields(first), icd10: (ep.icd10_codes || []).join(', ') || first?.icd10 } : null });
    }
    if (lane.type === 'acute') {
      lane.episodes.forEach((ep) => {
        const sev = ep.peak_severity;
        const first = ep.events[0];
        const chips = [];
        if (sev === 'CRITICAL') chips.push({ tone: 'critical', text: doctor ? 'CRITICAL' : 'Hospital care needed' });
        else if (sev === 'ABNORMAL') chips.push({ tone: 'serious', text: doctor ? 'ABNORMAL' : 'Hospital stay' });
        if (lane.is_recurrent) chips.push({ tone: 'serious', text: `↻ ${recurrentLabel(doctor)}` });
        if (doctor && ep.is_provisional) chips.push({ tone: 'warning', text: 'PROVISIONAL' });
        push({ id: `acute:${ep.key}`, date: ep.start, endDate: ep.end, kind: 'acute', filter: 'illness',
          marker: { shape: sev === 'CRITICAL' ? 'diamond' : 'dot', tone: sev === 'CRITICAL' ? 'critical' : 'acute' },
          title: lane.label,
          detail: `${ep.event_count} doctor visit${ep.event_count === 1 ? '' : 's'}`,
          chips, documentId: ep.document_ids[0], laneId: lane.id, episodeKey: ep.key,
          doctor: doctor ? { ...docFields(first), icd10: (ep.icd10_codes || []).join(', ') || first?.icd10 } : null });
      });
    }
    if (lane.type === 'hospital') {
      lane.items.forEach((h) => {
        if (h.kind === 'ADMISSION') {
          const days = h.end ? daysBetween(h.start, h.end) : null;
          push({ id: `adm:${h.start}`, date: h.start, endDate: h.end, kind: 'hospital', filter: 'hospital',
            marker: { shape: 'diamond', tone: h.is_critical ? 'critical' : 'serious' },
            title: h.reason ? `Hospital stay: ${h.reason.toLowerCase()}` : 'Hospital stay',
            detail: [h.ward !== 'WARD' && h.ward, days != null && `${days} day${days === 1 ? '' : 's'}`].filter(Boolean).join(' · '),
            chips: [{ tone: h.is_critical ? 'critical' : 'serious', text: doctor ? (h.is_critical ? 'CRITICAL' : 'ADMISSION') : h.label }],
            documentId: h.document_id });
        } else {
          push({ id: `lab:${h.start}:${h.analyte}`, date: h.start, kind: 'lab', filter: 'hospital',
            marker: { shape: 'diamond', tone: 'critical' },
            title: doctor ? `${analyteName(h.analyte)} ${fmtNumber(h.value)} ${analyteUnit(h.analyte)}` : `${analyteName(h.analyte)} test result`,
            detail: doctor ? `Critical ${h.direction?.toLowerCase()}` : 'A result your doctor looked at closely',
            chips: [{ tone: 'critical', text: doctor ? 'CRITICAL LAB' : h.label }], documentId: h.document_id });
        }
      });
    }
  }
  // Discharge summaries put the illness on the discharge date: keep it next to its stay.
  items.sort((a, b) => (a.date === b.date ? a.id.localeCompare(b.id) : b.date.localeCompare(a.date)));
  return items;
}

export function groupByYear(items, dobIso) {
  const groups = [];
  for (const it of items) {
    const y = it.date.slice(0, 4);
    let g = groups[groups.length - 1];
    if (!g || g.year !== y) {
      // items arrive newest first, so this is the oldest age reached within that year
      const age = Math.floor(daysBetween(dobIso, it.date) / 365.25);
      g = { year: y, title: `${y} · age ${age < 1 ? 'under 1' : age}`, items: [] };
      groups.push(g);
    }
    g.items.push(it);
  }
  return groups;
}

export const FEED_FILTERS = [
  { key: 'all', label: 'All' }, { key: 'illness', label: 'Illness' },
  { key: 'hospital', label: 'Hospital' }, { key: 'vaccines', label: 'Vaccines' }, { key: 'growth', label: 'Growth' },
];

// ------------------------------------------------------------------ overview
export function attentionItems(payload) {
  const doctor = isDoctor(payload);
  const out = [];
  const imm = payload.lanes.find((l) => l.type === 'immunization');
  (imm?.items || []).filter((r) => r.status === 'OVERDUE').forEach((r) => out.push({
    id: `vax:${r.code}`, tone: 'critical', icon: 'cross', action: 'book',
    title: doctor ? `${r.code} overdue` : `${r.vaccine} vaccine is overdue`,
    detail: doctor ? `${r.vaccine} dose ${r.dose}, due ${fmtDate(r.due_on)} (${r.due_age})` : `Dose ${r.dose} was due on ${fmtDate(r.due_on)}.`,
  }));
  (imm?.items || []).filter((r) => r.status === 'DUE').forEach((r) => out.push({
    id: `vax:${r.code}`, tone: 'warning', icon: 'dot', action: 'book',
    title: doctor ? `${r.code} due` : `${r.vaccine} vaccine is due`, detail: `Due ${fmtDate(r.due_on)}.`,
  }));
  const growth = payload.lanes.find((l) => l.type === 'growth');
  const w = growth?.series.weight_kg || [];
  const last = w[w.length - 1];
  if (last?.flag) out.push({ id: 'growth', tone: 'serious', icon: 'diamond', action: 'growth',
    title: doctor ? `Weight ${last.flag} (z ${last.z})` : 'Latest weight is outside the usual range',
    detail: `Measured ${fmtDate(last.date)}.` });
  return out;
}

// ------------------------------------------------------------------ episode detail
const keyDate = (k) => k.split(':').pop();

export function findLane(payload, laneId) {
  return payload?.lanes.find((l) => l.id === laneId) || null;
}

export function episodeModel(payload, laneId) {
  const lane = findLane(payload, laneId);
  if (!lane) return null;
  const doctor = isDoctor(payload);
  const dob = payload.patient.dob;
  const episodes = (lane.type === 'chronic' ? [lane.episode] : lane.episodes).slice().sort((a, b) => b.start.localeCompare(a.start));
  const rec = lane.recurrence;
  const lines = [];
  const chips = [];
  if (lane.type === 'chronic') {
    chips.push({ tone: 'info', text: doctor ? 'CHRONIC' : 'Ongoing condition' });
    lines.push(doctor ? `Onset ${fmtDate(lane.episode.start)} (age ${lane.episode.onset_age}). ${lane.episode.event_count} encounter(s).`
      : `Ongoing since ${fmtDate(lane.episode.start)}, when ${payload.patient.sex === 'female' ? 'she' : 'he'} was ${lane.episode.onset_age} old.`);
  }
  if (rec?.is_recurrent) {
    chips.push({ tone: 'serious', text: `↻ ${recurrentLabel(doctor)}` });
    const dates = rec.episode_keys.map(keyDate);
    const n = rec.rule.min_count;
    const wm = rec.rule.window_months;
    const window = wm >= 1200 ? 'at any age' : wm % 12 === 0 ? `within ${wm / 12 === 1 ? 'a year' : `${wm / 12} years`}` : `within ${wm} months`;
    if (doctor) {
      const age = rec.age_max_days ? `, age < ${Math.round(rec.age_max_days / 365.25)} y` : '';
      lines.push(`Rule ${rec.group}: ≥${n} episodes ${wm >= 1200 ? 'ever' : `/ ${wm} mo`}${age}. Triggered ${fmtDate(rec.triggered_on)} by episodes on ${dates.map(fmtDate).join(', ')}.`);
      if (rec.clinical_hint) lines.push(`Hint: ${rec.clinical_hint}.`);
    } else {
      lines.push(`${lane.label} came back ${n} times ${window}, between ${fmtMonthYear(dates[0])} and ${fmtMonthYear(dates[dates.length - 1])}.`);
      lines.push(`The clinic is alerted when this happens ${n} times ${window}.`);
    }
  } else if (rec?.context === 'typical for age') {
    lines.push(doctor ? `${rec.episodes_last_12m} episode(s) in 12 months; expected ≤${rec.expected_per_year}/year for age.`
      : `${rec.episodes_last_12m} in the last 12 months. This is typical for ${payload.patient.sex === 'female' ? 'her' : 'his'} age.`);
  }
  if (doctor && episodes.some((e) => e.is_provisional)) chips.push({ tone: 'warning', text: 'PROVISIONAL' });
  return {
    lane, episodes, recurrence: rec || null, lines, chips, doctor,
    title: lane.label,
    flag: doctor && rec?.is_recurrent ? { id: rec.flag_id, acknowledgedAt: rec.acknowledged_at, hint: rec.clinical_hint } : null,
    rows: episodes.map((e) => ({
      key: e.key, range: fmtRange(e.start, e.end && e.end !== e.start ? e.end : null),
      age: ageOn(dob, e.start), visits: e.event_count, severity: e.peak_severity, severityLabel: e.peak_severity_label,
      documentId: e.document_ids[0], provisional: e.is_provisional, icd10: (e.icd10_codes || []).join(', '),
      events: e.events,
    })),
  };
}

// ------------------------------------------------------------------ doctor
export function reviewQueue(payload) {
  if (!isDoctor(payload)) return [];
  const q = [];
  for (const lane of payload.lanes) {
    const eps = lane.type === 'chronic' ? [lane.episode] : lane.type === 'acute' ? lane.episodes : [];
    eps.forEach((ep) => ep.events.filter((e) => e.is_provisional && !e.verified).forEach((e) => q.push({
      id: `ev:${e.id}`, kind: 'provisional', eventId: e.id, laneId: lane.id,
      title: `${e.text}${e.icd10 ? ` (${e.icd10})` : ''}`, detail: `Provisional · ${fmtDate(e.date)}${e.evidence ? ` · “${e.evidence}”` : ''}`,
      documentId: e.document_id,
    })));
    if (lane.recurrence?.is_recurrent && lane.recurrence.flag_id && !lane.recurrence.acknowledged_at) {
      q.push({ id: `flag:${lane.recurrence.flag_id}`, kind: 'flag', flagId: lane.recurrence.flag_id, laneId: lane.id,
        title: `Recurrent: ${lane.label}`, detail: lane.recurrence.clinical_hint || `Triggered ${fmtDate(lane.recurrence.triggered_on)}` });
    }
  }
  return q;
}

export function problemList(payload) {
  if (!isDoctor(payload)) return [];
  return payload.lanes.filter((l) => l.type === 'chronic' || (l.type === 'acute' && l.is_recurrent)).map((l) => {
    const ep = l.type === 'chronic' ? l.episode : l.episodes[0];
    const codes = l.type === 'chronic' ? l.episode.icd10_codes : [...new Set(l.episodes.flatMap((e) => e.icd10_codes || []))];
    return {
      laneId: l.id, label: l.label, codes: (codes || []).join(', '),
      status: l.type === 'chronic' ? (ep.is_provisional ? 'PROVISIONAL' : 'ACTIVE') : 'RECURRENT',
      since: l.type === 'chronic' ? fmtDate(ep.start) : `${l.episodes.length} episodes`,
    };
  });
}

export function abnormalLabs(payload) {
  return (payload.clinical?.labs || []).map((l) => {
    const lim = l.limits || {};
    const ref = lim.low != null && lim.high != null ? `${lim.low}–${lim.high}` : lim.high != null ? `≤ ${lim.high}` : lim.low != null ? `≥ ${lim.low}` : '';
    return { ...l, name: analyteName(l.analyte), unit: l.unit_raw || analyteUnit(l.analyte), ref,
      flag: `${l.direction === 'LOW' ? 'L' : 'H'}${l.severity === 'CRITICAL' ? '!!' : ''}` };
  });
}

export function sortRowsByAge(rows) {
  return rows.slice().sort((a, b) => parseISO(a.due_on) - parseISO(b.due_on));
}

export { SEV_RANK };
