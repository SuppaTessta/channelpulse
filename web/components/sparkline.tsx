import { useId } from "react";

/**
 * A trend at a glance (dataviz stat tile): the line wipes in left to right over a soft fill, then the latest period
 * lands. A wipe, not a dash draw: the stroke doesn't scale with the stretched viewBox, and dashes on a non-scaling
 * stroke are measured on screen, so a pathLength dash left gaps in the line.
 */
export function Sparkline({ values, label, index = 0 }: { values: (number | null)[]; label: string; index?: number }) {
  const gid = useId().replace(/:/g, "");
  const points = values.flatMap((v, i) => (v == null ? [] : [{ i, v }]));
  if (points.length < 2) return <p className="text-xs text-subtle">Too few periods for a trend</p>;
  const lo = Math.min(...points.map((p) => p.v));
  const hi = Math.max(...points.map((p) => p.v));
  const x = (i: number) => (values.length === 1 ? 50 : (i / (values.length - 1)) * 100);
  const y = (v: number) => 3 + (hi === lo ? 13 : ((hi - v) / (hi - lo)) * 26);
  const d = points.map((p, k) => `${k ? "L" : "M"}${x(p.i).toFixed(2)} ${y(p.v).toFixed(2)}`).join(" ");
  const last = points.at(-1)!;
  return (
    <div role="img" aria-label={label} className="relative h-9 w-full">
      <svg viewBox="0 0 100 32" preserveAspectRatio="none" aria-hidden className="cp-spark absolute inset-0 size-full overflow-visible" style={{ ["--i" as string]: index }}>
        <defs>
          <linearGradient id={`spark-${gid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="var(--series-1)" stopOpacity="0.22" />
            <stop offset="1" stopColor="var(--series-1)" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={`${d} L${x(last.i).toFixed(2)} 32 L${x(points[0].i).toFixed(2)} 32 Z`} fill={`url(#spark-${gid})`} className="cp-spark-area" />
        <path
          d={d}
          fill="none"
          stroke="var(--series-1)"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
          className="cp-spark-line"
        />
      </svg>
      <span
        aria-hidden
        className="cp-spark-dot cp-pulse absolute size-2 -translate-x-1/2 -translate-y-1/2 rounded-full"
        style={{ left: `${x(last.i)}%`, top: `${(y(last.v) / 32) * 100}%`, background: "var(--series-1)", ["--i" as string]: index }}
      />
    </div>
  );
}
