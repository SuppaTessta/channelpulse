"use client";

import { useState, type KeyboardEvent } from "react";
import { formatValue, type Kind } from "@/lib/format";
import { Legend, seriesColor } from "./core";
import { cx } from "../ui";

export type BarSeries = { key: string; label: string; slot: number | "deemph"; values: (number | null)[] };

/**
 * Horizontal bars in plain HTML: one row per category, every bar labelled at its tip (few categories, so every value
 * is shown and nothing hides in a tooltip). `mirrored` puts two series back to back, first to the left.
 */
export function BarList({
  rows,
  series,
  kind,
  mirrored = false,
  title,
}: {
  rows: { key: string; label: string }[];
  series: BarSeries[];
  kind: Kind;
  mirrored?: boolean;
  title: string;
}) {
  const [active, setActive] = useState<number | null>(null);
  const all = series.flatMap((s) => s.values.filter((v): v is number => v != null));
  const hi = Math.max(0, ...all.map((v) => (mirrored ? Math.abs(v) : v)));
  const lo = mirrored ? 0 : Math.min(0, ...all);
  const span = hi - lo || 1;
  const zero = (-lo / span) * 100;
  const pos = (v: number) => ((v - lo) / span) * 100;
  const describe = (i: number) => `${rows[i].label}: ${series.map((s) => `${s.label} ${formatValue(kind, s.values[i])}`).join("; ")}`;

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const n = rows.length;
    const move = { ArrowDown: (i: number) => Math.min(n - 1, i + 1), ArrowUp: (i: number) => Math.max(0, i - 1), Home: () => 0, End: () => n - 1 }[e.key];
    if (e.key === "Escape") return setActive(null);
    if (!move) return;
    e.preventDefault();
    setActive((i) => move(i ?? 0));
  };

  // Bars grow out from their zero edge, row after row, when the list first shows.
  const bar = (s: BarSeries, v: number | null, side: "left" | "right" | "auto", thick: string, row: number) => {
    const grow = { animationDelay: `${row * 50}ms` };
    if (v == null) return <div className={cx("text-xs text-subtle", thick)}>No value</div>;
    const text = formatValue(kind, v);
    if (side === "auto") {
      const start = Math.min(zero, pos(v));
      const width = Math.abs(pos(v) - zero);
      const negative = v < 0;
      return (
        <div className={cx("relative", thick)}>
          <div
            className={cx("absolute inset-y-0 animate-[cp-grow-x_700ms_var(--ease-out-expo)_both]", negative ? "origin-right rounded-l-[4px]" : "origin-left rounded-r-[4px]")}
            style={{ left: `${start}%`, width: `${width}%`, background: seriesColor(s.slot), ...grow }}
          />
          <span
            className="absolute top-1/2 -translate-y-1/2 text-xs font-semibold whitespace-nowrap text-ink"
            style={negative ? { right: `calc(${100 - start}% + 6px)` } : { left: `calc(${start + width}% + 6px)` }}
          >
            {text}
          </span>
        </div>
      );
    }
    const width = (Math.abs(v) / (hi || 1)) * 100;
    return (
      <div className={cx("relative", thick)}>
        <div
          className={cx("absolute inset-y-0 animate-[cp-grow-x_700ms_var(--ease-out-expo)_both]", side === "left" ? "right-0 origin-right rounded-l-[4px]" : "left-0 origin-left rounded-r-[4px]")}
          style={{ width: `${width}%`, background: seriesColor(s.slot), ...grow }}
        />
        <span
          className="absolute top-1/2 -translate-y-1/2 text-xs font-semibold whitespace-nowrap text-ink"
          style={side === "left" ? { right: `calc(${width}% + 6px)` } : { left: `calc(${width}% + 6px)` }}
        >
          {text}
        </span>
      </div>
    );
  };

  return (
    <div className="flex flex-col gap-3">
      {series.length > 1 ? (
        <Legend items={series.map((s) => ({ key: s.key, label: s.label, color: seriesColor(s.slot), shape: "rect" as const }))} />
      ) : null}
      <div
        tabIndex={0}
        role="group"
        aria-roledescription="chart"
        aria-label={`${title}. ${rows.length} rows. Use the up and down arrow keys to read each row; a table view is also available.`}
        onKeyDown={onKey}
        onBlur={() => setActive(null)}
        className="rounded-control outline-offset-4"
      >
        <ul className="flex flex-col">
          {rows.map((r, i) => (
            <li
              key={r.key}
              onPointerEnter={() => setActive(i)}
              onPointerLeave={() => setActive(null)}
              className={cx(
                "grid items-center gap-3 rounded-[4px] px-1 py-1.5 transition-colors duration-150",
                "grid-cols-[minmax(84px,32%)_1fr]",
                active === i && "bg-[var(--band)]",
              )}
            >
              <span className="text-[13px] text-ink max-md:leading-tight md:truncate" title={r.label}>
                {r.label}
              </span>
              {mirrored ? (
                <div className="grid grid-cols-2">
                  <div className="border-r border-[var(--axis)] pl-10 md:pl-16">{bar(series[0], series[0].values[i], "left", "h-4", i)}</div>
                  <div className="pr-10 md:pr-16">{bar(series[1], series[1].values[i], "right", "h-4", i)}</div>
                </div>
              ) : (
                <div className="flex flex-col gap-0.5 pr-20" style={lo < 0 ? { paddingLeft: "5rem" } : undefined}>
                  {series.map((s) => (
                    <div key={s.key}>{bar(s, s.values[i], "auto", series.length > 1 ? "h-3" : "h-4", i)}</div>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
        <p className="sr-only" aria-live="polite">
          {active != null ? describe(active) : ""}
        </p>
      </div>
    </div>
  );
}
