// Turns governed query results into chart buckets and aligned series (server side).
import type { Bucket } from "@/components/charts/time-chart";
import type { DataWindow, Query } from "./api";
import { bucketEnd, bucketsBetween, maxDate, minDate, toISODate, type Grain, type Range } from "./dates";
import { fmtDate, fmtDayMonth, fmtMonth, fmtMonthShort, fmtRange } from "./format";
import { column, num } from "./table";

type Win = Pick<DataWindow, "asOf" | "dataStart" | "provisionalFrom">;

/**
 * The buckets a grouped query returns. MetricFlow widens date_range to whole buckets at the group-by grain, so the
 * first bucket can start before the selected range; the last is partial when it runs past the as-of date.
 */
export function timeBuckets(grain: Grain, range: Range, win: Win): Bucket[] {
  const from = maxDate(range.from, win.dataStart);
  const to = minDate(range.to, win.asOf);
  return bucketsBetween(from, to, grain).map((start) => {
    const end = bucketEnd(start, grain);
    const year = start.slice(0, 4);
    const partial = end > win.asOf ? `Data to ${fmtDayMonth(win.asOf)}` : start < win.dataStart ? `Data from ${fmtDayMonth(win.dataStart)}` : null;
    const provisional = !!win.provisionalFrom && end >= win.provisionalFrom;
    if (grain === "month") return { start, end, year, partial, provisional, label: fmtMonth(start), tick: fmtMonthShort(start), tickYear: fmtMonth(start) };
    if (grain === "week") {
      return { start, end, year, partial, provisional, label: `Week of ${fmtDate(start)}`, tick: fmtDayMonth(start), tickYear: `${fmtDayMonth(start)} ${year}` };
    }
    return { start, end, year, partial, provisional, label: fmtDate(start), tick: fmtDayMonth(start), tickYear: fmtDate(start) };
  });
}

/** What a grouped chart actually covers: whole buckets, cut at the as-of date. */
export function coverage(buckets: Bucket[], win: Win): Range | null {
  if (!buckets.length) return null;
  return { from: maxDate(buckets[0].start, win.dataStart), to: minDate(buckets.at(-1)!.end, win.asOf) };
}

export function coverageText(buckets: Bucket[], range: Range, win: Win, grain: Grain): string {
  const c = coverage(buckets, win);
  if (!c) return fmtRange(range);
  return c.from < range.from ? `${fmtRange(c)}, whole ${grain}s` : fmtRange(c);
}

/** Upper bounds of `bins - 1` equal-width bins on a round step covering 0 to max: [5, 10, 15, 20, 25] for six. */
export function niceThresholds(max: number, bins = 6): number[] {
  const raw = Math.max(max, 1e-9) / bins;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((f) => f * power).find((s) => s >= raw) ?? 10 * power;
  return Array.from({ length: bins - 1 }, (_, i) => +((i + 1) * step).toFixed(10));
}

/** One value per bucket; sums and counts read 0 for a bucket with no rows, other metrics have no value there. */
export function alignSeries(buckets: Bucket[], q: Query, timeColumn: string, valueColumn: string, zeroFill: boolean): (number | null)[] {
  const times = column(q.result.data, timeColumn) ?? [];
  const values = column(q.result.data, valueColumn) ?? [];
  const byStart = new Map<string, number | null>();
  times.forEach((t, i) => {
    const d = toISODate(t);
    if (d) byStart.set(d, num(values[i]));
  });
  return buckets.map((b) => (byStart.has(b.start) ? (byStart.get(b.start) ?? null) : zeroFill ? 0 : null));
}
