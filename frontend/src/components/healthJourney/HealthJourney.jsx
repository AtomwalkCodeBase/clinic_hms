// Health Journey screen for the guardian portal (also usable in the clinician view with view="doctor").
//
// `section` ('timeline' | 'growth' | 'vaccines') shows just that part, for a host page that has its own tabs.
// <HealthJourney http={axiosInstance} children={[{id, name}]} onOpenDocument={(docId) => ...} emptyAction={{label, onClick}} />
//
// `id` is the patient's awpid. deps: react >= 17, echarts 5, echarts-for-react, lucide-react
import React, { useEffect, useMemo, useState } from 'react';
import { Building2, FileUp, HeartPulse, Repeat, Stethoscope, Syringe, TrendingUp } from 'lucide-react';
import { makePedsApi } from './api';
import GrowthChart from './GrowthChart';
import ImmunizationCard from './ImmunizationCard';
import TimelineChart from './TimelineChart';
import './healthJourney.css';

const PERIODS = [
  { key: '6m', label: '6 months', months: 6 },
  { key: '1y', label: '1 year', months: 12 },
  { key: '3y', label: '3 years', months: 36 },
  { key: 'all', label: 'Since birth', months: null },
];

const iso = (d) => d.toISOString().slice(0, 10);
const monthsAgo = (n) => { const d = new Date(); d.setMonth(d.getMonth() - n); return iso(d); };

// What the reports have contributed; a lane that comes from the vaccine schedule alone says nothing about the child's history.
const REPORT_LANES = ['birth', 'growth', 'chronic', 'acute', 'hospital'];

