// Swimlane health-journey timeline (ECharts custom series).
import React, { useMemo } from 'react';
import ReactECharts from './EChart';
import {
  DAY_MS, GROWTH_FLAG_STYLE, SEVERITY_STYLE, VACCINE_STYLE, formatAgeDays, toMs, useChartTokens,
} from './theme';

const BAR_H = 12;
const DOT_R = 6;

// ---------------------------------------------------------------- data -> items
function buildItems(payload, axisMode) {
  const dobMs = toMs(payload.patient.dob);
  const periodEnd = toMs(payload.period.to);
  const x = (iso) => (axisMode === 'age' ? (toMs(iso) - dobMs) / DAY_MS : toMs(iso));
  const items = [];
  const push = (lane, start, end, shape, token, meta) =>
    items.push({ value: [x(start), x(end || start), lane, shape, token], meta });

  payload.lanes.forEach((lane, i) => {
    switch (lane.type) {
      case 'birth': {
        const b = lane.items[0];
        push(i, payload.patient.dob, null, b.nicu_admission ? 'diamond' : 'dot',
          b.nicu_admission ? 'status-serious' : 'text-secondary', { kind: 'birth', ...b });
        break;
      }
      case 'growth': {
        // one marker per measurement date, coloured by the worst flag of that day
        const byDate = {};
        Object.entries(lane.series).forEach(([ind, pts]) => pts.forEach((p) => {
          (byDate[p.date] ||= { date: p.date, readings: {} }).readings[ind] = p;
        }));
        Object.values(byDate).forEach((d) => {
          const flags = Object.values(d.readings).map((r) => r.flag).filter(Boolean);
          const worst = flags.find((f) => f.startsWith('SEVERE')) || flags[0];
          push(i, d.date, null, worst ? 'diamond' : 'dot',
            worst ? GROWTH_FLAG_STYLE[worst].token : 'growth-line', { kind: 'growth', ...d, worst });
        });
        lane.alerts.forEach((a) => push(i, a.from, a.to, 'band', 'status-serious', { kind: 'faltering', ...a }));
        break;
      }
      case 'immunization': {
        // one mark per day (6 doses are usually given together); worst status wins
        const rank = { OVERDUE: 0, DUE: 1, UPCOMING: 2, SCHEDULED: 3, GIVEN: 4 };
        const byDate = {};
        lane.items.forEach((r) => { (byDate[r.date] ||= []).push(r); });
        Object.entries(byDate).forEach(([d, rows]) => {
          const worst = rows.reduce((a, b) => (rank[b.status] < rank[a.status] ? b : a));
          const st = VACCINE_STYLE[worst.status] || VACCINE_STYLE.SCHEDULED;
          push(i, d, null, st.shape, st.token, { kind: 'vaccines', date: d, rows, document_id: worst.document_id });
        });
        break;
      }
      case 'chronic': {
        const ep = lane.episode;
        const end = ep.end || payload.period.to;
        items.push({
          value: [x(ep.start), axisMode === 'age' ? (Math.min(toMs(end), periodEnd) - dobMs) / DAY_MS
            : Math.min(toMs(end), periodEnd), i, 'bar', 'chronic'],
          meta: { kind: 'chronic', label: lane.label, ...ep },
        });
        ep.events.forEach((e) => push(i, e.date, null, 'tick',
          SEVERITY_STYLE[e.severity]?.token || 'text-primary', { kind: 'visit', label: lane.label, ...e }));
        break;
      }
      case 'acute':
        lane.episodes.forEach((ep) => {
          const st = SEVERITY_STYLE[ep.peak_severity] || SEVERITY_STYLE.NORMAL;
          const multiDay = ep.end && ep.end !== ep.start;
          push(i, ep.start, multiDay ? ep.end : null, multiDay ? 'bar' : st.shape, st.token,
            { kind: 'acute', label: lane.label, recurrent: lane.is_recurrent, ...ep });
        });
        break;
      case 'hospital':
        lane.items.forEach((h) => {
          const token = h.is_critical ? 'status-critical' : 'status-serious';
          if (h.kind === 'ADMISSION') push(i, h.start, h.end || h.start, 'bar', token, { kind: 'admission', ...h });
          else push(i, h.start, null, 'diamond', token, { kind: 'lab', ...h });
        });
        break;
      default:
    }
  });
  return items;
}

