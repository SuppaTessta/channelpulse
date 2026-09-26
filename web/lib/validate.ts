// Shape checks where API responses enter the dashboard. A response that fails one becomes an ApiError of kind
// "shape" for its own panel, instead of a crash somewhere downstream (typically an API and a dashboard from
// different commits).
import type { AskResponse, AskStatus, Replay } from "./ask";
import type { Governed, Metric } from "./api";

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

const LABELS = new Set(["governed_metric", "ad_hoc_sql_verify", "refused"]);
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
    isStr(v.model) &&
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
