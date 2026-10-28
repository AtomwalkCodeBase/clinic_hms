// Vaccination card grouped by due age, IAP schedule. Status always icon + text, never colour alone.
import React, { useEffect, useMemo, useState } from 'react';
import { useClientPaging } from '../../hooks/usePagedApi';
import PaginationControls from '../../components/common/PaginationControls';
import { VACCINE_STYLE } from './theme';

export default function ImmunizationCard({ api, patientId, canAdd = true, onOpenDocument }) {
  const [data, setData] = useState(null);
  const [form, setForm] = useState(null);
  const [msg, setMsg] = useState('');

  const load = () => api.immunization(patientId).then(setData);
  useEffect(() => { load(); }, [patientId]); // eslint-disable-line react-hooks/exhaustive-deps

  const groups = useMemo(() => {
    if (!data) return [];
    const g = {};
    data.rows.forEach((r) => { (g[r.due_age] ||= { due_age: r.due_age, due_on: r.due_on, rows: [] }).rows.push(r); });
    return Object.values(g).sort((a, b) => a.due_on.localeCompare(b.due_on));
  }, [data]);
  const paging = useClientPaging(groups, 6);

  if (!data) return <section className="dhj-card"><div className="dhj-skeleton" style={{ height: 240 }} /></section>;
  const s = data.summary;

  const submit = async (e) => {
    e.preventDefault();
    try {
      await api.addVaccine(patientId, form);
      setForm(null); setMsg('Saved'); load();
    } catch (err) {
      setMsg(err.response?.data?.vaccine_text?.[0] || err.response?.data?.given_on?.[0] || 'Could not save');
    }
  };

  return (
    <section className="dhj-card">
      <div className="dhj-row dhj-between">
        <h3 className="dhj-h3">Vaccinations</h3>
        {canAdd && !form && <button className="dhj-btn" onClick={() => setForm({ vaccine_text: '', given_on: '' })}>Add a vaccine</button>}
      </div>

      <div className="dhj-row dhj-gap">
        <span className="dhj-pill">{VACCINE_STYLE.GIVEN.icon} {s.given} given</span>
        {s.overdue > 0 && <span className="dhj-pill dhj-pill-critical">{VACCINE_STYLE.OVERDUE.icon} {s.overdue} overdue</span>}
        {s.due > 0 && <span className="dhj-pill dhj-pill-warning">! {s.due} due now</span>}
        {s.coverage_pct != null && <span className="dhj-muted">{s.coverage_pct}% of doses due so far are recorded</span>}
      </div>
      {data.next_due && (
        <p className="dhj-callout">
          Next: <strong>{data.next_due.vaccine} dose {data.next_due.dose}</strong> — {data.next_due.status_label.toLowerCase()} (due {data.next_due.due_on})
        </p>
      )}

      {form && (
        <form className="dhj-form" onSubmit={submit}>
          <input required placeholder="Vaccine as written on the card, e.g. Hexaxim 2"
            value={form.vaccine_text} onChange={(e) => setForm({ ...form, vaccine_text: e.target.value })} />
          <input required type="date" max={new Date().toISOString().slice(0, 10)}
            value={form.given_on} onChange={(e) => setForm({ ...form, given_on: e.target.value })} />
          <button className="dhj-btn dhj-btn-primary" type="submit">Save</button>
          <button className="dhj-btn" type="button" onClick={() => setForm(null)}>Cancel</button>
        </form>
      )}
      {msg && <p className="dhj-muted" role="status">{msg}</p>}

      <table className="dhj-table">
        <thead><tr><th>Age</th><th>Vaccine</th><th>Status</th><th>Date</th></tr></thead>
        <tbody>
          {paging.pageItems.map((g) => g.rows.map((r, idx) => {
            const st = VACCINE_STYLE[r.status] || VACCINE_STYLE.SCHEDULED;
            return (
              <tr key={r.code}>
                {idx === 0 && <td rowSpan={g.rows.length} className="dhj-age">{g.due_age}</td>}
                <td>{r.vaccine} <span className="dhj-muted">· dose {r.dose}</span></td>
                <td><span className="dhj-status"><span className={`dhj-ico dhj-ico-${r.status.toLowerCase()}`} aria-hidden="true">{st.icon}</span> {r.status_label}</span>
                  {r.late && <span className="dhj-muted"> · late</span>}</td>
                <td>{r.given_on
                  ? (r.document_id ? <button className="dhj-link" onClick={() => onOpenDocument?.(r.document_id)}>{r.given_on}</button> : r.given_on)
                  : <span className="dhj-muted">due {r.due_on}</span>}</td>
              </tr>
            );
          }))}
        </tbody>
      </table>
      <PaginationControls pagination={paging.pagination} page={paging.page} pageSize={paging.pageSize} onPageChange={paging.setPage}
        onPageSizeChange={paging.setPageSize} pageSizeOptions={[4, 6, 10, 20]} />
      {data.unresolved.length > 0 && (
        <p className="dhj-note">{data.unresolved.length} vaccine entr{data.unresolved.length > 1 ? 'ies' : 'y'} from uploaded cards could not be read and will be checked by the clinic.</p>
      )}
      <p className="dhj-note">Schedule: {data.source}. Your doctor may advise a different timing.</p>
    </section>
  );
}
