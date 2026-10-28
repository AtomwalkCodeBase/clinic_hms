// Health Journey screen for the guardian portal, and the clinician view with view="doctor".
//
// <HealthJourney http={axiosInstance} children={[{id, name}]} onOpenDocument={(docId) => ...} />
// <HealthJourney http={axiosInstance} children={[{id, name}]} view="doctor" />   // adds the Clinical tab
//
// deps: react >= 17, echarts 5, echarts-for-react
import React, { useEffect, useMemo, useState } from 'react';
import { makePedsApi } from './api';
import { useClientPaging } from '../../hooks/usePagedApi';
import PaginationControls from '../../components/common/PaginationControls';
import ClinicalPanel from './ClinicalPanel';
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

function SummaryTiles({ s, doctor }) {
  const tiles = doctor ? [
    { label: 'Chronic', value: s.chronic_conditions },
    { label: 'Acute episodes', value: s.acute_episodes },
    { label: 'Recurrent', value: s.recurrent_conditions, tone: s.recurrent_conditions ? 'serious' : null },
    { label: 'Admissions', value: s.hospital_stays, tone: s.hospital_stays ? 'serious' : null },
    { label: 'Critical events', value: s.critical_events, tone: s.critical_events ? 'critical' : null },
    { label: 'Vaccine coverage', value: s.vaccine_coverage_pct != null ? `${s.vaccine_coverage_pct}%` : '–', tone: s.vaccines_overdue ? 'critical' : 'good' },
  ] : [
    { label: 'Ongoing conditions', value: s.chronic_conditions },
    { label: 'Short illnesses', value: s.acute_episodes },
    { label: 'Happen often', value: s.recurrent_conditions, tone: s.recurrent_conditions ? 'serious' : null },
    { label: 'Hospital stays', value: s.hospital_stays, tone: s.critical_events ? 'critical' : null },
    { label: 'Vaccines overdue', value: s.vaccines_overdue, tone: s.vaccines_overdue ? 'critical' : 'good' },
    { label: 'Growth checks to discuss', value: s.growth_flags, tone: s.growth_flags ? 'serious' : null },
  ];
  return (
    <div className="dhj-tiles">
      {tiles.map((t) => (
        <div key={t.label} className={`dhj-tile ${t.tone ? `dhj-tone-${t.tone}` : ''}`}>
          <div className="dhj-tile-v">{t.value}</div>
          <div className="dhj-tile-l">{t.label}</div>
        </div>
      ))}
    </div>
  );
}

// Accessible / printable alternative to the chart
function TimelineList({ payload }) {
  const rows = [];
  payload.lanes.forEach((l) => {
    if (l.type === 'chronic') rows.push({ d: l.episode.start, what: l.label, detail: `Ongoing since age ${l.episode.onset_age}` });
    if (l.type === 'acute') l.episodes.forEach((e) => rows.push({ d: e.start, what: l.label, detail: `${e.onset_age}${l.is_recurrent ? ' · happens often' : ''}` }));
    if (l.type === 'hospital') l.items.forEach((h) => rows.push({ d: h.start, what: h.label, detail: h.kind === 'ADMISSION' ? `${h.ward}${h.reason ? ` · ${h.reason}` : ''}` : h.analyte }));
  });
  rows.sort((a, b) => b.d.localeCompare(a.d));
  const paging = useClientPaging(rows, 10);
  return (
    <>
      <table className="dhj-table">
        <thead><tr><th>Date</th><th>What</th><th>Details</th></tr></thead>
        <tbody>{paging.pageItems.map((r, i) => <tr key={i}><td>{r.d}</td><td>{r.what}</td><td>{r.detail}</td></tr>)}</tbody>
      </table>
      <PaginationControls pagination={paging.pagination} page={paging.page} pageSize={paging.pageSize} onPageChange={paging.setPage}
        onPageSizeChange={paging.setPageSize} pageSizeOptions={[10, 20, 50]} />
    </>
  );
}

