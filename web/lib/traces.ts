// GET /api/traces and /api/traces/{id} (api/app/traces.py): agent traces, recorded by eval runs or asked live.
// No React or server imports: the traces page (server) and its table and drawer (client) both use it.
import type { AskLabel } from "./ask";

export type TraceRow = {
  trace_id: string;
  created_at: string;
  source: string;
  question: string;
  question_id: string | null;
  category: string | null;
  provider: string | null;
  model: string | null;
  served_model: string | null;
  label: AskLabel | null;
  final_sql: string | null;
  row_count: number | null;
  latency_ms: number | null;
  est_cost_usd: number | null;
  answer_text: string | null;
  eval_correct: boolean | null;
  error: string | null;
  tools: string[];
  tool_errors: number | unknown[] | null;
} & Record<string, unknown>;

export type ToolCall = {
  id: string;
  name: string;
  input: unknown;
  output: string | null;
  sql: string | null;
  row_count: number | null;
  duration_ms: number | null;
  error: string | null;
};
export type TraceDetail = TraceRow & { tool_calls: ToolCall[] };

/** A facet as the API sends it: a value-to-count map or a list of {value, count}. */
export type FacetCounts = Record<string, number> | { value: string | null; count: number }[];
export const FACETS = ["label", "provider", "model", "category", "source"] as const;
export type FacetKey = (typeof FACETS)[number];

export type TraceTotals = {
  traces: number;
  input_tokens: number | null;
  output_tokens: number | null;
  est_cost_usd: number | null;
  median_latency_ms: number | null;
  by_label: FacetCounts;
};
export type TraceList = {
  total: number;
  traces: TraceRow[];
  facets: Partial<Record<FacetKey, FacetCounts>>;
  totals: TraceTotals;
  live: "included" | "admin_only" | "unavailable";
  withheld: boolean;
};

/** Facet counts as [value, count] pairs, largest first, whichever form the API used. */
export function facetPairs(f: FacetCounts | undefined): [string, number][] {
  if (!f) return [];
  const pairs: [string, number][] = Array.isArray(f) ? f.filter((x) => x.value != null).map((x) => [String(x.value), x.count]) : Object.entries(f);
  return pairs.filter(([v]) => v !== "").sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

/** The row's token counts, read by name (input_tokens, output_tokens and the cache counts), in a stable order. */
export function tokenCounts(row: Record<string, unknown>): [string, number][] {
  return Object.entries(row)
    .filter((e): e is [string, number] => e[0].endsWith("_tokens") && typeof e[1] === "number")
    .sort((a, b) => a[0].localeCompare(b[0]));
}

export const tokenLabel = (key: string) => {
  const words = key.replace(/_tokens$/, "").replace(/_/g, " ");
  return `${words.charAt(0).toUpperCase()}${words.slice(1)}`;
};

export const toolErrorCount = (v: TraceRow["tool_errors"]) => (Array.isArray(v) ? v.length : typeof v === "number" ? v : 0);

/** "30 Sep 2026, 12:35" in IST, fixed so the server and the browser render the same text (no hydration mismatch). */
export function when(iso: string) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const zone = { timeZone: "Asia/Kolkata" } as const;
  return `${d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric", ...zone })}, ${d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false, ...zone })}`;
}

export const fmtLatency = (ms: number | null | undefined) =>
  ms == null ? "No value" : ms >= 10_000 ? `${(ms / 1000).toFixed(0)} s` : ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;

export const fmtUsd = (v: number | null | undefined) => (v == null ? "No value" : v === 0 ? "$0" : v < 0.01 ? `$${v.toFixed(4)}` : `$${v.toFixed(2)}`);

export const CATEGORY_TEXT: Record<string, string> = {
  simple_lookup: "Simple lookup",
  filtered_grouped: "Filtered and grouped",
  time_comparison: "Time comparison",
  multi_hop_why: "Multi-hop why",
  trap: "Trap",
};
export const categoryText = (c: string | null) => (c ? (CATEGORY_TEXT[c] ?? c.replace(/_/g, " ")) : "");
