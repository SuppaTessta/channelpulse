"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

export type PlotModule = typeof import("@observablehq/plot");
let plotModule: Promise<PlotModule> | null = null;
/** Plot is loaded on demand, so pages hydrate before the chart library arrives. */
export const loadPlot = () => (plotModule ??= import("@observablehq/plot"));

/** Series colour for a categorical slot (1-8, validated order) or the de-emphasis grey. */
export const seriesColor = (slot: number | "deemph") => (slot === "deemph" ? "var(--deemph)" : `var(--series-${slot})`);

// d3-array's tick increment, so y ticks land on round numbers (0 / 10 cr / 20 cr).
function tickIncrement(start: number, stop: number, count: number): number {
  const step = (stop - start) / Math.max(1, count);
  const power = Math.floor(Math.log10(step));
  const error = step / 10 ** power;
  const factor = error >= Math.sqrt(50) ? 10 : error >= Math.sqrt(10) ? 5 : error >= Math.sqrt(2) ? 2 : 1;
  return factor * 10 ** power;
}

/** A zero-based domain widened to round ticks. */
export function niceScale(values: number[], count = 4, fixed?: [number, number]): { domain: [number, number]; ticks: number[] } {
  if (fixed) {
    const step = tickIncrement(fixed[0], fixed[1], count);
    const ticks: number[] = [];
    for (let t = fixed[0]; t <= fixed[1] + step / 1e6; t += step) ticks.push(+t.toFixed(10));
    return { domain: fixed, ticks };
  }
  let lo = Math.min(0, ...values);
  let hi = Math.max(0, ...values);
  if (lo === hi) hi = lo + 1;
  const step = tickIncrement(lo, hi, count);
  lo = Math.floor(lo / step) * step;
  hi = Math.ceil(hi / step) * step;
  const ticks: number[] = [];
  for (let t = lo; t <= hi + step / 1e6; t += step) ticks.push(+t.toFixed(10));
  return { domain: [lo, hi], ticks };
}

/** Pixel width of a tick label in 12px Geist, near enough to size the margin that holds it. */
export const labelWidth = (text: string) => Math.ceil(text.length * 7.1);

/** Measures the container and re-renders on resize; charts redraw at the real width, never a scaled SVG. */
export function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

export type TooltipRow = { key: string; color: string; value: string; label: string; shape?: "line" | "rect"; muted?: boolean };

/** Values lead, series names follow, each keyed by a short stroke of its colour (dataviz interaction spec). */
export function ChartTooltip({ x, y, containerWidth, title, note, rows }: { x: number; y: number; containerWidth: number; title: string; note?: string | null; rows: TooltipRow[] }) {
  const width = Math.min(260, containerWidth - 8);
  const left = x + 14 + width > containerWidth ? Math.max(4, x - 14 - width) : x + 14;
  return (
    <div
      className="pointer-events-none absolute z-10 rounded-control border border-line bg-raised px-3 py-2 text-[13px]/5 shadow-raised"
      style={{ left, top: Math.max(0, y), width }}
    >
      <p className="font-medium text-ink">{title}</p>
      {note ? <p className="text-xs text-muted">{note}</p> : null}
      <ul className="mt-1.5 space-y-1">
        {rows.map((r) => (
          <li key={r.key} className="flex items-center gap-2">
            <span
              aria-hidden
              className={r.shape === "rect" ? "size-2.5 shrink-0 rounded-[2px]" : "h-0.5 w-3 shrink-0 rounded-full"}
              style={{ background: r.color }}
            />
            <span className={r.muted ? "font-semibold text-muted" : "font-semibold text-ink"}>{r.value}</span>
            <span className="truncate text-muted">{r.label}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export type LegendItem = { key: string; label: string; color: string; shape: "line" | "rect" | "band" | "dashed" };

/** Always present for two or more series, and for the provisional band. Text wears ink, never the series colour. */
export function Legend({ items, children }: { items: LegendItem[]; children?: ReactNode }) {
  if (!items.length && !children) return null;
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
      {items.map((i) => (
        <li key={i.key} className="flex items-center gap-1.5">
          {i.shape === "rect" ? (
            <span aria-hidden className="size-2.5 rounded-[2px]" style={{ background: i.color }} />
          ) : i.shape === "band" ? (
            <span aria-hidden className="h-3 w-4 rounded-[2px] border border-line" style={{ background: i.color }} />
          ) : i.shape === "dashed" ? (
            <span aria-hidden className="w-4 border-t-2 border-dashed" style={{ borderColor: i.color }} />
          ) : (
            <span aria-hidden className="h-0.5 w-4 rounded-full" style={{ background: i.color }} />
          )}
          {i.label}
        </li>
      ))}
      {children}
    </ul>
  );
}