export default function HealthJourney({ http, children, initialChildId, initialPeriod = '1y', view = 'guardian', onOpenDocument, clinicalExtra }) {
  const doctor = view === 'doctor';
  const api = useMemo(() => makePedsApi(http), [http]);
  const [childId, setChildId] = useState(initialChildId || children?.[0]?.id);
  const [period, setPeriod] = useState(initialPeriod);
  const [axisMode, setAxisMode] = useState('age');
  const [tab, setTab] = useState(doctor ? 'clinical' : 'timeline');
  const [showList, setShowList] = useState(false);
  const [payload, setPayload] = useState(null);
  const [error, setError] = useState(null);
  const [version, setVersion] = useState(0);      // bumped after a clinician confirms / rejects / acknowledges

  useEffect(() => { setPayload(null); }, [childId, period, view]);
  useEffect(() => {
    if (!childId) return undefined;
    let live = true;
    const p = PERIODS.find((x) => x.key === period);
    setError(null);
    api.timeline(childId, { from: p.months ? monthsAgo(p.months) : undefined, to: iso(new Date()), view: doctor ? 'doctor' : undefined })
      .then((d) => live && setPayload(d))
      .catch((e) => live && setError(e.response?.status === 403 ? 'You do not have access to this record.' : 'Could not load the health journey.'));
    return () => { live = false; };
  }, [api, childId, period, doctor, version]);
  const tabs = doctor
    ? [['clinical', 'Clinical'], ['timeline', 'Timeline'], ['growth', 'Growth'], ['vaccines', 'Vaccinations']]
    : [['timeline', 'Timeline'], ['growth', 'Growth'], ['vaccines', 'Vaccinations']];

  return (
    <div className="dhj">
      {/* filters: one row above the charts */}
      <div className="dhj-row dhj-between dhj-filters">
        {children?.length > 1 ? (
          <select value={childId} onChange={(e) => setChildId(e.target.value)} aria-label="Child">
            {children.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        ) : <h2 className="dhj-h2">{doctor ? `${children?.[0]?.name} · clinical timeline` : `${children?.[0]?.name}'s health journey`}</h2>}
        <div className="dhj-seg" role="tablist" aria-label="Period">
          {PERIODS.map((p) => (
            <button key={p.key} role="tab" aria-selected={period === p.key} className={period === p.key ? 'on' : ''}
              onClick={() => setPeriod(p.key)}>{p.label}</button>
          ))}
        </div>
      </div>

      {error && <p className="dhj-callout dhj-tone-critical">{error}</p>}
      {!payload && !error && <div className="dhj-skeleton" style={{ height: 420 }} />}

      {payload && (
        <>
          <p className="dhj-muted">
            Age {payload.patient.age_label}
          </p>
          <SummaryTiles s={payload.summary} doctor={doctor} />
          {payload.notes.map((n) => <p key={n} className="dhj-callout">{n}</p>)}

          <div className="dhj-tabs" role="tablist">
            {tabs.map(([k, l]) => (
              <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{l}</button>
            ))}
          </div>

          {tab === 'clinical' && doctor && (
            <>
              <ClinicalPanel api={api} payload={payload} onChanged={() => setVersion((v) => v + 1)} onOpenDocument={onOpenDocument} />
              {clinicalExtra}
            </>
          )}
          {tab === 'timeline' && (
            <section className="dhj-card">
              <div className="dhj-row dhj-between">
                <div className="dhj-seg" aria-label="Axis">
                  <button className={axisMode === 'age' ? 'on' : ''} onClick={() => setAxisMode('age')}>By age</button>
                  <button className={axisMode === 'date' ? 'on' : ''} onClick={() => setAxisMode('date')}>By date</button>
                </div>
                <button className="dhj-link" onClick={() => setShowList((v) => !v)}>{showList ? 'Show chart' : 'Show as list'}</button>
              </div>
              {payload.lanes.length === 0
                ? <p className="dhj-muted">Nothing recorded in this period.</p>
                : showList ? <TimelineList payload={payload} />
                  : <TimelineChart payload={payload} axisMode={axisMode} onOpenDocument={onOpenDocument} />}
              <div className="dhj-legend">
                <span><i className="sw dhj-c-chronic" />{doctor ? 'Chronic' : 'Ongoing condition'}</span>
                <span><i className="dot dhj-c-acute" />{doctor ? 'Acute episode' : 'Short illness'}</span>
                <span>↻ {doctor ? 'Recurrent (rule met)' : 'Happens often'}</span>
                <span><span className="dhj-c-critical-t">◆</span> {doctor ? 'Critical / admission' : 'Hospital care / needs attention'}</span>
                <span><span className="dhj-c-good-t">✓</span> Vaccine given</span>
                <span><span className="dhj-c-critical-t">✕</span> Vaccine overdue</span>
              </div>
              <p className="dhj-note">Built automatically from uploaded reports. Tap any mark to open the report it came from.</p>
            </section>
          )}
          {tab === 'growth' && <GrowthChart api={api} patientId={childId} onOpenDocument={onOpenDocument} />}
          {tab === 'vaccines' && <ImmunizationCard api={api} patientId={childId} onOpenDocument={onOpenDocument} />}
        </>
      )}
    </div>
  );
}