function SummaryTiles({ s }) {
  const tiles = [
    { label: 'Ongoing conditions', value: s.chronic_conditions, Icon: HeartPulse, tone: 'info' },
    { label: 'Short illnesses', value: s.acute_episodes, Icon: Stethoscope, tone: 'muted' },
    { label: 'Happen often', value: s.recurrent_conditions, Icon: Repeat, tone: s.recurrent_conditions ? 'serious' : 'muted' },
    { label: 'Hospital stays', value: s.hospital_stays, Icon: Building2, tone: s.critical_events ? 'critical' : 'muted' },
    { label: 'Vaccines overdue', value: s.vaccines_overdue, Icon: Syringe, tone: s.vaccines_overdue ? 'critical' : 'good' },
    { label: 'Growth checks to discuss', value: s.growth_flags, Icon: TrendingUp, tone: s.growth_flags ? 'serious' : 'muted' },
  ];
  return (
    <div className="phj-tiles">
      {tiles.map(({ label, value, Icon, tone }) => (
        <div key={label} className={`phj-tile phj-tone-${tone}`}>
          <span className="phj-tile-ico"><Icon size={18} aria-hidden="true" /></span>
          <div>
            <div className="phj-tile-v">{value}</div>
            <div className="phj-tile-l">{label}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

// Accessible / printable alternative to the chart
function TimelineList({ payload }) {
  const rows = [];
  payload.lanes.forEach((l) => {
    if (l.type === 'birth') rows.push({ d: l.items[0].date, what: 'Birth', detail: [l.items[0].gestation_weeks && `${l.items[0].gestation_weeks} weeks`, l.items[0].birth_weight_kg && `${l.items[0].birth_weight_kg} kg`, l.items[0].nicu_admission && 'NICU stay'].filter(Boolean).join(' · ') });
    if (l.type === 'chronic') rows.push({ d: l.episode.start, what: l.label, detail: `Ongoing since age ${l.episode.onset_age} · ${l.episode.event_count} visit(s)` });
    if (l.type === 'acute') l.episodes.forEach((e) => rows.push({ d: e.start, what: l.label, detail: `Age ${e.onset_age}${l.is_recurrent ? ' · happens often' : ''}` }));
    if (l.type === 'hospital') l.items.forEach((h) => rows.push({ d: h.start, what: h.label, detail: h.kind === 'ADMISSION' ? `${h.ward}${h.reason ? ` · ${h.reason}` : ''}` : h.analyte }));
    if (l.type === 'growth') {
      const byDate = {};
      Object.entries(l.series).forEach(([k, pts]) => pts.forEach((p) => { (byDate[p.date] ||= []).push(`${{ weight_kg: 'Weight', height_cm: 'Height', head_circ_cm: 'Head' }[k]} ${p.value} ${k === 'weight_kg' ? 'kg' : 'cm'}`); }));
      Object.entries(byDate).forEach(([d, parts]) => rows.push({ d, what: 'Growth check', detail: parts.join(' · ') }));
    }
    if (l.type === 'immunization') {
      const byDate = {};
      l.items.filter((r) => r.status === 'GIVEN').forEach((r) => { (byDate[r.date] ||= []).push(`${r.vaccine} (dose ${r.dose})`); });
      Object.entries(byDate).forEach(([d, parts]) => rows.push({ d, what: 'Vaccines given', detail: parts.join(' · ') }));
    }
  });
  rows.sort((a, b) => b.d.localeCompare(a.d));
  return (
    <table className="phj-table">
      <thead><tr><th>Date</th><th>What</th><th>Details</th></tr></thead>
      <tbody>{rows.map((r, i) => <tr key={i}><td>{r.d}</td><td>{r.what}</td><td>{r.detail}</td></tr>)}</tbody>
    </table>
  );
}

function EmptyState({ view, emptyAction }) {
  return (
    <section className="phj-card phj-empty">
      <span className="phj-empty-ico"><FileUp size={28} aria-hidden="true" /></span>
      <h3>{view === 'doctor' ? 'No reports have been read for this patient yet' : 'Your timeline will appear here'}</h3>
      <p>
        {view === 'doctor'
          ? 'Conditions, growth readings and hospital stays are read from uploaded prescriptions, lab reports and discharge summaries.'
          : 'Upload prescriptions, lab reports or discharge summaries and the conditions, growth and hospital stays are picked up automatically.'}
      </p>
      {emptyAction && <button className="phj-btn phj-btn-primary" onClick={emptyAction.onClick}>{emptyAction.label}</button>}
    </section>
  );
}

export default function HealthJourney({
  http, children, initialChildId, initialPeriod = 'all', view = 'guardian', onOpenDocument, emptyAction, section,
}) {
  const api = useMemo(() => makePedsApi(http), [http]);
  const [childId, setChildId] = useState(initialChildId || children?.[0]?.id);
  const [period, setPeriod] = useState(initialPeriod);
  const [axisMode, setAxisMode] = useState('age');
  const [tab, setTab] = useState(section || 'timeline');
  const [showList, setShowList] = useState(false);
  const [payload, setPayload] = useState(null);
  const [error, setError] = useState(null);
  const child = children?.find((c) => c.id === childId) || children?.[0];

  useEffect(() => {
    if (!childId) return;
    let live = true;
    const p = PERIODS.find((x) => x.key === period);
    setPayload(null); setError(null);
    api.timeline(childId, { from: p.months ? monthsAgo(p.months) : undefined, to: iso(new Date()), view })
      .then((d) => live && setPayload(d))
      .catch((e) => live && setError((e.status ?? e.response?.status) === 403 ? 'You do not have access to this record.' : 'Could not load the health journey.'));
    return () => { live = false; };
  }, [api, childId, period, view]);

  const hasReportData = payload?.lanes.some((l) => REPORT_LANES.includes(l.type));

  return (
    <div className="phj">
      <header className="phj-hero">
        <div className="phj-who" style={section ? { display: 'none' } : undefined}>
          <span className="phj-avatar" aria-hidden="true">{(child?.name || '?').trim().charAt(0).toUpperCase()}</span>
          <div className="phj-who-text">
            <div className="phj-eyebrow">Health journey</div>
            {children?.length > 1 ? (
              <select value={childId} onChange={(e) => setChildId(e.target.value)} aria-label="Child" className="phj-filters">
                {children.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            ) : <h2 className="phj-h2">{child?.name}</h2>}
            {payload && (
              <div className="phj-chips">
                <span className="phj-chip">Age {payload.patient.age_label}</span>
                {payload.patient.uses_corrected_age && <span className="phj-chip">Corrected age</span>}
                {payload.pending_documents > 0 && <span className="phj-chip phj-chip-busy">{payload.pending_documents} report(s) being read</span>}
              </div>
            )}
          </div>
        </div>
        <div className="phj-seg" role="tablist" aria-label="Period">
          {PERIODS.map((p) => (
            <button key={p.key} role="tab" aria-selected={period === p.key} className={period === p.key ? 'on' : ''}
              onClick={() => setPeriod(p.key)}>{p.label}</button>
          ))}
        </div>
      </header>

      {error && <p className="phj-callout phj-tone-critical">{error}</p>}
      {!payload && !error && (
        <>
          <div className="phj-tiles">{[0, 1, 2, 3, 4, 5].map((i) => <div key={i} className="phj-skeleton" style={{ height: 70 }} />)}</div>
          <div className="phj-skeleton" style={{ height: 360 }} />
        </>
      )}

      {payload && (
        <>
          {(!section || section === 'timeline') && <SummaryTiles s={payload.summary} />}
          {payload.notes.map((n) => <p key={n} className="phj-callout">{n}</p>)}

          {!section && <div className="phj-tabs" role="tablist">
            {[['timeline', 'Timeline'], ['growth', 'Growth'], ['vaccines', 'Vaccinations']].map(([k, l]) => (
              <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{l}</button>
            ))}
          </div>}

          {tab === 'timeline' && (!hasReportData
            ? <EmptyState view={view} emptyAction={emptyAction} />
            : (
              <section className="phj-card">
                <div className="phj-card-head">
                  <div>
                    <h3 className="phj-h3">Timeline</h3>
                    <p className="phj-card-sub">Every condition, hospital stay and check-up, in one view</p>
                  </div>
                  <div className="phj-row">
                    <div className="phj-seg" aria-label="Axis">
                      <button className={axisMode === 'age' ? 'on' : ''} onClick={() => setAxisMode('age')}>By age</button>
                      <button className={axisMode === 'date' ? 'on' : ''} onClick={() => setAxisMode('date')}>By date</button>
                    </div>
                    <button className="phj-link" onClick={() => setShowList((v) => !v)}>{showList ? 'Show chart' : 'Show as list'}</button>
                  </div>
                </div>
                {showList ? <TimelineList payload={payload} />
                  : <TimelineChart payload={payload} axisMode={axisMode} onOpenDocument={onOpenDocument} />}
                <div className="phj-legend">
                  <span><i className="sw phj-c-chronic" />Ongoing condition</span>
                  <span><i className="dot phj-c-acute" />Short illness</span>
                  <span>↻ Happens often</span>
                  <span><span className="phj-c-critical-t">◆</span> Hospital care / needs attention</span>
                  <span><span className="phj-c-good-t">✓</span> Vaccine given</span>
                  <span><span className="phj-c-critical-t">✕</span> Vaccine overdue</span>
                </div>
                <p className="phj-note">Built automatically from uploaded reports. Tap any mark to open the report it came from.</p>
              </section>
            ))}
          {tab === 'growth' && <GrowthChart api={api} patientId={childId} onOpenDocument={onOpenDocument} />}
          {tab === 'vaccines' && <ImmunizationCard api={api} patientId={childId} onOpenDocument={onOpenDocument} canAdd />}
        </>
      )}
    </div>
  );
}
