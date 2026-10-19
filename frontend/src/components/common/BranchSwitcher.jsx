/** components/common/BranchSwitcher.jsx */
export default function BranchSwitcher({ branches, activeBranchId, onChange, style }) {
  if (!branches || branches.length <= 1) return null;
  return (
    <select
      value={activeBranchId ?? ""}
      onChange={e => onChange(e.target.value)}
      style={{
        padding: "6px 10px", borderRadius: 8, fontSize: 12.5, fontWeight: 600,
        border: "1.5px solid var(--color-border)", background: "var(--color-surface)",
        color: "var(--color-text)", outline: "none", cursor: "pointer",
        ...style,
      }}
      title="Switch branch"
    >
      {branches.map(b => (
        <option key={b.id} value={b.id}>{b.name}{b.is_primary ? " (primary)" : ""}</option>
      ))}
    </select>
  );
}
