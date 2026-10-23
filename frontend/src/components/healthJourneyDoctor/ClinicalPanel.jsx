// Clinician view for the web portal. Shown by <HealthJourney view="doctor">.
// Reads the extra fields the API returns for view=doctor (ICD-10, evidence, event ids, flag ids, labs)
// and lets the clinician confirm / reject extracted diagnoses and acknowledge recurrence flags.
import React, { useMemo, useState } from 'react';
import { problemList, reviewQueue } from './shared/derive';
import { fmtDate } from './shared/format';
import { useClientPaging } from '../../hooks/usePagedApi';
import PaginationControls from '../../components/common/PaginationControls';

function useActions(api, onChanged) {
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const run = (key, fn) => {
    setBusy(key); setError(null);
    return fn().then(onChanged)
      .catch((e) => setError(e.response?.status === 403 ? 'Only clinicians can change the record.' : 'Could not save. Try again.'))
      .finally(() => setBusy(null));
  };
  return {
    busy, error,
    verify: (id) => run(`ev:${id}`, () => api.patchEvent(id, { action: 'verify', is_provisional: false })),
    reject: (id) => run(`ev:${id}`, () => api.patchEvent(id, { action: 'reject' })),
    acknowledge: (id) => run(`flag:${id}`, () => api.acknowledgeFlag(id)),
  };
}

function encounterRows(payload) {
  let rows = [];
  payload.lanes.forEach((l) => {
    const eps = l.type === 'chronic' ? [l.episode] : l.type === 'acute' ? l.episodes : [];
    eps.forEach((ep) => ep.events.forEach((e) => rows.push({ ...e, lane: l.label, category: ep.category, recurrent: !!l.is_recurrent, kind: l.type === 'chronic' ? 'Chronic' : l.is_recurrent ? 'Recurrent' : 'Acute' })));
  });
  // a chronic condition is one problem: one row, from the report that first named it
  const first = new Map();
  rows.filter((r) => r.kind === 'Chronic').sort((a, b) => a.date.localeCompare(b.date)).forEach((r) => {
    if (first.has(r.lane)) first.get(r.lane).reports += 1; else first.set(r.lane, { ...r, reports: 1 });
  });
  rows = [...rows.filter((r) => r.kind !== 'Chronic'), ...first.values()];
  return rows.sort((a, b) => b.date.localeCompare(a.date) || a.lane.localeCompare(b.lane));
}

const KIND_TONE = { Chronic: 'info', Recurrent: 'serious', Acute: 'warning' };
const KINDS = ['Chronic', 'Recurrent', 'Acute'];
// the model sometimes quotes a section heading instead of a sentence; a heading is not evidence
const HEADING = /^(final |provisional |primary |principal |discharge )?(diagnosis|diagnoses|impression)s?:?$/i;
const evidenceOf = (e) => (e.evidence && !HEADING.test(e.evidence.trim()) ? `“${e.evidence}”` : '–');
const sevClass = (s) => (s === 'CRITICAL' ? 'critical' : s === 'ABNORMAL' ? 'serious' : 'muted');

