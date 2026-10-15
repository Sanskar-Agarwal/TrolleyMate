/** Placeholder blocks while a panel loads: shows the shape of what's coming. */
export default function Skeleton({ rows = 3, height = 18, label }: { rows?: number; height?: number; label: string }) {
  return (
    <div className="stack" style={{ "--gap": "10px" } as React.CSSProperties} aria-busy="true" aria-label={label}>
      <div className="skeleton" style={{ width: "42%", height: height + 10 }} />
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton" style={{ width: `${92 - i * 9}%`, height }} />
      ))}
      <span className="sr-only">{label}</span>
    </div>
  );
}
