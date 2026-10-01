import type { Range } from "./dates";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MINUS = "−";

const parts = (iso: string) => ({ y: iso.slice(0, 4), m: MONTHS[+iso.slice(5, 7) - 1], d: String(+iso.slice(8, 10)) });

export const fmtDate = (iso: string) => {
  const { y, m, d } = parts(iso);
  return `${d} ${m} ${y}`;
};
export const fmtDayMonth = (iso: string) => {
  const { m, d } = parts(iso);
  return `${d} ${m}`;
};
export const fmtMonth = (iso: string) => {
  const { y, m } = parts(iso);
  return `${m} ${y}`;
};
export const fmtMonthShort = (iso: string) => parts(iso).m;

export function fmtRange({ from, to }: Range): string {
  if (from === to) return fmtDate(to);
  return from.slice(0, 4) === to.slice(0, 4) ? `${fmtDayMonth(from)} to ${fmtDate(to)}` : `${fmtDate(from)} to ${fmtDate(to)}`;
}

const formatters = new Map<number, Intl.NumberFormat>();
export function fmtNumber(value: number, digits = 0): string {
  let f = formatters.get(digits);
  if (!f) {
    f = new Intl.NumberFormat("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
    formatters.set(digits, f);
  }
  return f.format(value).replace("-", MINUS);
}

/** How a metric's values read. Inferred from the governed label and name (see metricFormat). */
export type Kind = "inr" | "count" | "pct" | "days" | "per1000" | "ratio" | "score" | "number";

function fmtINR(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e7) return `₹${fmtNumber(v / 1e7, a >= 1e10 ? 0 : 1)} cr`;
  if (a >= 1e5) return `₹${fmtNumber(v / 1e5, 1)} lakh`;
  return `₹${fmtNumber(v, 0)}`;
}

function fmtCount(v: number): string {
  return Math.abs(v) >= 1e7 ? `${fmtNumber(v / 1e7, 1)} cr` : Math.abs(v) >= 1e5 ? `${fmtNumber(v / 1e5, 1)} lakh` : fmtNumber(v, Number.isInteger(v) ? 0 : 1);
}

export function formatValue(kind: Kind, v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "No value";
  switch (kind) {
    case "inr":
      return fmtINR(v);
    case "count":
      return fmtCount(v);
    case "pct":
      return `${fmtNumber(v * 100, Math.abs(v) < 0.1 ? 1 : 0)}%`;
    case "days":
      return `${fmtNumber(v, 1)} days`;
    case "per1000":
      return fmtNumber(v, Math.abs(v) < 10 ? 2 : 1);
    case "ratio":
      return `${fmtNumber(v, 2)}×`;
    case "score":
      return fmtNumber(v, 0);
    default:
      return fmtNumber(v, Math.abs(v) < 10 && !Number.isInteger(v) ? 2 : Number.isInteger(v) ? 0 : 1);
  }
}

/** Shorter tick labels for axes. */
export function formatTick(kind: Kind, v: number): string {
  switch (kind) {
    case "inr": {
      const a = Math.abs(v);
      if (a >= 1e7) return `₹${fmtNumber(v / 1e7, Number.isInteger(v / 1e7) ? 0 : 1)} cr`;
      if (a >= 1e5) return `₹${fmtNumber(v / 1e5, Number.isInteger(v / 1e5) ? 0 : 1)}L`;
      return `₹${fmtNumber(v)}`;
    }
    case "pct":
      return `${fmtNumber(v * 100, Number.isInteger(Math.round(v * 1000) / 10) ? 0 : 1)}%`;
    case "days":
    case "score":
      return fmtNumber(v);
    case "count":
      return Math.abs(v) >= 1e5 ? `${fmtNumber(v / 1e5, Number.isInteger(v / 1e5) ? 0 : 1)}L` : fmtNumber(v);
    default:
      return fmtNumber(v, Number.isInteger(v) ? 0 : 1);
  }
}

/** A signed change for KPI deltas: percent for money and counts, points for rates, the unit otherwise. */
export function formatDelta(kind: Kind, current: number, prior: number): { text: string; sign: -1 | 0 | 1 } | null {
  let change: number, text: string;
  if (kind === "inr" || kind === "count") {
    if (prior === 0) return null;
    change = ((current - prior) / Math.abs(prior)) * 100;
    text = `${fmtNumber(Math.abs(change), 1)}%`;
  } else if (kind === "pct") {
    change = (current - prior) * 100;
    text = `${fmtNumber(Math.abs(change), 1)} pts`;
  } else if (kind === "days") {
    change = current - prior;
    text = `${fmtNumber(Math.abs(change), 1)} days`;
  } else {
    change = current - prior;
    text = formatValue(kind, Math.abs(change));
  }
  const sign = !/[1-9]/.test(text) ? 0 : change > 0 ? 1 : -1;
  return { text: `${sign > 0 ? "+" : sign < 0 ? MINUS : ""}${text}`, sign };
}
