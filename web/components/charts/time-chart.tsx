"use client";

import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { formatTick, formatValue, type Kind } from "@/lib/format";
import { ChartTooltip, labelWidth, Legend, loadPlot, niceScale, seriesColor, useWidth, type LegendItem } from "./core";

export type Bucket = {
  start: string;
  end: string;
  /** Tooltip and table heading: "Sep 2026", "Week of 15 Sep 2026". */
  label: string;
  tick: string;
  tickYear: string;
  year: string;
  /** Why the bucket holds less than a full period, e.g. "Data to 23 Sep", or null. */
  partial: string | null;
  /** Overlaps sale dates the warehouse has not settled yet. */
  provisional: boolean;
};
export type ChartSeries = { key: string; label: string; slot: number | "deemph"; values: (number | null)[]; horizonBound: boolean };

type Geometry = { xs: number[]; y: (v: number) => number; top: number; bottom: number; left: number; right: number; step: number };

const MARGIN_BOTTOM = 28;

/** Partial periods, and provisional ones for metrics built on sell-out, draw lighter or dashed. */
const isDim = (b: Bucket, s: ChartSeries) => !!b.partial || (s.horizonBound && b.provisional);

export function TimeChart({
  buckets,
  series,
  mark,
  barMode = "grouped",
  kind,
  yDomain,
  height = 240,
  title,
  grain,
  endLabels = true,
  refLine,
}: {
  buckets: Bucket[];
  series: ChartSeries[];
  mark: "line" | "bar";
  barMode?: "grouped" | "overlay";
  kind: Kind;
  yDomain?: [number, number];
  height?: number;
  title: string;
  grain: string;
  endLabels?: boolean;
  /** A labelled threshold, such as the at-risk score. Drawn in the danger colour with its label, never colour alone. */
  refLine?: { value: number; label: string };
}) {
  const [hostRef, width] = useWidth<HTMLDivElement>();
  const plotRef = useRef<HTMLDivElement>(null);
  const [geom, setGeom] = useState<Geometry | null>(null);
  const [active, setActive] = useState<number | null>(null);
  const n = buckets.length;
  const firstProvisional = series.some((s) => s.horizonBound) ? buckets.findIndex((b) => b.provisional) : -1;
  const dim = (i: number, s: ChartSeries) => isDim(buckets[i], s);

  useEffect(() => {
    if (!width || !n) return;
    let cancelled = false;
    loadPlot().then((Plot) => {
      const host = plotRef.current;
      if (cancelled || !host) return;
      const values = series.flatMap((s) => s.values.filter((v): v is number => v != null));
      const { domain, ticks } = niceScale(values, height < 180 ? 3 : 4, yDomain);
      const marginLeft = Math.max(...ticks.map((t) => labelWidth(formatTick(kind, t)))) + 12;
      const marginTop = firstProvisional >= 0 ? 22 : 10;
      const plotH = height - marginTop - MARGIN_BOTTOM;
      const y = (v: number) => marginTop + ((domain[1] - v) / (domain[1] - domain[0])) * plotH;

      // Direct end labels for lines, unless two of them would collide (then the legend and tooltip carry it).
      const ends = series.map((s) => {
        let i = s.values.length - 1;
        while (i >= 0 && s.values[i] == null) i--;
        return i >= 0 ? { i, v: s.values[i] as number, text: formatValue(kind, s.values[i]) } : null;
      });
      const endYs = ends.filter(Boolean).map((e) => y(e!.v));
      const collide = endYs.some((a, i) => endYs.some((b, j) => i !== j && Math.abs(a - b) < 16));
      const showEnds = mark === "line" && endLabels && series.length <= 3 && !collide;
      const marginRight = showEnds ? Math.max(...ends.map((e) => (e ? labelWidth(e.text) : 0))) + 16 : 14;
      const plotW = Math.max(40, width - marginLeft - marginRight);
      const step = plotW / n;

      const tickWidth = Math.max(...buckets.map((b) => labelWidth(b.tickYear))) + 16;
      const every = Math.ceil(n / Math.max(1, Math.floor(plotW / tickWidth)));
      const tickIdx: number[] = [];
      for (let i = n - 1; i >= 0; i -= every) tickIdx.unshift(i);
      const tickText = new Map<number, string>();
      tickIdx.forEach((i, k) => tickText.set(i, k === 0 || buckets[i].year !== buckets[tickIdx[k - 1]].year ? buckets[i].tickYear : buckets[i].tick));

      const marks: import("@observablehq/plot").Markish[] = [];
      if (firstProvisional >= 0) {
        marks.push(Plot.rect([{ x1: firstProvisional - 0.5, x2: n - 0.5 }], { x1: "x1", x2: "x2", fill: "var(--band)" }));
        marks.push(
          Plot.text([{ x: n - 0.5 }], {
            x: "x",
            text: () => "Provisional",
            frameAnchor: "top",
            textAnchor: "end",
            dy: -14,
            fill: "var(--text-subtle)",
            fontSize: 11,
          }),
        );
      }
      marks.push(Plot.gridY(ticks, { stroke: "var(--grid)", strokeOpacity: 1 }));
      marks.push(Plot.axisY(ticks, { tickFormat: (d: number) => formatTick(kind, d), tickSize: 0, tickPadding: 8, fill: "var(--text-subtle)", fontSize: 12 }));
      marks.push(Plot.axisX(tickIdx, { tickFormat: (i: number) => tickText.get(i) ?? "", tickSize: 0, tickPadding: 10, fill: "var(--text-subtle)", fontSize: 12 }));

      if (mark === "bar") {
        const gap = 2;
        const count = barMode === "overlay" ? 1 : series.length;
        const group = Math.min(step * 0.72, count * 24 + (count - 1) * gap);
        const bar = barMode === "overlay" ? group : (group - (count - 1) * gap) / count;
        series.forEach((s, k) => {
          const offset = barMode === "overlay" ? -group / 2 : -group / 2 + k * (bar + gap);
          const rows = s.values.flatMap((v, i) =>
            v == null ? [] : [{ x1: i + offset / step, x2: i + (offset + bar) / step, y1: 0, y2: v, dim: isDim(buckets[i], s) }],
          );
          marks.push(
            Plot.rect(rows, {
              x1: "x1",
              x2: "x2",
              y1: "y1",
              y2: "y2",
              fill: seriesColor(s.slot),
              fillOpacity: (d: { dim: boolean }) => (d.dim ? 0.42 : 1),
              ry2: Math.min(4, bar / 2),
            }),
          );
        });
      } else {
        series.forEach((s, k) => {
          const stroke = seriesColor(s.slot);
          const points = s.values.map((v, i) => ({ i, v }));
          const dashFrom = points.findIndex((p) => isDim(buckets[p.i], s));
          const solid = dashFrom < 0 ? points : points.slice(0, Math.max(0, dashFrom));
          const dashed = dashFrom < 0 ? [] : points.slice(Math.max(0, dashFrom - 1));
          const line = { x: "i", y: "v", stroke, strokeWidth: 2, strokeLinejoin: "round", strokeLinecap: "round" } as const;
          if (solid.length) marks.push(Plot.line(solid, line));
          if (dashed.length) marks.push(Plot.line(dashed, { ...line, strokeDasharray: "4 3" }));
          const end = ends[k];
          if (end) {
            marks.push(Plot.dot([end], { x: "i", y: "v", r: 4, fill: stroke, stroke: "var(--surface)", strokeWidth: 2 }));
            if (showEnds) {
              marks.push(Plot.text([end], { x: "i", y: "v", text: "text", dx: 9, textAnchor: "start", fill: "var(--text)", fontSize: 12, fontWeight: 600 }));
            }
          }
        });
      }
      marks.push(Plot.ruleY([domain[0] < 0 ? 0 : domain[0]], { stroke: "var(--axis)" }));
      if (refLine && refLine.value >= domain[0] && refLine.value <= domain[1]) {
        marks.push(Plot.ruleY([refLine.value], { stroke: "var(--danger)", strokeOpacity: 0.7 }));
        marks.push(
          Plot.text([refLine], { x: () => -0.5, y: "value", text: "label", dy: -7, textAnchor: "start", fill: "var(--danger)", fontSize: 11 }),
        );
      }

      const svg = Plot.plot({
        width,
        height,
        marginLeft,
        marginRight,
        marginTop,
        marginBottom: MARGIN_BOTTOM,
        x: { type: "linear", domain: [-0.5, n - 0.5], axis: null },
        y: { domain, axis: null },
        marks,
      });
      svg.setAttribute("aria-hidden", "true");
      host.replaceChildren(svg);
      setGeom({
        xs: buckets.map((_, i) => marginLeft + (i + 0.5) * step),
        y,
        top: marginTop,
        bottom: height - MARGIN_BOTTOM,
        left: marginLeft,
        right: marginLeft + plotW,
        step,
      });
    });
    return () => {
      cancelled = true;
    };
  }, [width, n, buckets, series, mark, barMode, kind, yDomain, height, endLabels, firstProvisional, refLine]);

  const pick = (e: PointerEvent<HTMLDivElement>) => {
    if (!geom) return;
    const x = e.clientX - e.currentTarget.getBoundingClientRect().left;
    setActive(Math.max(0, Math.min(n - 1, Math.floor(x / geom.step))));
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const moves: Record<string, (i: number) => number> = {
      ArrowRight: (i) => Math.min(n - 1, i + 1),
      ArrowLeft: (i) => Math.max(0, i - 1),
      Home: () => 0,
      End: () => n - 1,
    };
    if (e.key === "Escape") return setActive(null);
    const move = moves[e.key];
    if (!move) return;
    e.preventDefault();
    setActive((i) => move(i ?? n - 1));
  };

  const describe = (i: number) =>
    `${buckets[i].label}${buckets[i].partial ? ` (${buckets[i].partial})` : ""}: ` +
    series.map((s) => `${s.label} ${formatValue(kind, s.values[i])}${dim(i, s) && buckets[i].provisional && s.horizonBound ? ", provisional" : ""}`).join("; ");
  const last = n - 1;
  const aria = n
    ? `${title}. ${n} ${grain}${n === 1 ? "" : "s"}, ${buckets[0].label} to ${buckets[last].label}. Latest, ${describe(last)}. Use the arrow keys to read each ${grain}; a table view is also available.`
    : title;

  const legend: LegendItem[] = [
    ...(series.length > 1 ? series.map((s) => ({ key: s.key, label: s.label, color: seriesColor(s.slot), shape: mark === "bar" ? ("rect" as const) : ("line" as const) })) : []),
    ...(firstProvisional >= 0 ? [{ key: "band", label: "Provisional: sell-out still arriving", color: "var(--band)", shape: "band" as const }] : []),
  ];
  const partials = buckets.filter((b) => b.partial);

  return (
    <div className="flex flex-col gap-2">
      <Legend items={legend} />
      <div
        ref={hostRef}
        tabIndex={0}
        role="group"
        aria-roledescription="chart"
        aria-label={aria}
        onKeyDown={onKey}
        onFocus={() => setActive((i) => i ?? last)}
        onBlur={() => setActive(null)}
        className="relative rounded-control outline-offset-4"
        style={{ height }}
      >
        {geom && active != null && mark === "bar" ? (
          <div aria-hidden className="absolute rounded-[4px] bg-[var(--band)]" style={{ left: geom.xs[active] - geom.step / 2, width: geom.step, top: geom.top, height: geom.bottom - geom.top }} />
        ) : null}
        <div ref={plotRef} className="cp-plot relative" />
        {geom ? (
          <div
            aria-hidden
            className="absolute touch-pan-y"
            style={{ left: geom.left, top: geom.top, width: geom.right - geom.left, height: geom.bottom - geom.top }}
            onPointerMove={pick}
            onPointerDown={pick}
            onPointerLeave={() => setActive(null)}
          />
        ) : null}
        {geom && active != null ? (
          <>
            {mark === "line" ? (
              <>
                <div aria-hidden className="pointer-events-none absolute w-px bg-[var(--axis)]" style={{ left: geom.xs[active], top: geom.top, height: geom.bottom - geom.top }} />
                {series.map((s) =>
                  s.values[active] == null ? null : (
                    <span
                      key={s.key}
                      aria-hidden
                      className="pointer-events-none absolute size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[var(--surface)]"
                      style={{ left: geom.xs[active], top: geom.y(s.values[active] as number), background: seriesColor(s.slot) }}
                    />
                  ),
                )}
              </>
            ) : null}
            <ChartTooltip
              x={geom.xs[active]}
              y={geom.top}
              containerWidth={width}
              title={buckets[active].label}
              note={buckets[active].partial ?? (firstProvisional >= 0 && buckets[active].provisional ? "Provisional: sell-out still arriving" : null)}
              rows={series.map((s) => ({
                key: s.key,
                color: seriesColor(s.slot),
                value: formatValue(kind, s.values[active]),
                label: s.label,
                shape: mark === "bar" ? "rect" : "line",
                muted: dim(active, s),
              }))}
            />
          </>
        ) : null}
        <p className="sr-only" aria-live="polite">
          {active != null ? describe(active) : ""}
        </p>
      </div>
      {partials.length ? (
        <p className="text-xs text-subtle">
          {mark === "bar" ? "Lighter bars" : "Dashed line"}: {partials.map((b) => `${b.label}, ${b.partial?.toLowerCase()}`).join("; ")}.
        </p>
      ) : null}
    </div>
  );
}
