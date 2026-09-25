// Server-side client for the governed API. Every figure on the dashboard comes through here.
// Functions return a Result instead of throwing, so each section can show the API's exact error.
import { cache } from "react";
import { API_URL, type Region } from "./config";
import { monthEnd, toISODate } from "./dates";
import { column, records, type Table } from "./table";

export type Scalar = string | number | boolean;
export type Filter = { dimension: string; op: "=" | "!=" | ">" | ">=" | "<" | "<=" | "in" | "not_in"; value: Scalar | Scalar[] };
export type MetricQuery = {
  metric_name: string;
  filters?: Filter[];
  group_by?: string[];
  date_range?: { start: string; end: string } | null;
};
export type Governed = { label: string; sql: string; row_count: number; row_cap_hit: boolean; data: Table };
export type Metric = {
  name: string;
  label: string;
  description: string;
  type: string;
  formula: string;
  time_dimension: string;
  default_time_grain: string;
  dimensions: string[];
  glossary: boolean;
};
export type ApiError = { kind: "unreachable" | "timeout" | "http" | "empty"; status?: number; detail: string; endpoint: string };
export type Result<T> = { ok: true; value: T } | { ok: false; error: ApiError };
/** A governed query together with the request that produced it, for the Definition and SQL disclosure. */
export type Query = { request: MetricQuery; region: Region; result: Governed };

const TIMEOUT_MS = 20_000;

// A page runs about 25 governed queries. Fired all at once they contend in Postgres and the heavy ones (weekly
// stock snapshots) pass the API's 5 s statement timeout, so at most this many calls run at a time per server process.
// ponytail: an in-process FIFO; a shared limit across instances would need the API to queue instead.
const MAX_CONCURRENT = 4;
let running = 0;
const waiting: (() => void)[] = [];

async function withSlot<T>(fn: () => Promise<T>): Promise<T> {
  if (running < MAX_CONCURRENT) running++;
  else await new Promise<void>((resolve) => waiting.push(resolve)); // the finishing call hands its slot over
  try {
    return await fn();
  } finally {
    const next = waiting.shift();
    if (next) next();
    else running--;
  }
}

async function errorDetail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    const detail = body?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail.map((e) => `${(e.loc ?? []).filter((p: unknown) => p !== "body").join(".")}: ${e.msg}`).join("; ");
    }
    return JSON.stringify(body);
  } catch {
    return res.statusText || `HTTP ${res.status}`;
  }
}

// A drill-down or filter change re-renders the whole page on the server, so without this every click re-ran every
// governed query on it (12 on /quality). Successful results are reused for a minute; the warehouse refreshes daily.
// ponytail: per-process memory, cleared wholesale at MAX_CACHED; a shared cache would need Redis or the API's help.
const CACHE_MS = 60_000;
const MAX_CACHED = 500;
const recent = new Map<string, { at: number; value: Promise<Result<unknown>> }>();

function call<T>(endpoint: string, init: RequestInit & { next?: { revalidate: number } }, region: Region): Promise<Result<T>> {
  const key = `${region} ${init.method ?? "GET"} ${endpoint} ${init.body ?? ""}`;
  const hit = recent.get(key);
  if (hit && Date.now() - hit.at < CACHE_MS) return hit.value as Promise<Result<T>>;
  if (recent.size >= MAX_CACHED) recent.clear();
  const value = callOnce<T>(endpoint, init, region);
  recent.set(key, { at: Date.now(), value });
  value.then((r) => !r.ok && recent.delete(key)); // failures are never reused: Retry must really retry
  return value;
}

function callOnce<T>(endpoint: string, init: RequestInit & { next?: { revalidate: number } }, region: Region): Promise<Result<T>> {
  return withSlot(async () => {
    const first = await send<T>(endpoint, init, region);
    // A statement timeout under contention is usually transient: one retry, then the error is shown as it is.
    const transient = !first.ok && first.error.status === 502 && first.error.detail.includes("statement timeout");
    return transient ? send<T>(endpoint, init, region) : first;
  });
}

