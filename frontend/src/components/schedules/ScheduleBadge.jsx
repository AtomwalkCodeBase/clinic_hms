export function ScheduleBadge({ children, tone = "primary" }) {
  const tones = {
    primary: { background: "var(--color-primary-light, var(--color-bg))", color: "var(--color-primary)", border: "1px solid var(--color-primary)" },
    muted:   { background: "var(--color-bg)", color: "var(--color-text-muted)", border: "1px solid var(--color-border)" },
  };
  return (
    <span style={{
      fontSize: 11, fontWeight: 700, padding: "2px 10px", borderRadius: 20,
      letterSpacing: 0.3, ...tones[tone],
    }}>{children}</span>
  );
}
