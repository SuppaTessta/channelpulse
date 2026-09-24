// Presentation rules for governed metrics, derived from the catalogue (GET /api/metrics) wherever possible.
import type { DefMetric, DefQuery } from "@/components/definition";
import type { Anomaly, Metric, Query } from "./api";
import { fmtNumber, type Kind } from "./format";

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

/** Metrics built on late-arriving sell-out reports carry an __is_settled dimension (semantic layer caveat). */
export const isHorizonBound = (m: Metric | undefined) => !!m?.dimensions.some((d) => d.endsWith("__is_settled"));

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

/** A detector's details JSON as label and value pairs, for display. Its keys are the detector's own. */
export function detailPairs(details: Anomaly["details"]): [string, string][] {
  if (!details || typeof details !== "object") return [];
  return Object.entries(details).map(([k, v]) => [k, typeof v === "number" ? fmtNumber(v, Number.isInteger(v) ? 0 : 2) : typeof v === "string" ? v : JSON.stringify(v)]);
}
