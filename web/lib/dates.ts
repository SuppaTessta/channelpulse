// ISO calendar dates ("YYYY-MM-DD") handled as UTC midnights, so server and browser always agree.

export type Grain = "day" | "week" | "month" | "quarter" | "year";
export type Range = { from: string; to: string };

const DAY_MS = 86_400_000;
const ISO = /^\d{4}-\d{2}-\d{2}$/;

const ms = (iso: string) => Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10));
const iso = (t: number) => new Date(t).toISOString().slice(0, 10);

export function isISODate(value: unknown): value is string {
  return typeof value === "string" && ISO.test(value) && iso(ms(value)) === value;
}

/** The calendar date at the start of an API value: "2026-04-01", "2026-04-01T00:00:00+00:00" and so on. */
export function toISODate(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const day = value.slice(0, 10);
  return isISODate(day) ? day : null;
}

export const addDays = (d: string, n: number) => iso(ms(d) + n * DAY_MS);
export const daysBetween = (a: string, b: string) => Math.round((ms(b) - ms(a)) / DAY_MS);
export const minDate = (a: string, b: string) => (a < b ? a : b);
export const maxDate = (a: string, b: string) => (a > b ? a : b);

export function addMonths(d: string, n: number): string {
  const y = +d.slice(0, 4), m = +d.slice(5, 7) - 1 + n, day = +d.slice(8, 10);
  const last = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
  return iso(Date.UTC(y, m, Math.min(day, last)));
}

export const monthStart = (d: string) => `${d.slice(0, 7)}-01`;
export const monthEnd = (d: string) => addDays(addMonths(monthStart(d), 1), -1);

/** Monday of the ISO week, matching Postgres date_trunc('week'). */
export function weekStart(d: string): string {
  const weekday = new Date(ms(d)).getUTCDay();
  return addDays(d, -((weekday + 6) % 7));
}

export function bucketStart(d: string, grain: Grain): string {
  switch (grain) {
    case "day":
      return d;
    case "week":
      return weekStart(d);
    case "month":
      return monthStart(d);
    case "quarter":
      return `${d.slice(0, 4)}-${String(Math.floor((+d.slice(5, 7) - 1) / 3) * 3 + 1).padStart(2, "0")}-01`;
    case "year":
      return `${d.slice(0, 4)}-01-01`;
  }
}

export function nextBucket(start: string, grain: Grain): string {
  switch (grain) {
    case "day":
      return addDays(start, 1);
    case "week":
      return addDays(start, 7);
    case "month":
      return addMonths(start, 1);
    case "quarter":
      return addMonths(start, 3);
    case "year":
      return addMonths(start, 12);
  }
}

export const bucketEnd = (start: string, grain: Grain) => addDays(nextBucket(start, grain), -1);

/** Every bucket start from the one holding `from` through the one holding `to`. */
export function bucketsBetween(from: string, to: string, grain: Grain): string[] {
  const out: string[] = [];
  for (let b = bucketStart(from, grain); b <= to; b = nextBucket(b, grain)) out.push(b);
  return out;
}

/** Indian fiscal year, named by the year it ends: FY27 runs 1 Apr 2026 to 31 Mar 2027. */
export const fiscalYear = (d: string) => (+d.slice(5, 7) >= 4 ? +d.slice(0, 4) + 1 : +d.slice(0, 4));
export const fyStart = (fy: number) => `${fy - 1}-04-01`;
export const fyEnd = (fy: number) => `${fy}-03-31`;
export const fyLabel = (fy: number) => `FY${String(fy % 100).padStart(2, "0")}`;

export type Preset = { key: string; label: string; range: Range; prior: Range; priorLabel: string };

/** The date-range presets, relative to the data's as-of date. Each carries the window its delta compares against. */
export function presets(asOf: string): Preset[] {
  const fy = fiscalYear(asOf);
  const full = (y: number): Preset => ({
    key: `fy${y}`,
    label: fyLabel(y),
    range: { from: fyStart(y), to: fyEnd(y) },
    prior: { from: fyStart(y - 1), to: fyEnd(y - 1) },
    priorLabel: fyLabel(y - 1),
  });
  return [
    {
      key: "fytd",
      label: `${fyLabel(fy)} to date`,
      range: { from: fyStart(fy), to: asOf },
      prior: { from: fyStart(fy - 1), to: addMonths(asOf, -12) },
      priorLabel: `same dates in ${fyLabel(fy - 1)}`,
    },
    full(fy - 1),
    full(fy - 2),
    {
      key: "90d",
      label: "Last 90 days",
      range: { from: addDays(asOf, -89), to: asOf },
      prior: { from: addDays(asOf, -179), to: addDays(asOf, -90) },
      priorLabel: "the 90 days before",
    },
  ];
}

/** The window of equal length immediately before `range`. */
export function precedingWindow(range: Range): Range {
  const length = daysBetween(range.from, range.to) + 1;
  return { from: addDays(range.from, -length), to: addDays(range.from, -1) };
}