// ---------------------------------------------------------------- shapes
function shapeFor(shape, cx, cy, x1, color, surface) {
  const ring = { stroke: surface, lineWidth: 2 };   // 2px surface ring on overlapping marks
  switch (shape) {
    case 'bar':
      return { type: 'rect', shape: { x: cx, y: cy - BAR_H / 2, width: Math.max(x1 - cx, 6), height: BAR_H, r: 4 },
        style: { fill: color, ...ring } };
    case 'band':
      return { type: 'rect', shape: { x: cx, y: cy - BAR_H, width: Math.max(x1 - cx, 6), height: BAR_H * 2, r: 4 },
        style: { fill: color, opacity: 0.18 }, z2: -1 };
    case 'diamond': {
      const r = DOT_R + 1;
      return { type: 'polygon', shape: { points: [[cx, cy - r], [cx + r, cy], [cx, cy + r], [cx - r, cy]] },
        style: { fill: color, ...ring } };
    }
    case 'ring':
      return { type: 'circle', shape: { cx, cy, r: DOT_R - 1 }, style: { fill: surface, stroke: color, lineWidth: 2 } };
    case 'tick':
      return { type: 'rect', shape: { x: cx - 1, y: cy - BAR_H / 2 - 4, width: 2, height: BAR_H + 8 },
        style: { fill: color } };
    case 'check':
      return { type: 'group', children: [
        { type: 'circle', shape: { cx, cy, r: DOT_R }, style: { fill: color, ...ring } },
        { type: 'polyline', shape: { points: [[cx - 3, cy], [cx - 1, cy + 2.5], [cx + 3.5, cy - 2.5]] },
          style: { stroke: surface, lineWidth: 1.6, fill: 'none' } }] };
    case 'cross':
      return { type: 'group', children: [
        { type: 'circle', shape: { cx, cy, r: DOT_R }, style: { fill: color, ...ring } },
        { type: 'line', shape: { x1: cx - 2.5, y1: cy - 2.5, x2: cx + 2.5, y2: cy + 2.5 }, style: { stroke: surface, lineWidth: 1.6 } },
        { type: 'line', shape: { x1: cx + 2.5, y1: cy - 2.5, x2: cx - 2.5, y2: cy + 2.5 }, style: { stroke: surface, lineWidth: 1.6 } }] };
    default:
      return { type: 'circle', shape: { cx, cy, r: DOT_R }, style: { fill: color, ...ring } };
  }
}

// ---------------------------------------------------------------- tooltip text
function tooltipHtml(m, axisLabel) {
  const row = (k, v) => (v == null || v === '' ? '' : `<div><span class="phj-tt-k">${k}</span> ${v}</div>`);
  const head = (t) => `<div class="phj-tt-h">${t}</div>`;
  switch (m.kind) {
    case 'birth':
      return head('Birth') + row('Gestation', m.gestation_weeks && `${m.gestation_weeks} weeks${m.preterm ? ' (preterm)' : ''}`)
        + row('Birth weight', m.birth_weight_kg && `${m.birth_weight_kg} kg`) + row('NICU', m.nicu_admission ? `${m.nicu_days ?? '?'} days` : 'No');
    case 'growth':
      return head(`Growth · ${m.date}`) + Object.entries(m.readings).map(([k, r]) =>
        row({ weight_kg: 'Weight', height_cm: 'Height', head_circ_cm: 'Head' }[k],
          `${r.value} ${k === 'weight_kg' ? 'kg' : 'cm'} · ${r.percentile != null ? `${r.percentile}th centile` : 'no reference chart for this age'}${r.flag ? ` · ${GROWTH_FLAG_STYLE[r.flag].label}` : ''}`)).join('');
    case 'faltering':
      return head('Weight dropped across centiles') + row('From', m.from) + row('To', m.to) + row('Change', `${m.drop} SD`);
    case 'vaccines':
      return head(`Vaccines · ${m.date}`) + m.rows.map((r) => row(
        `${(VACCINE_STYLE[r.status] || VACCINE_STYLE.SCHEDULED).icon} ${r.status_label}`,
        `${r.vaccine} dose ${r.dose}${r.status === 'GIVEN' ? '' : ` (due ${r.due_age})`}${r.late ? ' · late' : ''}`)).join('');
    case 'chronic':
      return head(m.label) + row('Since', `${m.start} (age ${m.onset_age})`) + row('Visits', m.event_count) + row('Status', 'Ongoing');
    case 'visit':
      return head(`${m.label} – visit`) + row('Date', `${m.date} (${m.age_label})`) + row('Noted as', m.text);
    case 'acute':
      return head(m.label) + row('Date', m.end && m.end !== m.start ? `${m.start} → ${m.end}` : m.start)
        + row('Age', m.onset_age) + row('Visits', m.event_count) + row('', m.peak_severity_label !== 'NORMAL' ? m.peak_severity_label : '')
        + (m.recurrent ? row('', 'Happens often') : '');
    case 'admission':
      return head(m.label) + row('Ward', m.ward) + row('Dates', `${m.start}${m.end ? ` → ${m.end}` : ''}`) + row('Reason', m.reason);
    case 'lab':
      return head(m.label) + row('Test', m.analyte.replace(/_/g, ' ').toLowerCase()) + row('Value', `${m.value} (${m.direction?.toLowerCase()})`) + row('Date', m.start);
    default:
      return axisLabel;
  }
}