async function send<T>(endpoint: string, init: RequestInit & { next?: { revalidate: number } }, region: Region): Promise<Result<T>> {
  try {
    const res = await fetch(`${API_URL}${endpoint}`, {
      ...init,
      headers: { "Content-Type": "application/json", "X-Demo-Region": region },
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!res.ok) return { ok: false, error: { kind: "http", status: res.status, detail: await errorDetail(res), endpoint } };
    return { ok: true, value: (await res.json()) as T };
  } catch (e) {
    const timedOut = e instanceof Error && (e.name === "TimeoutError" || e.name === "AbortError");
    const cause = (e as { cause?: { code?: string } })?.cause?.code;
    return {
      ok: false,
      error: {
        kind: timedOut ? "timeout" : "unreachable",
        detail: timedOut ? `No response within ${TIMEOUT_MS / 1000} seconds.` : `Couldn't connect to ${API_URL}${cause ? ` (${cause})` : ""}.`,
        endpoint,
      },
    };
  }
}

// Keyed by the request's JSON, so identical queries on one page share a single API call.
const runQuery = cache((body: string, region: Region) =>
  call<Governed>("/api/metrics/query", { method: "POST", body, cache: "no-store" }, region),
);

export async function query(request: MetricQuery, region: Region): Promise<Result<Query>> {
  const normal: MetricQuery = {
    metric_name: request.metric_name,
    filters: request.filters ?? [],
    group_by: request.group_by ?? [],
    date_range: request.date_range ?? null,
  };
  const r = await runQuery(JSON.stringify(normal), region);
  return r.ok ? { ok: true, value: { request: normal, region, result: r.value } } : r;
}

/** Runs queries in parallel; the first failure wins, so a section shows one clear error. */
export async function queryAll(requests: MetricQuery[], region: Region): Promise<Result<Query[]>> {
  const results = await Promise.all(requests.map((r) => query(r, region)));
  const failed = results.find((r) => !r.ok);
  if (failed && !failed.ok) return failed;
  return { ok: true, value: results.map((r) => (r as { ok: true; value: Query }).value) };
}

/** The governed catalogue from GET /api/metrics: labels, definitions, formulas and each metric's dimensions. */
export const getMetrics = cache(async (): Promise<Result<Record<string, Metric>>> => {
  const r = await call<{ metrics: Metric[] }>("/api/metrics", { method: "GET", next: { revalidate: 300 } }, "ALL");
  return r.ok ? { ok: true, value: Object.fromEntries(r.value.metrics.map((m) => [m.name, m])) } : r;
});

export type Anomaly = {
  as_of: string;
  detector: string;
  entity_type: string;
  entity_id: string;
  failure_mode: string | null;
  region: string | null;
  snapshot_date: string;
  first_flag_date: string | null;
  effect_size: number | null;
  p_value: number | null;
  details: Record<string, unknown> | null;
};
export type Anomalies = { rows: Anomaly[]; asOf: string | null; result: Governed; endpoint: string; region: Region };

/** GET /api/anomalies: each pre-registered detector's latest flags on or before `asOf`, under the region claim. */
export const getAnomalies = cache(async (region: Region, asOf?: string): Promise<Result<Anomalies>> => {
  const endpoint = `/api/anomalies${asOf ? `?as_of=${encodeURIComponent(asOf)}` : ""}`;
  const r = await call<Governed>(endpoint, { method: "GET", cache: "no-store" }, region);
  if (!r.ok) return r;
  const rows = records(r.value.data) as Anomaly[];
  return { ok: true, value: { rows, asOf: toISODate(rows[0]?.as_of) ?? asOf ?? null, result: r.value, endpoint, region } };
});

export type DataWindow = {
  /** Latest sale date of reported sell-out: what "Data as of" shows. */
  asOf: string;
  /** First month with sell-out data. */
  dataStart: string;
  /** First sale date the warehouse still marks unsettled (decisions D12), or null when none are. */
  provisionalFrom: string | null;
  queries: Query[];
};

const days = (q: Query, name: string) =>
  (column(q.result.data, name) ?? []).map(toISODate).filter((d): d is string => d !== null).sort();

/**
 * As-of and provisional window, from two cheap governed queries on secondary_units: its months (for the data start)
 * and its sale days that are not yet settled (the reporting horizon), whose last day is the as-of.
 */
export const getDataWindow = cache(async (region: Region): Promise<Result<DataWindow>> => {
  const both = await queryAll(
    [
      { metric_name: "secondary_units", group_by: ["metric_time__month"] },
      {
        metric_name: "secondary_units",
        group_by: ["metric_time__day"],
        filters: [{ dimension: "secondary_sale__is_settled", op: "=", value: false }],
      },
    ],
    region,
  );
  if (!both.ok) return both;
  const [months, unsettled] = both.value;
  const monthStarts = days(months, "metric_time__month");
  if (!monthStarts.length) {
    return {
      ok: false,
      error: { kind: "empty", detail: "secondary_units returned no rows, so there is no as-of date.", endpoint: "/api/metrics/query" },
    };
  }
  const provisional = days(unsettled, "metric_time__day");
  const queries = [months, unsettled];
  let asOf = provisional.at(-1);
  if (!asOf) {
    // Nothing is provisional (an old snapshot): the as-of is the last sale day of the last month.
    const lastMonth = monthStarts.at(-1)!;
    const r = await query(
      { metric_name: "secondary_units", group_by: ["metric_time__day"], date_range: { start: lastMonth, end: monthEnd(lastMonth) } },
      region,
    );
    if (!r.ok) return r;
    queries.push(r.value);
    asOf = days(r.value, "metric_time__day").at(-1) ?? monthEnd(lastMonth);
  }
  return { ok: true, value: { asOf, dataStart: monthStarts[0], provisionalFrom: provisional[0] ?? null, queries } };
});
