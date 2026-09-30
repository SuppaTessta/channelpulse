// Shape checks where API responses enter the dashboard. A response that fails one becomes an ApiError of kind
// "shape" for its own panel, instead of a crash somewhere downstream (typically an API and a dashboard from
// different commits).
import type { AskResponse, AskStatus, Replay } from "./ask";
import type { Governed, Metric } from "./api";
import type { Brief, BriefWeeks } from "./brief";
import type { TraceDetail, TraceList } from "./traces";

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const isStr = (v: unknown): v is string => typeof v === "string";
const isStrOrNull = (v: unknown) => v === null || isStr(v);

function isTable(v: unknown): boolean {
  if (!isObj(v) || !Array.isArray(v.columns) || !Array.isArray(v.rows) || !v.columns.every(isStr)) return false;
  const width = v.columns.length;
  return v.rows.every((row) => Array.isArray(row) && row.length === width);
}

export function isGoverned(v: unknown): v is Governed {
  return (
    isObj(v) &&
    isStr(v.label) &&
    isStr(v.sql) &&
    typeof v.row_count === "number" &&
    typeof v.row_cap_hit === "boolean" &&
    isTable(v.data)
  );
}

export function isMetricList(v: unknown): v is { metrics: Metric[] } {
  return (
    isObj(v) &&
    Array.isArray(v.metrics) &&
    v.metrics.every((m) => isObj(m) && isStr(m.name) && isStr(m.label) && isStr(m.description) && Array.isArray(m.dimensions))
  );
}

const LABELS = new Set(["governed_metric", "ad_hoc_sql_verify", "refused", "needs_clarification"]);
const CHART_TYPES = new Set(["line", "bar", "table"]);

export function isAskResponse(v: unknown): v is AskResponse {
  if (!isObj(v)) return false;
  const chart = v.chart_spec;
  const chartOk =
    chart === null || (isObj(chart) && CHART_TYPES.has(chart.type as string) && isStrOrNull(chart.x) && isStrOrNull(chart.y) && isStrOrNull(chart.series));
  return (
    isStr(v.answer_text) &&
    Array.isArray(v.sql) &&
    v.sql.every(isStr) &&
    (v.data === null || isTable(v.data)) &&
    chartOk &&
    LABELS.has(v.label as string) &&
    isStr(v.confidence_note) &&
    isStr(v.trace_id)
  );
}

function isRecording(v: unknown): boolean {
  return (
    isObj(v) &&
    isStr(v.model) &&
    isStr(v.effort) &&
    isStr(v.recorded_at) &&
    isStr(v.as_of) &&
    isStr(v.region) &&
    typeof v.count === "number"
  );
}

export function isAskStatus(v: unknown): v is AskStatus {
  return (
    isObj(v) &&
    (v.mode === "live" || v.mode === "replay") &&
    (v.reason === null || v.reason === "no_credentials" || v.reason === "live_off") &&
    isStr(v.provider) &&
    isStrOrNull(v.model) &&
    (v.recording === null || isRecording(v.recording))
  );
}

export function isReplay(v: unknown): v is Replay {
  return (
    isObj(v) &&
    (v.recording === null || isRecording(v.recording)) &&
    typeof v.withheld === "boolean" &&
    Array.isArray(v.answers) &&
    v.answers.every(
      (a) => isObj(a) && isStr(a.id) && isStr(a.category) && isStr(a.question) && isAskResponse(a.response) && isObj(a.eval) && typeof a.eval.correct === "boolean",
    )
  );
}

// Traces and the Weekly Brief: the fields each page reads are checked; anything else the API adds passes through.
const isNumOrNull = (v: unknown) => v == null || typeof v === "number";
const isFacet = (v: unknown) =>
  v === undefined ||
  (isObj(v) && Object.values(v).every((n) => typeof n === "number")) ||
  (Array.isArray(v) && v.every((x) => isObj(x) && typeof x.count === "number"));

function isTraceRow(v: unknown): boolean {
  return (
    isObj(v) &&
    isStr(v.trace_id) &&
    isStr(v.created_at) &&
    isStr(v.source) &&
    (v.label == null || LABELS.has(v.label as string)) &&
    (v.tools == null || (Array.isArray(v.tools) && v.tools.every(isStr))) &&
    isNumOrNull(v.latency_ms) &&
    isNumOrNull(v.est_cost_usd) &&
    isNumOrNull(v.row_count)
  );
}

export function isTraceList(v: unknown): v is TraceList {
  const t = isObj(v) ? v.totals : null;
  const f = isObj(v) ? v.facets : null;
  return (
    isObj(v) &&
    typeof v.total === "number" &&
    Array.isArray(v.traces) &&
    v.traces.every(isTraceRow) &&
    isObj(f) &&
    Object.values(f).every(isFacet) &&
    isObj(t) &&
    typeof t.traces === "number" &&
    isFacet(t.by_label) &&
    (v.live === "included" || v.live === "admin_only" || v.live === "unavailable") &&
    typeof v.withheld === "boolean"
  );
}

export function isTraceDetail(v: unknown): v is TraceDetail {
  return isTraceRow(v) && isObj(v) && Array.isArray(v.tool_calls) && v.tool_calls.every((c) => isObj(c) && isStr(c.name));
}

export function isBriefWeeks(v: unknown): v is BriefWeeks {
  return isObj(v) && Array.isArray(v.weeks) && v.weeks.every(isStr);
}

export function isBrief(v: unknown): v is Brief {
  const check = isObj(v) ? v.check : null;
  const narration = isObj(v) ? v.narration : null;
  return (
    isObj(v) &&
    isObj(v.week) &&
    isStr(v.week.start) &&
    isStr(v.week.end) &&
    (v.status === "verified" || v.status === "blocked") &&
    Array.isArray(v.sections) &&
    v.sections.every(
      (s) => isObj(s) && isStr(s.title) && Array.isArray(s.sentences) && s.sentences.every((x) => isObj(x) && isStr(x.text) && Array.isArray(x.facts) && x.facts.every(isStr)),
    ) &&
    isObj(v.facts) &&
    Object.values(v.facts).every((f) => isObj(f) && isStr(f.label) && isStr(f.display)) &&
    isObj(check) &&
    typeof check.queries_rechecked === "number" &&
    Array.isArray(check.problems) &&
    isObj(narration) &&
    (narration.by === "model" || narration.by === "template") &&
    (narration.blocked == null || Array.isArray(narration.blocked))
  );
}
