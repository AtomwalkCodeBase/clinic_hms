import { useState, useEffect } from "react";
import { RuleRow } from "./RuleRow";

/** The rule list of one schedule or template: add, edit, reorder, remove, and the payload the PATCH endpoint takes. */
export function useRules(kind, saved, resetKey) {
  const seed = () => (saved || []).map(r => ({ ...r, _key: `existing-${r.immunization_schedule_rule_id}` }));
  const [rules, setRules] = useState(seed);
  const [removedIds, setRemovedIds] = useState([]);

  useEffect(() => {
    setRules(seed());
    setRemovedIds([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-seed only when a different schedule is opened
  }, [resetKey]);

  return {
    rules,
    add: () => setRules(rs => [...rs, kind.emptyRule(rs.length ? Math.max(...rs.map(r => r.sort_order ?? 0)) + 1 : 0)]),
    update: (key, next) => setRules(rs => rs.map(r => (r._key === key ? next : r))),
    remove: (key) => setRules(rs => {
      const target = rs.find(r => r._key === key);
      if (target?.immunization_schedule_rule_id) setRemovedIds(ids => [...ids, target.immunization_schedule_rule_id]);
      return rs.filter(r => r._key !== key);
    }),
    move: (index, dir) => setRules(rs => {
      const to = index + dir;
      if (to < 0 || to >= rs.length) return rs;
      const next = [...rs];
      [next[index], next[to]] = [next[to], next[index]];
      return next.map((r, i) => ({ ...r, sort_order: i }));
    }),
    /** The first reason the rules can't be saved, or null. */
    error: () => rules.map(kind.ruleError).find(Boolean) || null,
    payload: () => [...rules.map(kind.rulePayload), ...removedIds.map(id => ({ id, _delete: true }))],
  };
}

export function RulesEditor({ kind, list }) {
  const sorted = [...list.rules].sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));
  const t = kind.text;
  return (
    <>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: 0.4 }}>
          {t.rules} ({sorted.length})
        </div>
        <button type="button" onClick={list.add}
          style={{ fontSize: 12.5, padding: "5px 12px", borderRadius: 7, border: "1.5px solid var(--color-primary)", background: "none", color: "var(--color-primary)", cursor: "pointer", fontWeight: 600 }}>
          {t.addRule}
        </button>
      </div>

      {sorted.length === 0 ? (
        <div style={{ textAlign: "center", padding: 30, color: "var(--color-text-muted)", fontSize: 13.5 }}>{t.noRules}</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 20 }}>
          {sorted.map((rule, idx) => (
            <RuleRow
              key={rule._key}
              kind={kind}
              rule={rule}
              onChange={(next) => list.update(rule._key, next)}
              onRemove={() => list.remove(rule._key)}
              onMove={(dir) => list.move(idx, dir)}
              isFirst={idx === 0}
              isLast={idx === sorted.length - 1}
            />
          ))}
        </div>
      )}
    </>
  );
}
