"use client";

import { CaretDown, CaretUp, CheckCircle, Minus, WarningCircle, XCircle } from "@phosphor-icons/react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { fmtNumber } from "@/lib/format";
import { categoryText, fmtLatency, fmtUsd, tokenCounts, toolErrorCount, when, type TraceRow } from "@/lib/traces";
import { LabelBadge } from "../ask/answer";
import { Badge, cx, ICON } from "../ui";

type SortKey = "created_at" | "tokens" | "latency_ms" | "est_cost_usd";

const tokensOf = (r: TraceRow) => tokenCounts(r).reduce((sum, [, n]) => sum + n, 0);
const value = (r: TraceRow, key: SortKey) => (key === "tokens" ? tokensOf(r) : key === "created_at" ? r.created_at : (r[key] ?? -Infinity));


function Verdict({ correct }: { correct: boolean | null }) {
  if (correct == null)
    return (
      <span className="text-subtle">
        <Minus size={15} {...ICON} aria-hidden />
        <span className="sr-only">Not scored</span>
      </span>
    );
  const Icon = correct ? CheckCircle : XCircle;
  return (
    <span className={correct ? "text-good" : "text-danger"}>
      <Icon size={16} {...ICON} weight={correct ? "light" : "regular"} aria-hidden />
      <span className="sr-only">{correct ? "Scored correct" : "Scored wrong"}</span>
    </span>
  );
}

/** The page of traces, sortable in place. Each question opens the trace's drawer (?trace=), keeping the filters. */
export function TraceTable({ rows, hrefFor }: { rows: TraceRow[]; hrefFor: Record<string, string> }) {
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 } | null>(null);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    return [...rows].sort((a, b) => {
      const x = value(a, sort.key), y = value(b, sort.key);
      return (x < y ? -1 : x > y ? 1 : 0) * sort.dir;
    });
  }, [rows, sort]);

  const header = (key: SortKey, label: string) => {
    const active = sort?.key === key;
    return (
      <th scope="col" aria-sort={active ? (sort.dir === 1 ? "ascending" : "descending") : "none"} className={cx("px-3 py-1.5 font-medium", key === "created_at" ? "text-left" : "text-right")}>
        <button
          type="button"
          onClick={() => setSort((s) => ({ key, dir: s?.key === key ? (s.dir === 1 ? -1 : 1) : -1 }))}
          className={cx("-mx-1 inline-flex h-8 items-center gap-1 rounded-control px-1 text-xs hover:text-ink", active ? "text-ink" : "text-muted", key !== "created_at" && "flex-row-reverse")}
        >
          {label}
          {active ? sort.dir === 1 ? <CaretUp size={12} {...ICON} aria-hidden /> : <CaretDown size={12} {...ICON} aria-hidden /> : null}
        </button>
      </th>
    );
  };
  const plain = (label: string, right = false) => (
    <th scope="col" className={cx("px-3 py-1.5 text-xs font-medium whitespace-nowrap text-muted", right ? "text-right" : "text-left")}>
      {label}
    </th>
  );

  return (
    <div className="-mx-4 overflow-x-auto md:mx-0 md:rounded-control md:border md:border-line">
      <table className="w-full min-w-[1040px] border-collapse text-[13px]">
        <caption className="sr-only">Agent traces, {rows.length} rows on this page</caption>
        <thead className="border-b border-line bg-sunken">
          <tr>
            {header("created_at", "When, IST")}
            {plain("Question")}
            {plain("Label")}
            {plain("Model")}
            {header("tokens", "Tokens")}
            {header("latency_ms", "Latency")}
            {header("est_cost_usd", "Est. cost")}
            {plain("Tools", true)}
            {plain("Eval")}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => {
            const errors = toolErrorCount(r.tool_errors);
            const tokens = tokenCounts(r);
            return (
              <tr key={r.trace_id} className="relative border-b border-line align-top transition-colors duration-150 last:border-0 hover:bg-hover">
                <td className="px-3 py-2.5 whitespace-nowrap">
                  <span className="text-ink">{when(r.created_at)}</span>
                  <span className="block text-xs text-subtle capitalize">{r.source}</span>
                </td>
                <td className="max-w-[420px] px-3 py-2.5">
                  <Link href={hrefFor[r.trace_id]} scroll={false} className="line-clamp-2 font-medium text-ink after:absolute after:inset-0 after:content-[''] hover:underline hover:underline-offset-4">
                    {r.question}
                  </Link>
                  <span className="mt-0.5 block text-xs text-subtle">
                    {[r.question_id, categoryText(r.category)].filter(Boolean).join(", ")}
                  </span>
                </td>
                <td className="px-3 py-2.5">
                  {r.error ? (
                    <Badge tone="danger" icon={<WarningCircle size={14} {...ICON} aria-hidden />}>
                      Error
                    </Badge>
                  ) : r.label ? (
                    <LabelBadge label={r.label} />
                  ) : (
                    <span className="text-xs text-subtle">No label</span>
                  )}
                </td>
                <td className="px-3 py-2.5">
                  <span className="font-mono text-xs whitespace-nowrap text-ink">{r.served_model ?? r.model ?? ""}</span>
                  <span className="block text-xs text-subtle">{r.provider}</span>
                </td>
                <td className="px-3 py-2.5 text-right whitespace-nowrap" title={tokens.map(([k, n]) => `${k}: ${fmtNumber(n)}`).join(", ")}>
                  <span className="text-ink">{tokens.length ? fmtNumber(tokensOf(r)) : ""}</span>
                  {typeof r.input_tokens === "number" && typeof r.output_tokens === "number" ? (
                    <span className="block text-xs text-subtle">
                      {fmtNumber(r.input_tokens)} in, {fmtNumber(r.output_tokens)} out
                    </span>
                  ) : null}
                </td>
                <td className="px-3 py-2.5 text-right whitespace-nowrap text-ink">{fmtLatency(r.latency_ms)}</td>
                <td className="px-3 py-2.5 text-right whitespace-nowrap text-ink">{fmtUsd(r.est_cost_usd)}</td>
                <td className="px-3 py-2.5 text-right whitespace-nowrap">
                  <span className="text-ink">{fmtNumber(r.tools?.length ?? 0)}</span>
                  {errors ? <span className="block text-xs text-danger">{errors === 1 ? "1 error" : `${fmtNumber(errors)} errors`}</span> : null}
                </td>
                <td className="px-3 py-2.5">
                  <Verdict correct={r.eval_correct} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
