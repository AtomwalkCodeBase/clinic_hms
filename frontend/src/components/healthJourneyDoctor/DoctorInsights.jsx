// Doctor-only detail shown under the health journey: laboratory trends with the range for the
// child's age, the medicines a hospital prescribed, and what the timeline does not know.
import React, { useEffect, useState } from 'react';
import { makePedsApi } from './api';
import { useClientPaging } from '../../hooks/usePagedApi';
import PaginationControls from '../../components/common/PaginationControls';
import { fmtDate } from './shared/format';

const TONE = { CRITICAL: 'critical', ABNORMAL: 'warning' };
const COLOR = { CRITICAL: 'var(--dhj-status-critical)', ABNORMAL: 'var(--dhj-status-serious)', NORMAL: 'var(--dhj-text-muted)' };
const ARROW = { up: '↑', down: '↓', flat: '→' };

function Spark({ points, unit }) {
  const [hover, setHover] = useState(null);
  const w = 96; const h = 28; const vals = points.map((p) => p.value);
  const min = Math.min(...vals); const max = Math.max(...vals); const span = max - min || 1;
  const xy = points.map((p, i) => [points.length === 1 ? w / 2 : 4 + (i * (w - 8)) / (points.length - 1), h - 4 - ((p.value - min) / span) * (h - 8)]);
  const shown = hover ? points[hover.i] : null;
  return (
    <span style={{ position: 'relative', display: 'inline-block' }}>
      <svg width={w} height={h} role="img" aria-label="trend" onMouseLeave={() => setHover(null)}>
        <polyline points={xy.map((p) => p.join(',')).join(' ')} fill="none" stroke="var(--dhj-axis)" strokeWidth="1.5" />
        {xy.map(([x, y], i) => (
          <g key={i} onMouseEnter={(e) => { const r = e.currentTarget.getBoundingClientRect(); setHover({ i, x: r.left + r.width / 2, y: r.top }); }} style={{ cursor: 'pointer' }}>
            <circle cx={x} cy={y} r="8" fill="transparent" />
            <circle cx={x} cy={y} r={hover?.i === i ? 4.5 : 3} fill={COLOR[points[i].severity] || COLOR.NORMAL}><title>{`${fmtDate(points[i].date)}: ${points[i].value} ${unit}`}</title></circle>
          </g>
        ))}
      </svg>
      {shown && (
        <span role="tooltip" style={{ position: 'fixed', left: hover.x, top: hover.y - 6, transform: 'translate(-50%, -100%)', whiteSpace: 'nowrap', pointerEvents: 'none', zIndex: 1000,
          background: 'var(--dhj-surface-1)', color: 'var(--dhj-text-primary)', border: '1px solid var(--dhj-border)', borderRadius: 8, padding: '5px 9px',
          fontSize: 12, boxShadow: '0 6px 18px rgba(0,0,0,.14)' }}>
          <b>{shown.value} {unit}</b>{shown.severity !== 'NORMAL' ? (shown.direction === 'LOW' ? ' · Low' : shown.direction === 'HIGH' ? ' · High' : ' · Out of range') : ''}
          <br />{fmtDate(shown.date)}
        </span>
      )}
    </span>
  );
}

function Flag({ p }) {
  if (p.severity === 'NORMAL') return null;
  return <span className={`dhj-pill dhj-pill-${TONE[p.severity] || 'warning'}`}>{p.direction === 'LOW' ? 'Low' : p.direction === 'HIGH' ? 'High' : p.severity}</span>;
}

