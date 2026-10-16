// Growth chart: WHO (0-5 y) / IAP (5-18 y) reference bands with the child's own readings on top.
// Bands: -3..-2 and +2..+3 SD (outer), -2..+2 SD (inner, the "expected" range), median dashed.
import React, { useEffect, useMemo, useState } from 'react';
import ReactECharts from './EChart';
import { GROWTH_FLAG_STYLE, useChartTokens } from './theme';

const INDICATORS = [
  { key: 'weight_kg', label: 'Weight', unit: 'kg' },
  { key: 'height_cm', label: 'Height', unit: 'cm' },
  { key: 'head_circ_cm', label: 'Head size', unit: 'cm' },
];

const fmtAgeM = (m) => (m < 24 ? `${Math.round(m)} m` : `${Math.floor(m / 12)} y${Math.round(m % 12) ? ` ${Math.round(m % 12)} m` : ''}`);

export default function GrowthChart({ api, patientId, onOpenDocument }) {
  const [indicator, setIndicator] = useState('weight_kg');
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const t = useChartTokens();
  const meta = INDICATORS.find((i) => i.key === indicator);

  useEffect(() => {
    let live = true;
    setData(null);
    api.growth(patientId, indicator).then((d) => live && setData(d)).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [api, patientId, indicator]);

  const option = useMemo(() => {
    if (!data) return null;
    const ref = data.reference;
    const curve = (z) => ref[z] || [];
    const refAge = curve('0').length ? curve('0')[curve('0').length - 1][0] : 24;
    const lastAge = Math.max(refAge, ...data.points.map((p) => p.age_months + 6));
    const stepM = lastAge <= 12 ? 2 : lastAge <= 36 ? 6 : 12;
    const xMax = Math.ceil(lastAge / stepM) * stepM;
    // a band is the polygon between two z-curves: lower curve forward, upper curve back
    const bandPoly = (api, lo, hi) => [
      ...curve(lo).map((p) => api.coord(p)),
      ...curve(hi).slice().reverse().map((p) => api.coord(p)),
    ];
    const bands = {
      type: 'custom', silent: true, clip: true, z: 1, tooltip: { show: false },
      data: [[0, 0]],
      renderItem: (params, api) => ({
        type: 'group',
        children: [
          ['-3', '-2', 'band-outer'], ['-2', '2', 'band-inner'], ['2', '3', 'band-outer'],
        ].map(([lo, hi, tok]) => ({
          type: 'polygon', shape: { points: bandPoly(api, lo, hi) }, style: { fill: t[tok] },
        })),
      }),
    };
    const pts = data.points.map((p) => ({
      value: [p.age_months, p.value], meta: p,
      itemStyle: { color: p.flag ? t[GROWTH_FLAG_STYLE[p.flag].token] : t['growth-line'], borderColor: t['surface-1'], borderWidth: 2 },
      symbol: p.flag ? 'diamond' : 'circle',
    }));
    return {
      backgroundColor: 'transparent',
      animation: false,
      grid: { left: 52, right: 56, top: 32, bottom: 44 },
      tooltip: {
        trigger: 'item', confine: true, backgroundColor: t['surface-1'], borderColor: t.grid,
        textStyle: { color: t['text-primary'], fontSize: 13 },
        formatter: (p) => {
          const m = p.data?.meta;
          if (!m) return '';
          return `<div class="phj-tt-h">${m.value} ${meta.unit} at ${fmtAgeM(m.age_months)}</div>`
            + (m.percentile != null ? `<div>${m.percentile}th centile</div>` : '<div>No reference chart for this age yet</div>')
            + (m.flag ? `<div>${GROWTH_FLAG_STYLE[m.flag].label}</div>` : (m.percentile != null ? '<div>Within expected range</div>' : ''))
            + `<div class="phj-tt-k">${m.date}${m.source === 'MANUAL' ? ' · entered by clinic' : ''}</div>`;
        },
      },
      xAxis: {
        type: 'value', min: 0, max: xMax, interval: stepM, name: data.uses_corrected_age ? 'Corrected age' : 'Age',
        nameLocation: 'middle', nameGap: 30, nameTextStyle: { color: t['text-muted'], fontSize: 13 },
        axisLabel: { color: t['text-muted'], fontSize: 13, formatter: fmtAgeM },
        axisLine: { lineStyle: { color: t.axis } }, splitLine: { lineStyle: { color: t.grid } },
      },
      yAxis: {
        type: 'value', scale: true, name: meta.unit,
        min: (v) => Math.floor(Math.min(v.min, ...curve('-3').map((p) => p[1]))),
        max: (v) => Math.ceil(Math.max(v.max, ...curve('3').map((p) => p[1]))), nameTextStyle: { color: t['text-muted'], fontSize: 13 },
        axisLabel: { color: t['text-muted'], fontSize: 13 }, splitLine: { lineStyle: { color: t.grid } },
      },
      series: [
        bands,
        { name: 'Median', type: 'line', data: curve('0'), symbol: 'none', silent: true,
          lineStyle: { color: t['band-median'], width: 1.5, type: 'dashed' }, tooltip: { show: false }, z: 2,
          endLabel: { show: true, formatter: '50th', color: t['text-muted'], fontSize: 13 } },
        { name: 'Your child', type: 'line', data: pts, symbolSize: 9, z: 5,
          lineStyle: { color: t['growth-line'], width: 2 } },
      ],
    };
  }, [data, t, meta]);

  return (
    <section className="phj-card">
      <div className="phj-row phj-between">
        <h3 className="phj-h3">Growth</h3>
        <div className="phj-seg" role="tablist" aria-label="Growth measure">
          {INDICATORS.map((i) => (
            <button key={i.key} role="tab" aria-selected={indicator === i.key}
              className={indicator === i.key ? 'on' : ''} onClick={() => setIndicator(i.key)}>{i.label}</button>
          ))}
        </div>
      </div>
      {error && <p className="phj-muted">Could not load growth data.</p>}
      {!data && !error && <div className="phj-skeleton" style={{ height: 320 }} />}
      {data && data.points.length === 0 && (
        <p className="phj-muted">No {meta.label.toLowerCase()} readings yet. They are picked up automatically from prescriptions.</p>
      )}
      {data && data.points.length > 0 && option && (
        <>
          <ReactECharts option={option} notMerge style={{ height: 340, width: '100%' }}
            onEvents={{ click: (p) => p.data?.meta?.document_id && onOpenDocument?.(p.data.meta.document_id) }} />
          <div className="phj-legend">
            <span><i className="sw" style={{ background: t['band-inner'] }} />Expected range (2nd–98th centile)</span>
            <span><i className="sw" style={{ background: t['band-outer'] }} />Outer range</span>
            <span><i className="ln" style={{ background: t['growth-line'] }} />Your child</span>
            <span><span style={{ color: t['status-serious'] }}>◆</span> Outside expected range</span>
          </div>
          <p className="phj-note">
            {data.reference_note}.{data.uses_corrected_age ? ' Born early, so age is corrected until 2 years.' : ''}
          </p>
        </>
      )}
    </section>
  );
}
