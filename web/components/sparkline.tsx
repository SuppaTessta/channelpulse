/** A trend at a glance: the line in the de-emphasis grey, the latest period as an accent dot (dataviz stat tile). */
export function Sparkline({ values, label }: { values: (number | null)[]; label: string }) {
  const points = values.flatMap((v, i) => (v == null ? [] : [{ i, v }]));
  if (points.length < 2) return <p className="text-xs text-subtle">Too few periods for a trend</p>;
  const lo = Math.min(...points.map((p) => p.v));
  const hi = Math.max(...points.map((p) => p.v));
  const x = (i: number) => (values.length === 1 ? 50 : (i / (values.length - 1)) * 100);
  const y = (v: number) => 3 + (hi === lo ? 13 : ((hi - v) / (hi - lo)) * 26);
  const d = points.map((p, k) => `${k ? "L" : "M"}${x(p.i).toFixed(2)} ${y(p.v).toFixed(2)}`).join(" ");
  const last = points.at(-1)!;
  return (
    <div role="img" aria-label={label} className="relative h-8 w-full">
      <svg viewBox="0 0 100 32" preserveAspectRatio="none" aria-hidden className="absolute inset-0 size-full overflow-visible">
        <path d={d} fill="none" stroke="var(--deemph)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      </svg>
      <span
        aria-hidden
        className="absolute size-2 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-[var(--surface)]"
        style={{ left: `${x(last.i)}%`, top: `${(y(last.v) / 32) * 100}%`, background: "var(--series-1)" }}
      />
    </div>
  );
}
