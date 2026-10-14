// Presentation rules for governed metrics, derived from the catalogue (GET /api/metrics) wherever possible.
import type { DefMetric, DefQuery } from "@/components/definition";
import type { Anomaly, Metric, Query, Result } from "./api";
import type { Kind } from "./format";

export const toDefMetric = ({ name, label, description, formula, type, time_dimension }: Metric): DefMetric => ({
  name,
  label,
  description,
  formula,
  type,
  time_dimension,
});

export function toDefQuery(q: Query, caption: string): DefQuery {
  const r = q.request;
  const request: [string, string][] = [
    ["POST", "/api/metrics/query"],
    ["metric_name", r.metric_name],
    ...(r.group_by?.length ? [["group_by", r.group_by.join(", ")] as [string, string]] : []),
    ...(r.filters ?? []).map((f): [string, string] => ["filter", `${f.dimension} ${f.op} ${JSON.stringify(f.value)}`]),
    ["date_range", r.date_range ? `${r.date_range.start} to ${r.date_range.end}` : "all history"],
    ["X-Demo-Region", q.region],
  ];
  return { caption, request, sql: q.result.sql, rowCount: q.result.row_count, rowCapHit: q.result.row_cap_hit };
}

export function anomaliesDefQuery(a: { endpoint: string; region: string; result: { sql: string; row_count: number; row_cap_hit: boolean } }, caption: string): DefQuery {
  return {
    caption,
    request: [
      ["GET", a.endpoint],
      ["X-Demo-Region", a.region],
    ],
    sql: a.result.sql,
    rowCount: a.result.row_count,
    rowCapHit: a.result.row_cap_hit,
  };
}

/** How values read, from the governed name and label: "(₹)" is money, "per 1,000" a claim rate, and so on. */
export function metricKind(name: string, label = ""): Kind {
  const text = `${name} ${label}`.toLowerCase();
  if (label.includes("(₹)") || /_value\b|receivables|amount_inr|_cost\b/.test(name)) return "inr";
  if (text.includes("per 1,000") || name.includes("per_1000")) return "per1000";
  if (name === "dso" || name.includes("days_of_stock") || label.includes("(days)")) return "days";
  if (name.includes("ratio")) return "ratio";
  if (/_rate$|efficiency/.test(name)) return "pct";
  if (name.includes("score")) return "score";
  if (/units|visits|claims|flags|distributors|_days$/.test(name)) return "count";
  return "number";
}

/** The governed label without its unit suffix or the health-component prefix: the value shows the unit. */
export function shortLabel(label: string): string {
  const bare = label.replace(/\s*\([^)]*\)\s*$/, "").replace(/^Health component:\s*/i, "");
  return bare.charAt(0).toUpperCase() + bare.slice(1);
}

/**
 * Metrics built on late-arriving sell-out reports, whose newest days are provisional (decisions D12). Sell-out facts
 * carry an __is_settled dimension. Channel stock is implied from sell-out too (primary minus secondary), but the weekly
 * inventory mart (D24) has no settled flag, so its metrics are recognised by their semantic model's own dimension.
 */
export const isHorizonBound = (m: Metric | undefined) =>
  !!m?.dimensions.some((d) => d.endsWith("__is_settled") || d === "inventory_week__has_days_of_stock");

/** Sums and counts read zero for a period with no rows; averages and ratios have no value there. */
export const zeroWhenEmpty = (m: Metric | undefined) => !!m && m.type === "simple" && /^(sum|count)/.test(m.formula);

/** Which way is good, for delta colour. Days of stock has a target band, so neither direction is good. */
export const GOOD_DIRECTION: Record<string, 1 | -1 | 0> = {
  primary_sales_value: 1,
  secondary_sales_value: 1,
  channel_days_of_stock: 0,
  claims_per_1000_units: -1,
  dso: -1,
};

/** Metrics whose period is a manufacture date: newer cohorts have had less time to collect claims. */
export const isCohortTimed = (m: Metric | undefined) => !!m && /mfg_date/.test(m.time_dimension);

export function fallbackMetric(name: string): Metric {
  return {
    name,
    label: name,
    description: "",
    type: "",
    formula: "",
    time_dimension: "",
    default_time_grain: "day",
    dimensions: [],
    glossary: false,
  };
}

export const metricOf = (catalog: Result<Record<string, Metric>>, name: string) => (catalog.ok ? catalog.value[name] : undefined) ?? fallbackMetric(name);

const WEEKLY_DETECTORS = new Set(["distributor_health", "lot_scan", "installer_scan"]);
const day = (v: unknown) => (typeof v === "string" ? v.slice(0, 10) : null);

/** The most recent weekly detector snapshot among the flags (detectors run every Sunday, detectors.yaml). */
export function latestSnapshot(rows: Anomaly[]): string | null {
  return rows.reduce<string | null>((max, a) => {
    const d = WEEKLY_DETECTORS.has(a.detector) ? day(a.snapshot_date) : null;
    return d && (!max || d > max) ? d : max;
  }, null);
}

/**
 * /api/anomalies returns each entity's latest flag on or before as_of, so it includes entities last flagged long ago.
 * A flag is current when it comes from the latest snapshot (and, where the detector says so, flagged in it).
 */
export function isCurrentFlag(a: Anomaly, latest: string | null): boolean {
  return !!latest && day(a.snapshot_date) === latest && a.details?.flagged_this_snapshot !== false;
}