export default function ClinicalPanel({ api, payload, onChanged, onOpenDocument }) {
  const a = useActions(api, onChanged);
  const queue = reviewQueue(payload).filter((q) => q.kind !== 'flag');       // recurrence is already shown on the chart and in the problem list
  const problems = problemList(payload);
  const encounters = useMemo(() => encounterRows(payload), [payload]);
  const [kind, setKind] = useState('All');
  const counts = useMemo(() => Object.fromEntries(KINDS.map((k) => [k, encounters.filter((e) => e.kind === k).length])), [encounters]);
  const shown = kind === 'All' ? encounters : encounters.filter((e) => e.kind === kind);
  const queuePaging = useClientPaging(queue, 5);
  const dxPaging = useClientPaging(shown, 8);
  const birth = payload.lanes.find((l) => l.type === 'birth')?.items[0];
  const docs = payload.clinical?.documents;

  return (
    <div className="dhj-clin">
      <div className="dhj-clin-grid">
        {queue.length > 0 && (
          <section className="dhj-card" aria-labelledby="clin-review">
            <div className="dhj-row dhj-between"><h3 id="clin-review" className="dhj-h3">Needs review</h3>
              <span className="dhj-muted">{queue.length ? `${queue.length} open` : 'All clear'}</span></div>
            {queue.length === 0 && <p className="dhj-muted">Nothing to review. Provisional diagnoses and new recurrence flags appear here.</p>}
            {queuePaging.pageItems.map((q) => (
              <div key={q.id} className="dhj-clin-item">
                <span className={`dhj-badge ${q.kind === 'flag' ? 'serious' : 'warning'}`}>{q.kind === 'flag' ? 'RECURRENCE' : 'PROVISIONAL'}</span>
                <div className="dhj-clin-title">{q.title}</div>
                <div className="dhj-muted">{q.detail}</div>
                <div className="dhj-row">
                  {q.kind === 'provisional' ? (
                    <>
                      <button type="button" className="dhj-btn dhj-btn-good" disabled={a.busy === q.id} onClick={() => a.verify(q.eventId)}>✓ Confirm</button>
                      <button type="button" className="dhj-btn dhj-btn-danger" disabled={a.busy === q.id} onClick={() => a.reject(q.eventId)}>✕ Reject</button>
                      {q.documentId && <button type="button" className="dhj-link" onClick={() => onOpenDocument?.(q.documentId)}>Open report</button>}
                    </>
                  ) : (
                    <button type="button" className="dhj-btn" disabled={a.busy === q.id} onClick={() => a.acknowledge(q.flagId)}>✓ Acknowledge</button>
                  )}
                </div>
              </div>
            ))}
            <PaginationControls pagination={queue.length > queuePaging.pageSize ? queuePaging.pagination : null} page={queuePaging.page} pageSize={queuePaging.pageSize}
              onPageChange={queuePaging.setPage} onPageSizeChange={queuePaging.setPageSize} pageSizeOptions={[5, 10]} />
            {a.error && <p className="dhj-err" role="alert">{a.error}</p>}
          </section>
        )}

        <section className="dhj-card" aria-labelledby="clin-problems">
          <h3 id="clin-problems" className="dhj-h3">Chronic &amp; recurrent conditions</h3>
          {problems.length === 0 && <p className="dhj-muted">No chronic or recurrent conditions.</p>}
          <table className="dhj-table">
            <tbody>
              {problems.map((p) => (
                <tr key={p.laneId}>
                  <td><strong>{p.label}</strong><div className="dhj-mono">{p.codes || 'ICD –'}</div></td>
                  <td className="dhj-mono">{p.since}</td>
                  <td><span className={`dhj-badge ${p.status === 'ACTIVE' ? 'info' : p.status === 'RECURRENT' ? 'serious' : 'warning'}`}>{p.status}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
          {birth && (
            <p className="dhj-mono dhj-clin-birth">
              {[`GA ${birth.gestation_weeks ?? '?'} wk`, `BW ${birth.birth_weight_kg ?? '?'} kg`, birth.delivery,
                birth.nicu_admission ? `NICU ${birth.nicu_days ?? '?'} d` : 'No NICU', birth.preterm && 'Preterm', birth.low_birth_weight && 'LBW']
                .filter(Boolean).join(' · ')}
            </p>
          )}
          {docs && <p className="dhj-note">Reports: {docs.DONE} read · {docs.PENDING} pending · {docs.FAILED} failed</p>}
        </section>
      </div>

      <section className="dhj-card" aria-labelledby="clin-enc">
        <div className="dhj-row dhj-between">
          <h3 id="clin-enc" className="dhj-h3">Diagnosis history</h3>
          <div className="dhj-row" role="group" aria-label="Filter by type">
            {['All', ...KINDS].map((k) => (
              <button key={k} type="button" className="dhj-btn" aria-pressed={kind === k} style={kind === k ? { fontWeight: 700, outline: '2px solid currentColor' } : undefined}
                onClick={() => { setKind(k); dxPaging.setPage(1); }}>
                {k}{k === 'All' ? ` ${encounters.length}` : ` ${counts[k]}`}
              </button>
            ))}
          </div>
        </div>
        <div className="dhj-scroll">
          <table className="dhj-table">
            <thead><tr><th>Date</th><th>Age</th><th>Type</th><th>Condition</th><th>ICD-10</th><th>Source evidence</th><th>Severity</th><th /></tr></thead>
            <tbody>
              {dxPaging.pageItems.map((e, i, list) => {
                const sameDay = i > 0 && list[i - 1].date === e.date;      // one visit, several diagnoses: the date is written once
                return (
                <tr key={e.id} className={e.is_provisional ? 'dhj-row-prov' : ''} style={sameDay ? { borderTopColor: 'transparent' } : undefined}>
                  <td className="dhj-mono">{sameDay ? '' : fmtDate(e.date)}</td>
                  <td className="dhj-mono">{sameDay ? '' : e.age_label}</td>
                  <td><span className={`dhj-badge ${KIND_TONE[e.kind]}`}>{e.kind}</span></td>
                  <td>{e.text}{e.kind === 'Chronic' ? <div className="dhj-muted">Since {e.age_label}{e.reports > 1 ? ` · in ${e.reports} reports` : ''}</div> : null}</td>
                  <td className="dhj-mono">{e.icd10 || '–'}</td>
                  <td className="dhj-evidence">{evidenceOf(e)}</td>
                  <td><span className={`dhj-badge ${sevClass(e.severity)}`}>{e.severity}</span></td>
                  <td className="dhj-actions">
                    {e.document_id && <button type="button" className="dhj-link" onClick={() => onOpenDocument?.(e.document_id)}>Report</button>}
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
          <PaginationControls pagination={dxPaging.pagination} page={dxPaging.page} pageSize={dxPaging.pageSize}
            onPageChange={dxPaging.setPage} onPageSizeChange={dxPaging.setPageSize} pageSizeOptions={[5, 8, 15, 25]} />
        </div>
      </section>
    </div>
  );
}
