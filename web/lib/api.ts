// Server-side client for the governed API. Every figure on the dashboard comes through here.
// Functions return a Result instead of throwing, so each section can show the API's exact error.
import { cache } from "react";
import { API_URL, type Region } from "./config";
import { monthEnd, toISODate } from "./dates";
import { column, records, type Table } from "./table";
import type { AskStatus, Replay } from "./ask";
import type { Brief, BriefWeeks } from "./brief";
import type { TraceDetail, TraceList } from "./traces";
import { isAskStatus, isBrief, isBriefWeeks, isGoverned, isMetricList, isReplay, isTraceDetail, isTraceList } from "./validate";

type Scalar = string | number | boolean;
export type Filter = { dimension: string; op: "=" | "!=" | ">" | ">=" | "<" | "<=" | "in" | "not_in"; value: Scalar | Scalar[] };
type MetricQuery = {
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
export type ApiError = { kind: "unreachable" | "timeout" | "waking" | "http" | "empty" | "shape"; status?: number; detail: string; endpoint: string };
export type Result<T> = { ok: true; value: T } | { ok: false; error: ApiError };
/** A governed query together with the request that produced it, for the Definition and SQL disclosure. */
export type Query = { request: MetricQuery; region: Region; result: Governed };

const TIMEOUT_MS = 20_000;

// Server-side calls may use a different base than the browser's baked-in NEXT_PUBLIC_API_URL: read at run time, so
// one build can be pointed elsewhere (the smoke test's fault-injection proxy, or a private URL in deployment).
const SERVER_API_URL = (process.env.CHANNELPULSE_API_URL || API_URL).replace(/\/+$/, "");

// A free Render service sleeps after 15 idle minutes and takes about a minute to wake (D49). Meanwhile its proxy
// times out, refuses, or answers with an HTML page (a loading page, or a 502-504) where the API always sends JSON.
// That is "waking", not a failure. The first such answer marks the API as waking for WAKING_MS, so the rest of the
// page's calls don't each wait out a timeout.
const COLD_STARTS = process.env.CHANNELPULSE_API_COLD_STARTS === "1" || /\.onrender\.com$/.test(new URL(SERVER_API_URL).hostname);
const WAKING_MS = 20_000;
let wakingUntil = 0;

function waking<T>(endpoint: string, detail: string): Result<T> {
  wakingUntil = Date.now() + WAKING_MS;
  return { ok: false, error: { kind: "waking", detail, endpoint } };
}

type Check<T> = (value: unknown) => value is T;
/** fetch options, plus a longer time limit for the few endpoints that run many queries per call (the brief). */
type Init = RequestInit & { next?: { revalidate: number }; timeoutMs?: number; headers?: Record<string, string> };

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

function call<T>(endpoint: string, init: Init, region: Region, check: Check<T>): Promise<Result<T>> {
  const key = `${region} ${init.method ?? "GET"} ${endpoint} ${init.body ?? ""}`;
  const hit = recent.get(key);
  if (hit && Date.now() - hit.at < CACHE_MS) return hit.value as Promise<Result<T>>;
  if (recent.size >= MAX_CACHED) recent.clear();
  const value = callOnce<T>(endpoint, init, region, check);
  recent.set(key, { at: Date.now(), value });
  value.then((r) => !r.ok && recent.delete(key)); // failures are never reused: Retry must really retry
  return value;
}

function callOnce<T>(endpoint: string, init: Init, region: Region, check: Check<T>): Promise<Result<T>> {
  return withSlot(async () => {
    const first = await send<T>(endpoint, init, region, check);
    // A statement timeout under contention is usually transient: one retry, then the error is shown as it is.
    const transient = !first.ok && first.error.status === 502 && first.error.detail.includes("statement timeout");
    return transient ? send<T>(endpoint, init, region, check) : first;
  });
}

async function send<T>(endpoint: string, { timeoutMs = TIMEOUT_MS, headers, ...init }: Init, region: Region, check: Check<T>): Promise<Result<T>> {
  // Skipped calls don't extend the window: only a real answer from the sleeping host does.
  if (COLD_STARTS && Date.now() < wakingUntil) return { ok: false, error: { kind: "waking", detail: "The API was still waking up a moment ago.", endpoint } };
  try {
    const res = await fetch(`${SERVER_API_URL}${endpoint}`, {
      ...init,
      headers: { "Content-Type": "application/json", "X-Demo-Region": region, ...headers },
      signal: AbortSignal.timeout(timeoutMs),
    });
    const fromApi = (res.headers.get("content-type") ?? "").includes("json");
    if (COLD_STARTS && !fromApi && (res.ok || res.status >= 502)) return waking(endpoint, `HTTP ${res.status} from the host, not the API.`);
    if (!res.ok) return { ok: false, error: { kind: "http", status: res.status, detail: await errorDetail(res), endpoint } };
    const body: unknown = await res.json().catch(() => undefined);
    if (!check(body)) {
      return { ok: false, error: { kind: "shape", status: res.status, detail: `Unexpected response: ${JSON.stringify(body)?.slice(0, 200) ?? "not JSON"}`, endpoint } };
    }
    return { ok: true, value: body };
  } catch (e) {
    const timedOut = e instanceof Error && (e.name === "TimeoutError" || e.name === "AbortError");
    const cause = (e as { cause?: { code?: string } })?.cause?.code;
    if (COLD_STARTS) return waking(endpoint, timedOut ? `No response within ${timeoutMs / 1000} seconds.` : `Couldn't connect${cause ? ` (${cause})` : ""}.`);
    return {
      ok: false,
      error: {
        kind: timedOut ? "timeout" : "unreachable",
        detail: timedOut ? `No response within ${timeoutMs / 1000} seconds.` : `Couldn't connect to ${SERVER_API_URL}${cause ? ` (${cause})` : ""}.`,
        endpoint,
      },
    };
  }
}

// Keyed by the request's JSON, so identical queries on one page share a single API call.
const runQuery = cache((body: string, region: Region) =>
  call<Governed>("/api/metrics/query", { method: "POST", body, cache: "no-store" }, region, isGoverned),
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
  const r = await call<{ metrics: Metric[] }>("/api/metrics", { method: "GET", next: { revalidate: 300 } }, "ALL", isMetricList);
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
  const r = await call<Governed>(endpoint, { method: "GET", cache: "no-store" }, region, isGoverned);
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

/** GET /api/ask/status: whether the analyst answers live, why not, and which eval run can be replayed instead. */
export const getAskStatus = cache(() => call<AskStatus>("/api/ask/status", { method: "GET", cache: "no-store" }, "ALL", isAskStatus));

/** GET /api/ask/replay: the recorded answers, withheld by the API unless the region claim matches the recording's. */
export const getReplay = cache((region: Region) => call<Replay>("/api/ask/replay", { method: "GET", cache: "no-store" }, region, isReplay));

// Live traces need X-Admin-Token. It is read here, on the Next server, from a server-only variable: never
// NEXT_PUBLIC, so it is not in any browser bundle, and no client component calls these functions.
const ADMIN_TOKEN = process.env.CHANNELPULSE_ADMIN_TOKEN?.trim();
const adminHeaders = (): Record<string, string> => (ADMIN_TOKEN ? { "X-Admin-Token": ADMIN_TOKEN } : {});

/** GET /api/traces: the filtered page of traces, facet counts and totals. `params` is the filter query string. */
export const getTraces = cache((params: string, region: Region) =>
  call<TraceList>(`/api/traces${params ? `?${params}` : ""}`, { method: "GET", cache: "no-store", headers: adminHeaders() }, region, isTraceList),
);

/** GET /api/traces/{id}: one trace with its tool calls. */
export const getTrace = cache((id: string, region: Region) =>
  call<TraceDetail>(`/api/traces/${encodeURIComponent(id)}`, { method: "GET", cache: "no-store", headers: adminHeaders() }, region, isTraceDetail),
);

/** GET /api/brief/weeks: the weeks a brief exists for, newest first. */
export const getBriefWeeks = cache((region: Region) => call<BriefWeeks>("/api/brief/weeks", { method: "GET", cache: "no-store" }, region, isBriefWeeks));

/** GET /api/brief: one week's brief. The API re-runs every cited query first, so this call can take a while. */
export const getBrief = cache((week: string, region: Region) =>
  call<Brief>(`/api/brief?week=${encodeURIComponent(week)}`, { method: "GET", cache: "no-store", timeoutMs: 60_000 }, region, isBrief),
);