function LabTrends({ labs, onOpenDocument }) {
  const paging = useClientPaging(labs, 5);
  if (!labs.length) return <p className="dhj-muted">No laboratory results have been read from this patient's reports.</p>;
  return (
    <div className="dhj-scroll">
      <table className="dhj-table">
        <thead><tr><th>Test</th><th>Latest</th><th>Reference (age)</th><th>Trend</th><th>History</th></tr></thead>
        <tbody>
          {paging.pageItems.map((t) => {
            const last = t.points[t.points.length - 1];
            return (
              <React.Fragment key={t.analyte}>
                <tr>
                  <td><strong>{t.label}</strong><div className="dhj-muted dhj-mono">{fmtDate(last.date)}</div></td>
                  <td className="dhj-mono"><strong>{last.value}</strong> {t.unit} <Flag p={last} /></td>
                  <td className="dhj-mono">{last.reference || '–'} {last.age_band ? <span className="dhj-muted">· {last.age_band.toLowerCase()}</span> : null}</td>
                  <td>{t.trend ? `${ARROW[t.trend]} ${t.points.length} results` : '1 result'}</td>
                  <td><Spark points={t.points} unit={t.unit} /></td>
                </tr>
                {t.points.length > 1 && (
                  <tr><td colSpan={5}>
                    <details>
                      <summary className="dhj-link">All {t.points.length} results</summary>
                      <table className="dhj-table">
                        <tbody>
                          {[...t.points].reverse().map((p, i) => (
                            <tr key={i}>
                              <td className="dhj-mono">{fmtDate(p.date)}</td>
                              <td className="dhj-mono">{p.value} {t.unit} <Flag p={p} /></td>
                              <td className="dhj-mono">{p.reference}</td>
                              <td>{p.document_id && onOpenDocument ? <button className="dhj-link" onClick={() => onOpenDocument(p.document_id)}>Report</button> : null}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </details>
                  </td></tr>
                )}
              </React.Fragment>
            );
          })}
        </tbody>
      </table>
      <PaginationControls pagination={paging.pagination} page={paging.page} pageSize={paging.pageSize} onPageChange={paging.setPage}
        onPageSizeChange={paging.setPageSize} pageSizeOptions={[5, 10, 20]} />
    </div>
  );
}

function Medicines({ rows = [], onOpenDocument }) {
  const paging = useClientPaging(rows, 10);
  if (!rows.length) return <p className="dhj-muted">No prescriptions from a hospital on file. Medicines on reports a parent uploaded are not listed here.</p>;
  return (
    <div className="dhj-scroll">
      <table className="dhj-table">
        <thead><tr><th>Date</th><th>Medicine</th><th>Dose</th><th>Frequency</th><th>Route</th><th>Days</th><th /></tr></thead>
        <tbody>
          {paging.pageItems.map((m, i) => (
            <tr key={i}>
              <td className="dhj-mono">{fmtDate(m.date)}</td><td><strong>{m.drug_name}</strong></td>
              <td className="dhj-mono">{[m.dose, m.unit].filter(Boolean).join(' ') || '–'}</td><td>{m.frequency || '–'}</td><td>{m.route || '–'}</td>
              <td className="dhj-mono">{m.duration_days ?? '–'}</td>
              <td>{m.document_id && onOpenDocument ? <button className="dhj-link" onClick={() => onOpenDocument(m.document_id)}>Prescription</button> : null}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <PaginationControls pagination={paging.pagination} page={paging.page} pageSize={paging.pageSize} onPageChange={paging.setPage}
        onPageSizeChange={paging.setPageSize} pageSizeOptions={[5, 10, 20]} />
    </div>
  );
}

export default function DoctorInsights({ http, awpid, onOpenDocument }) {
  const [api] = useState(() => makePedsApi(http));
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let live = true;
    setError(null);
    api.clinicalSummary(awpid)
      .then((s) => { if (live) setSummary(s); })
      .catch(() => live && setError('Could not load the clinical detail.'));
    return () => { live = false; };
  }, [api, awpid]);

  if (error) return <p className="dhj-callout dhj-tone-critical">{error}</p>;
  if (!summary) return <div className="dhj-skeleton" style={{ height: 160 }} />;
  return (
    <div className="dhj">
      <section className="dhj-card">
        <h3 className="dhj-h3">Laboratory investigations</h3>
        <p className="dhj-muted">Every result by test, with the range for the child's age. Out-of-range values are flagged; open a test to see each result and its report.</p>
        <LabTrends labs={summary.labs} onOpenDocument={onOpenDocument} />
      </section>
      <section className="dhj-card">
        <h3 className="dhj-h3">Medication history</h3>
        <Medicines rows={summary.medications} onOpenDocument={onOpenDocument} />
      </section>
    </div>
  );
}
