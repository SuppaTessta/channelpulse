// POST /api/ask: response types and the chart built from chart_spec, checked against the returned columns.
// No React or server imports: the Ask panel (client) uses it.
import type { BarSeries } from "@/components/charts/bar-list";
import type { Bucket, ChartSeries } from "@/components/charts/time-chart";
import { toISODate, weekStart } from "./dates";
import type { Kind } from "./format";
import { metricKind } from "./metrics";
import { bucketText } from "./series";
import { num, type Table } from "./table";

export type AskLabel = "governed_metric" | "ad_hoc_sql_verify" | "refused" | "needs_clarification";
type ChartSpec = { type: "line" | "bar" | "table"; x: string | null; y: string | null; series: string | null };
export type AskResponse = {
  answer_text: string;
  sql: string[];
  data: Table | null;
  chart_spec: ChartSpec | null;
  label: AskLabel;
  confidence_note: string;
  trace_id: string;
};

/** GET /api/ask/status and /api/ask/replay (api/app/main.py): live mode is opt-in; otherwise recorded answers. */
export type Recording = {
  model: string;
  effort: string;
  recorded_at: string;
  as_of: string;
  region: string;
  status: string;
  git_commit: string | null;
  count: number;
};
/** Live mode's owner-paid allowance for the asking visitor; null in replay mode, absent from an older API. */
export type FreeAllowance = { limit: number; remaining: number; available: boolean; reason: "no_credentials" | "paused" | "used" | null };
export type AskStatus = {
  mode: "live" | "replay";
  reason: "no_credentials" | "live_off" | null;
  model: string | null;
  recording: Recording | null;
  free?: FreeAllowance | null;
};
export type ReplayAnswer = {
  id: string;
  category: string;
  question: string;
  response: AskResponse;
  eval: { correct: boolean; label_correct: boolean };
  served_model: string | null;
  latency_ms: number;
  cost_usd: number;
};
export type Replay = { recording: Recording | null; answers: ReplayAnswer[]; withheld: boolean };

type AskChart =
  | { kind: "time"; mark: "line" | "bar"; buckets: Bucket[]; series: ChartSeries[]; valueKind: Kind; grain: string; x: string; y: string }
  | { kind: "category"; rows: { key: string; label: string }[]; series: BarSeries[]; valueKind: Kind; x: string; y: string }
  | { kind: "none"; reason: string | null };

const MAX_SERIES = 8;
const MAX_CATEGORIES = 30;

function dateBuckets(dates: string[]): { buckets: Bucket[]; grain: string } {
  const grain = dates.every((d) => d.endsWith("-01")) ? "month" : dates.every((d) => weekStart(d) === d) ? "week" : "day";
  return { grain, buckets: dates.map((d) => ({ start: d, end: d, year: d.slice(0, 4), partial: null, provisional: false, ...bucketText(grain, d) })) };
}

/**
 * The chart for an answer, or why there isn't one. The API already checks the hint; this checks again here, since a
 * chart drawn from the wrong column would state something the data doesn't.
 */
export function buildAskChart(r: AskResponse): AskChart {
  const data = r.data;
  const spec = r.chart_spec;
  if (!data || !data.rows.length) return { kind: "none", reason: null };
  if (!spec) return { kind: "none", reason: "No chart was suggested for this answer, so the table shows the result." };
  if (spec.type === "table") return { kind: "none", reason: null };
  const { x, y, series } = spec;
  const xi = x ? data.columns.indexOf(x) : -1;
  const yi = y ? data.columns.indexOf(y) : -1;
  const si = series ? data.columns.indexOf(series) : -1;
  if (!x || !y || xi < 0 || yi < 0 || (series && si < 0)) {
    return { kind: "none", reason: "The chart hint names columns the result doesn't have, so only the table is shown." };
  }
  if (!data.rows.every((row) => row[yi] == null || num(row[yi]) != null)) {
    return { kind: "none", reason: `${y} isn't numeric in every row, so it can't be charted. The table shows the result.` };
  }
  const seriesKeys = [...new Set(data.rows.map((row) => (si < 0 ? y : String(row[si]))))];
  if (seriesKeys.length > MAX_SERIES) {
    return { kind: "none", reason: `The result has ${seriesKeys.length} series, more than a chart can keep apart. The table shows them all.` };
  }
  const valueKind = metricKind(y);
  const xs = data.rows.map((row) => row[xi]);
  const dates = xs.map(toISODate);
  const cell = new Map<string, number | null>();
  data.rows.forEach((row, i) => cell.set(`${si < 0 ? y : String(row[si])}|${dates[i] ?? String(xs[i])}`, num(row[yi])));
  const slot = (k: number) => k + 1;

  if (dates.every(Boolean)) {
    const unique = [...new Set(dates as string[])].sort();
    const { buckets, grain } = dateBuckets(unique);
    return {
      kind: "time",
      mark: spec.type,
      buckets,
      grain,
      x,
      y,
      valueKind,
      series: seriesKeys.map((s, k) => ({ key: s, label: s, slot: slot(k), horizonBound: false, values: unique.map((d) => cell.get(`${s}|${d}`) ?? null) })),
    };
  }
  const categories = [...new Set(xs.map(String))];
  if (spec.type === "line") {
    const buckets: Bucket[] = categories.map((c) => ({ start: c, end: c, year: "", partial: null, provisional: false, label: c, tick: c, tickYear: c }));
    return {
      kind: "time",
      mark: "line",
      buckets,
      grain: x,
      x,
      y,
      valueKind,
      series: seriesKeys.map((s, k) => ({ key: s, label: s, slot: slot(k), horizonBound: false, values: categories.map((c) => cell.get(`${s}|${c}`) ?? null) })),
    };
  }
  if (categories.length > MAX_CATEGORIES) {
    return { kind: "none", reason: `${categories.length} categories are too many bars to read. The table shows them all.` };
  }
  return {
    kind: "category",
    rows: categories.map((c) => ({ key: c, label: c })),
    x,
    y,
    valueKind,
    series: seriesKeys.map((s, k) => ({ key: s, label: s, slot: slot(k), values: categories.map((c) => cell.get(`${s}|${c}`) ?? null) })),
  };
}

export const LABEL_TEXT: Record<AskLabel, string> = {
  governed_metric: "Governed metric",
  ad_hoc_sql_verify: "Ad-hoc SQL, verify",
  refused: "Refused",
  needs_clarification: "Needs clarification",
};