// ---------------------------------------------------------------- component
export default function TimelineChart({ payload, axisMode = 'age', onOpenDocument }) {
  const t = useChartTokens();
  const option = useMemo(() => {
    const items = buildItems(payload, axisMode);
    const lanes = payload.lanes.map((l) => (l.is_recurrent ? `${l.label}  ↻` : l.label));
    const dobMs = toMs(payload.patient.dob);
    const xFmt = axisMode === 'age' ? (v) => (v < 1 ? 'Birth' : formatAgeDays(v))
      : (v) => new Date(v).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' });
    const xMin = axisMode === 'age' ? Math.max(0, (toMs(payload.period.from) - dobMs) / DAY_MS) : toMs(payload.period.from);
    const xMax = axisMode === 'age' ? (toMs(payload.period.to) - dobMs) / DAY_MS : toMs(payload.period.to);
    // age axis ticks on whole months: 1, 3, 6 or 12-month steps depending on span
    const spanM = (xMax - xMin) / 30.4375;
    const narrow = typeof window !== 'undefined' && window.innerWidth < 600;
    const baseStep = spanM <= 8 ? 1 : spanM <= 30 ? 3 : spanM <= 72 ? 6 : spanM <= 144 ? 12 : 24;
    const stepM = narrow ? baseStep * 2 : baseStep;
    const zoomable = spanM > 36;                         // a long history can be zoomed and panned
    const xMinAxis = axisMode === 'age' ? Math.floor(xMin / (stepM * 30.4375)) * stepM * 30.4375 : xMin;

    return {
      backgroundColor: 'transparent',
      animation: false,
      grid: { left: narrow ? 104 : 180, right: narrow ? 16 : 36, top: 16, bottom: zoomable ? 78 : 40 },
      dataZoom: zoomable ? [
        { type: 'inside', xAxisIndex: 0, filterMode: 'none', start: 0, end: 100 },
        { type: 'slider', xAxisIndex: 0, filterMode: 'none', start: 0, end: 100, height: 22, bottom: 8, brushSelect: false, borderColor: t.grid,
          fillerColor: t['band-inner'], textStyle: { color: t['text-muted'], fontSize: 12 }, labelFormatter: (v) => xFmt(v) },
      ] : undefined,
      tooltip: {
        trigger: 'item', confine: true,
        backgroundColor: t['surface-1'], borderColor: t.grid, textStyle: { color: t['text-primary'], fontSize: 13 },
        extraCssText: 'box-shadow: 0 8px 24px rgba(0,0,0,0.14); border-radius: 10px; padding: 10px 12px;',
        formatter: (p) => tooltipHtml(p.data.meta, xFmt(p.value[0])),
      },
      xAxis: {
        type: axisMode === 'age' ? 'value' : 'time', min: xMinAxis, max: xMax,
        ...(axisMode === 'age' ? { interval: stepM * 30.4375 } : {}),
        axisLabel: { color: t['text-muted'], fontSize: 13, formatter: xFmt, hideOverlap: true, showMaxLabel: false },
        axisLine: { lineStyle: { color: t.axis } },
        splitLine: { show: true, lineStyle: { color: t.grid, width: 1 } },
      },
      yAxis: {
        type: 'category', data: lanes, inverse: true,
        axisTick: { show: false }, axisLine: { show: false },
        axisLabel: { color: t['text-secondary'], fontSize: narrow ? 12 : 14, fontWeight: 500, width: narrow ? 96 : 165, overflow: 'truncate' },
        splitLine: { show: true, lineStyle: { color: t.grid, width: 1 } },
        splitArea: { show: true, areaStyle: { color: ['transparent', t['band-outer']] } },
      },
      series: [{
        type: 'custom',
        clip: true,
        encode: { x: [0, 1], y: 2 },
        data: items,
        renderItem: (params, api) => {
          const [x0, cy] = api.coord([api.value(0), api.value(2)]);
          const [x1] = api.coord([api.value(1), api.value(2)]);
          return shapeFor(api.value(3), x0, cy, x1, t[api.value(4)] || t['text-primary'], t['surface-1']);
        },
      }],
    };
  }, [payload, axisMode, t]);

  const zoomable = (toMs(payload.period.to) - toMs(payload.period.from)) / DAY_MS / 30.4375 > 36;
  const height = 56 + payload.lanes.length * 46 + (zoomable ? 38 : 0);
  return (
    <ReactECharts
      option={option}
      notMerge
      style={{ height, width: '100%' }}
      onEvents={{ click: (p) => { const id = p.data?.meta?.document_id; if (id && onOpenDocument) onOpenDocument(id); } }}
      aria-label="Health timeline chart"
    />
  );
}

export { buildItems };
