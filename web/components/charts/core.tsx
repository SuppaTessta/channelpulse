"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

type PlotModule = typeof import("@observablehq/plot");
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

/** A zero-based domain widened to round ticks. Whole-number measures (counts) never get fractional ticks. */
export function niceScale(values: number[], count = 4, fixed?: [number, number], integer = false): { domain: [number, number]; ticks: number[] } {
  if (fixed) {
    const step = tickIncrement(fixed[0], fixed[1], count);
    const ticks: number[] = [];
    for (let t = fixed[0]; t <= fixed[1] + step / 1e6; t += step) ticks.push(+t.toFixed(10));
    return { domain: fixed, ticks };
  }
  let lo = Math.min(0, ...values);
  let hi = Math.max(0, ...values);
  if (lo === hi) hi = lo + 1;
  const step = integer ? Math.max(1, tickIncrement(lo, hi, count)) : tickIncrement(lo, hi, count);
  lo = Math.floor(lo / step) * step;
  hi = Math.ceil(hi / step) * step;
  const ticks: number[] = [];
  for (let t = lo; t <= hi + step / 1e6; t += step) ticks.push(+t.toFixed(10));
  return { domain: [lo, hi], ticks };
}

/** Line groups take their series colour as currentColor, so the dark edition's glow matches each line. */
export function decorate(svg: SVGSVGElement) {
  svg.querySelectorAll<SVGGElement>('g[aria-label="line"]').forEach((g) => {
    const stroke = g.getAttribute("stroke");
    if (stroke) g.style.color = stroke;
  });
}

// Plot labels each mark's group by its type, so bars and the provisional band are both "rect": the band is the one
// filled with the hatch pattern. globals.css uses the same two selectors.
const BARS = 'g[aria-label="rect"]:not([fill^="url("])';

/**
 * Draw-in for a chart whose data just changed (DESIGN.md motion): lines trace in, bars grow from the baseline in
 * sequence, dots and labels fade in. Callers skip it on a resize redraw. Nothing runs under reduced motion.
 */
export function animateEnter(svg: SVGSVGElement) {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  // Solid lines only: a pathLength of 1 would stretch a dashed line's dash over its whole length.
  svg.querySelectorAll<SVGPathElement>('g[aria-label="line"]:not([stroke-dasharray]) path').forEach((p) => p.setAttribute("pathLength", "1"));
  svg.querySelectorAll<SVGGElement>(BARS).forEach((g) =>
    // Rounded bars come out of Plot as paths, square ones as rects: every child is a bar.
    [...g.children].forEach((bar, i) => (bar as SVGElement).style.setProperty("--i", String(i))),
  );
  svg.classList.add("cp-enter");
}

/** An area gradient and a provisional hatch, defined inside one chart's SVG; returns their fill references. */
export function chartDefs(svg: SVGSVGElement, id: string) {
  const ns = "http://www.w3.org/2000/svg";
  const defs = document.createElementNS(ns, "defs");
  defs.innerHTML =
    `<linearGradient id="${id}-area" x1="0" y1="0" x2="0" y2="1">` +
    `<stop offset="0" stop-color="var(--series-1)" stop-opacity="0.28"/><stop offset="1" stop-color="var(--series-1)" stop-opacity="0"/>` +
    `</linearGradient>` +
    `<pattern id="${id}-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">` +
    `<rect width="6" height="6" fill="var(--band)"/><line x1="0" y1="0" x2="0" y2="6" stroke="var(--marigold)" stroke-opacity="0.35" stroke-width="1.5"/>` +
    `</pattern>`;
  svg.prepend(defs);
  return { area: `url(#${id}-area)`, hatch: `url(#${id}-hatch)` };
}

/** The provisional hatch as CSS, for the legend swatch beside a chart that draws it in SVG. */
export const HATCH_CSS = "repeating-linear-gradient(135deg, color-mix(in oklab, var(--marigold) 35%, var(--band)) 0 1.5px, var(--band) 1.5px 4.2px)";

/** Pixel width of a tick label in 12px Plus Jakarta Sans, near enough to size the margin that holds it. */
export const labelWidth = (text: string) => Math.ceil(text.length * 7.1);

/** Measures the container and re-renders on resize; charts redraw at the real width, never a scaled SVG. */
export function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // Measure now rather than waiting for the observer's first callback, which only runs once a frame is painted.
    setWidth(Math.floor(el.getBoundingClientRect().width));
    const ro = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

type TooltipRow = { key: string; color: string; value: string; label: string; shape?: "line" | "rect"; muted?: boolean };

/** Values lead, series names follow, each keyed by a short stroke of its colour (dataviz interaction spec). */
export function ChartTooltip({ x, y, containerWidth, title, note, rows }: { x: number; y: number; containerWidth: number; title: string; note?: string | null; rows: TooltipRow[] }) {
  const width = Math.min(260, containerWidth - 8);
  const left = x + 14 + width > containerWidth ? Math.max(4, x - 14 - width) : x + 14;
  return (
    <div
      className="pointer-events-none absolute z-10 rounded-panel border border-line-strong/70 bg-raised/90 shadow-raised backdrop-blur-xl px-3 py-2 text-[13px]/5"
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
            <span aria-hidden className="h-3 w-4 rounded-[2px] border border-line" style={{ background: HATCH_CSS }} />
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
