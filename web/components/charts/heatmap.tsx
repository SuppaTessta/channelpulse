"use client";

import { useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { fmtNumber, formatValue } from "@/lib/format";
import { useNavigation } from "../providers";
import { cx } from "../ui";
import { ChartTooltip } from "./core";

export type HeatRow = { key: string; label: string; units: number | null };
type Cell = { r: number; c: number };

/** Colour class for a value: six equal-width bins on round thresholds (one hue, light to dark). */
const bin = (v: number, thresholds: number[]) => {
  const i = thresholds.findIndex((t) => v < t);
  return i < 0 ? thresholds.length : i;
};

export function Heatmap({
  rows,
  cols,
  cells,
  thresholds,
  title,
  valueLabel,
  activeRow,
}: {
  rows: HeatRow[];
  cols: number[];
  cells: (number | null)[][];
  thresholds: number[];
  title: string;
  valueLabel: string;
  activeRow: string | null;
}) {
  const { setParams } = useNavigation();
  const hostRef = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState<(Cell & { x: number; y: number }) | null>(null);

  const place = (cell: Cell) => {
    const host = hostRef.current;
    const el = host?.querySelector<HTMLElement>(`[data-cell="${cell.r}-${cell.c}"]`);
    if (!host || !el) return setActive(null);
    const a = host.getBoundingClientRect();
    const b = el.getBoundingClientRect();
    setActive({ ...cell, x: b.right - a.left, y: b.bottom - a.top + 4 });
  };
  const fromEvent = (e: PointerEvent<HTMLDivElement>): Cell | null => {
    const el = (e.target as HTMLElement).closest<HTMLElement>("[data-cell]");
    if (!el) return null;
    const [r, c] = el.dataset.cell!.split("-").map(Number);
    return { r, c };
  };
  const drill = (r: number) => setParams({ month: rows[r].key, lot: null, batch: null });

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const cur = active ?? { r: 0, c: 0 };
    const moves: Record<string, Cell> = {
      ArrowRight: { r: cur.r, c: Math.min(cols.length - 1, cur.c + 1) },
      ArrowLeft: { r: cur.r, c: Math.max(0, cur.c - 1) },
      ArrowDown: { r: Math.min(rows.length - 1, cur.r + 1), c: cur.c },
      ArrowUp: { r: Math.max(0, cur.r - 1), c: cur.c },
      Home: { r: cur.r, c: 0 },
      End: { r: cur.r, c: cols.length - 1 },
    };
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (active) drill(active.r);
      return;
    }
    if (e.key === "Escape") return setActive(null);
    const next = moves[e.key];
    if (!next) return;
    e.preventDefault();
    place(next);
  };

  const describe = ({ r, c }: Cell) => {
    const v = cells[r]?.[c];
    const age = `${cols[c]} month${cols[c] === 1 ? "" : "s"} since shipment`;
    return v == null
      ? `Made ${rows[r].label}, ${age}: not yet fully observed`
      : `Made ${rows[r].label}, ${age}: ${formatValue("per1000", v)} ${valueLabel}`;
  };

  const legend = [
    ...thresholds.map((t, i) => ({ label: i === 0 ? `under ${fmtNumber(t)}` : `${fmtNumber(thresholds[i - 1])} to ${fmtNumber(t)}`, color: `var(--seq-${i + 1})` })),
    { label: `${fmtNumber(thresholds.at(-1)!)} and over`, color: `var(--seq-${thresholds.length + 1})` },
  ];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted">
        <span className="font-medium text-ink">{valueLabel}</span>
        <ul className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {legend.map((l) => (
            <li key={l.label} className="flex items-center gap-1.5">
              <span aria-hidden className="h-3 w-4 rounded-[2px]" style={{ background: l.color }} />
              {l.label}
            </li>
          ))}
          <li className="flex items-center gap-1.5">
            <span aria-hidden className="h-3 w-4 rounded-[2px] border border-line-strong" />
            Not yet fully observed
          </li>
        </ul>
      </div>
      <div
        ref={hostRef}
        tabIndex={0}
        role="group"
        aria-roledescription="heatmap"
        aria-label={`${title}. ${rows.length} manufacture months by ${cols.length} months since shipment. Use the arrow keys to read cells and Enter to open that month's lots; a table view is also available.`}
        onKeyDown={onKey}
        onFocus={() => !active && place({ r: 0, c: 0 })}
        onBlur={() => setActive(null)}
        className="relative rounded-control outline-offset-4"
      >
        <div className="overflow-x-auto overscroll-x-contain pb-1">
          <div
            className="grid min-w-max gap-[2px] sm:min-w-0"
            style={{ gridTemplateColumns: `76px repeat(${cols.length}, minmax(14px, 1fr))` }}
            onPointerOver={(e) => {
              const cell = fromEvent(e);
              if (cell) place(cell);
            }}
            onPointerLeave={() => setActive(null)}
            onClick={(e) => {
              const el = (e.target as HTMLElement).closest<HTMLElement>("[data-row]");
              if (el) drill(Number(el.dataset.row));
            }}
          >
            <div className="sticky left-0 z-[1] bg-surface" />
            {cols.map((c) => (
              <div key={c} aria-hidden className="h-5 text-center text-[11px] leading-5 text-subtle">
                {c % 6 === 0 ? c : ""}
              </div>
            ))}
            {rows.map((row, r) => (
              <div key={row.key} className="contents">
                <button
                  type="button"
                  tabIndex={-1}
                  data-row={r}
                  className={cx(
                    "sticky left-0 z-[1] h-4 truncate bg-surface pr-2 text-left text-[11px] leading-4 hover:text-ink",
                    activeRow === row.key ? "font-semibold text-accent" : "text-muted",
                  )}
                >
                  {row.label}
                </button>
                {cols.map((c, ci) => {
                  const v = cells[r]?.[ci];
                  const isActive = active?.r === r && active?.c === ci;
                  return (
                    <div
                      key={c}
                      data-cell={`${r}-${ci}`}
                      data-row={r}
                      className={cx(
                        "h-4 cursor-pointer rounded-[2px]",
                        v == null && "shadow-[inset_0_0_0_1px_var(--grid)]",
                        isActive && "outline-2 outline-offset-1 outline-[var(--text)]",
                        activeRow === row.key && v != null && !isActive && "shadow-[inset_0_0_0_1px_var(--surface)]",
                      )}
                      style={v == null ? undefined : { background: `var(--seq-${bin(v, thresholds) + 1})` }}
                    />
                  );
                })}
              </div>
            ))}
          </div>
        </div>
        <p className="mt-2 pl-[78px] text-xs text-muted">Months since shipment</p>
        {active ? (
          <ChartTooltip
            x={Math.min(active.x, (hostRef.current?.clientWidth ?? 0) - 20)}
            y={active.y}
            containerWidth={hostRef.current?.clientWidth ?? 320}
            title={`Made ${rows[active.r].label}`}
            note={rows[active.r].units != null ? `${formatValue("count", rows[active.r].units)} units shipped in this cohort` : null}
            rows={[
              {
                key: "v",
                color: cells[active.r]?.[active.c] == null ? "var(--border-strong)" : `var(--seq-${bin(cells[active.r][active.c]!, thresholds) + 1})`,
                value: cells[active.r]?.[active.c] == null ? "Not yet fully observed" : formatValue("per1000", cells[active.r][active.c]),
                label: `at ${cols[active.c]} months`,
                shape: "rect",
              },
            ]}
          />
        ) : null}
        <p className="sr-only" aria-live="polite">
          {active ? describe(active) : ""}
        </p>
      </div>
    </div>
  );
}
