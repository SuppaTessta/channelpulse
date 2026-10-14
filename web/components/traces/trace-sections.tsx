import { CheckCircle, EyeSlash, ListMagnifyingGlass, LockKey, Wrench, XCircle } from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";
import type { ReactNode } from "react";
import { getTrace, getTraces, type Result } from "@/lib/api";
import { LABEL_TEXT, type AskLabel } from "@/lib/ask";
import { regionName, type Region } from "@/lib/config";
import { fmtNumber } from "@/lib/format";
import { categoryText, facetPairs, fmtLatency, fmtUsd, tokenCounts, tokenLabel, when, type TraceList } from "@/lib/traces";
import { LabelBadge } from "../ask/answer";
import { SqlBlock } from "../sql";
import { EmptyState, ErrorState } from "../states";
import { Badge, buttonClass, cx, Figure, ICON, Sheet, Skeleton } from "../ui";
import { TraceTable } from "./trace-table";

/** Label colours for the mix bar, the same family as each label's badge. The legend always carries the text. */
const LABEL_COLOR: Record<AskLabel, string> = {
  governed_metric: "var(--accent)",
  ad_hoc_sql_verify: "var(--adhoc)",
  refused: "var(--refused-edge)",
  needs_clarification: "var(--control-border)",
};

function Tile({ label, value, note, className }: { label: string; value: string; note?: ReactNode; className?: string }) {
  return (
    <div className={cx("flex min-w-0 flex-col gap-1.5 bg-surface p-4 md:p-5", className)}>
      <p className="text-[13px] font-medium text-muted">{label}</p>
      <Figure text={value} className="text-[26px]/8 font-semibold tracking-[-0.03em] text-ink md:text-[28px]/9" />
      {note ? <p className="text-xs text-subtle">{note}</p> : null}
    </div>
  );
}

function LabelMix({ pairs, className }: { pairs: [string, number][]; className?: string }) {
  const total = pairs.reduce((s, [, n]) => s + n, 0);
  return (
    <div className={cx("flex min-w-0 flex-col gap-3 bg-surface p-4 md:p-5", className)}>
      <p className="text-[13px] font-medium text-muted">Label mix</p>
      {total ? (
        <>
          <div aria-hidden className="flex h-2.5 w-full gap-0.5 overflow-hidden rounded-full">
            {pairs.map(([label, n]) => (
              <span key={label} style={{ flexGrow: n, background: LABEL_COLOR[label as AskLabel] ?? "var(--deemph)" }} />
            ))}
          </div>
          <ul className="grid grid-cols-1 gap-x-4 gap-y-1 text-xs sm:grid-cols-2 xl:grid-cols-1">
            {pairs.map(([label, n]) => (
              <li key={label} className="flex items-center gap-2">
                <span aria-hidden className="size-2.5 shrink-0 rounded-[2px]" style={{ background: LABEL_COLOR[label as AskLabel] ?? "var(--deemph)" }} />
                <span className="min-w-0 flex-1 truncate text-ink">{LABEL_TEXT[label as AskLabel] ?? label}</span>
                <span className="text-muted tabular-nums">
                  {fmtNumber(n)} <span className="text-subtle">({fmtNumber((n / total) * 100)}%)</span>
                </span>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="text-sm text-muted">No labelled traces</p>
      )}
    </div>
  );
}

const LIVE_NOTE: Record<TraceList["live"], { icon: ReactNode; text: string }> = {
  included: { icon: <CheckCircle size={16} {...ICON} className="text-accent" aria-hidden />, text: "Includes live traces: this server holds the admin token." },
  admin_only: {
    icon: <LockKey size={16} {...ICON} className="text-adhoc" aria-hidden />,
    text: "Recorded eval traces only. Live traces need the admin token, and this dashboard server doesn't have one, so none are listed.",
  },
  unavailable: { icon: <LockKey size={16} {...ICON} className="text-subtle" aria-hidden />, text: "Recorded eval traces only. This API has no live traces to show." },
};

/** The KPI strip over the filtered traces: count, tokens, median latency, cost and the label mix. */
export async function TraceSummary({ params, region }: { params: string; region: Region }) {
  const r = await getTraces(params, region);
  if (!r.ok) return <section aria-label="Trace totals" className="rounded-panel border border-line bg-surface px-4"><ErrorState error={r.error} /></section>;
  const t = r.value.totals;
  const tokens = (t.input_tokens ?? 0) + (t.output_tokens ?? 0);
  const live = LIVE_NOTE[r.value.live];
  return (
    <section aria-labelledby="trace-totals" className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id="trace-totals" className="text-sm font-semibold text-ink">
          Totals over the filtered traces
        </h2>
        <p className="flex items-center gap-1.5 text-xs text-muted">
          {live.icon}
          {live.text}
        </p>
      </div>
      <Sheet className="md:grid-cols-4 xl:grid-cols-6" dim={false}>
        <Tile label="Traces" value={fmtNumber(t.traces)} />
        <Tile
          label="Tokens"
          value={fmtNumber(tokens)}
          note={t.input_tokens != null && t.output_tokens != null ? `${fmtNumber(t.input_tokens)} in, ${fmtNumber(t.output_tokens)} out` : null}
        />
        <Tile label="Median latency" value={fmtLatency(t.median_latency_ms)} />
        <Tile label="Estimated cost" value={fmtUsd(t.est_cost_usd)} note="From the recorded token counts" />
        <LabelMix pairs={facetPairs(t.by_label)} className="md:col-span-4 xl:col-span-2" />
      </Sheet>
    </section>
  );
}

/** The page of traces with paging links; a withheld recording is explained instead, like the Ask replay. */
export async function TraceListPanel({
  params,
  region,
  offset,
  limit,
  pageQuery,
}: {
  params: string;
  region: Region;
  offset: number;
  limit: number;
  /** This page's own URL query (filters, region, offset), which the paging and trace links change one key of. */
  pageQuery: string;
}) {
  const link = (changes: Record<string, string | null>) => {
    const p = new URLSearchParams(pageQuery);
    for (const [k, v] of Object.entries(changes)) {
      if (v == null) p.delete(k);
      else p.set(k, v);
    }
    const qs = p.toString();
    return `/traces${qs ? `?${qs}` : ""}`;
  };
  const cleared = new URLSearchParams(pageQuery).get("region");
  const hrefWith = {
    clear: `/traces${cleared ? `?region=${encodeURIComponent(cleared)}` : ""}`,
    prev: link({ offset: offset - limit > 0 ? String(offset - limit) : null }),
    next: link({ offset: String(offset + limit) }),
  };
  const r: Result<TraceList> = await getTraces(params, region);
  if (!r.ok) {
    return (
      <section aria-label="Traces" className="rounded-panel border border-line bg-surface px-4 md:px-5">
        <ErrorState error={r.error} />
      </section>
    );
  }
  const { traces, total, withheld } = r.value;
  const empty = traces.length === 0;
  return (
    <section aria-labelledby="traces-heading" className="flex flex-col gap-4 rounded-panel border border-line bg-surface p-4 md:p-5" data-dim="">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="traces-heading" className="text-sm font-semibold text-ink">
          Traces
        </h2>
        <p className="text-xs text-muted">Open a question to see its tool calls, SQL, tokens and verdict.</p>
      </div>
      {withheld ? (
        <p className="flex items-start gap-2 rounded-control bg-sunken px-3 py-2 text-xs text-muted">
          <EyeSlash size={16} {...ICON} className="mt-px shrink-0" aria-hidden />
          The recorded eval traces were recorded viewing as All regions, so they are hidden under {regionName(region)}. View as All regions to list them.
        </p>
      ) : null}
      {empty ? (
        <EmptyState
          icon={<ListMagnifyingGlass size={20} {...ICON} aria-hidden />}
          title="No traces match these filters"
          body="Clear a filter or the search to widen the list."
          action={
            <Link href={hrefWith.clear} className={buttonClass("secondary", "sm")}>
              Clear all filters
            </Link>
          }
        />
      ) : (
        <>
          <TraceTable rows={traces} hrefFor={Object.fromEntries(traces.map((t) => [t.trace_id, link({ trace: t.trace_id })]))} />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-muted">
              Showing {fmtNumber(offset + 1)} to {fmtNumber(offset + traces.length)} of {fmtNumber(total)}
            </p>
            <div className="flex items-center gap-1">
              {offset > 0 ? (
                <Link href={hrefWith.prev} scroll={false} className={buttonClass("secondary", "sm")}>
                  Previous {fmtNumber(limit)}
                </Link>
              ) : null}
              {offset + traces.length < total ? (
                <Link href={hrefWith.next} scroll={false} className={buttonClass("secondary", "sm")}>
                  Next {fmtNumber(Math.min(limit, total - offset - traces.length))}
                </Link>
              ) : null}
            </div>
          </div>
        </>
      )}
    </section>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5 border-r border-b border-line px-3.5 py-2.5">
      <dt className="text-[11.5px] text-muted">{label}</dt>
      <dd className="min-w-0 text-sm text-ink [overflow-wrap:anywhere]">{children}</dd>
    </div>
  );
}

const json = (v: unknown) => (typeof v === "string" ? v : JSON.stringify(v, null, 2));

/** One trace: the question and answer, its measurements, the final SQL and every tool call in order. */
export async function TraceDetailView({ id, region }: { id: string; region: Region }) {
  const r = await getTrace(id, region);
  if (!r.ok) return <ErrorState error={r.error} className="px-5" />;
  const t = r.value;
  const tokens = tokenCounts(t);
  const failed = t.tool_calls.filter((c) => c.error != null).length;
  return (
    <div className="flex flex-col gap-6 px-5 py-5">
      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
          {t.label ? <LabelBadge label={t.label} /> : null}
          {t.error ? <Badge tone="danger">Error</Badge> : null}
          <span className="text-xs text-muted">
            {when(t.created_at)} IST, <span className="capitalize">{t.source}</span>
            {t.question_id ? `, ${t.question_id}` : ""}
            {t.category ? `, ${categoryText(t.category)}` : ""}
          </span>
        </div>
        <h3 className="text-[17px]/6 font-semibold tracking-[-0.01em] text-pretty text-ink">{t.question}</h3>
        {t.answer_text ? <p className="max-w-[70ch] text-[15px]/7 text-ink">{t.answer_text}</p> : null}
        {t.eval_correct != null ? (
          <p className={cx("flex items-center gap-1.5 text-xs", t.eval_correct ? "text-good" : "text-danger")}>
            {t.eval_correct ? <CheckCircle size={15} {...ICON} aria-hidden /> : <XCircle size={15} {...ICON} aria-hidden />}
            {t.eval_correct ? "The eval scored this answer correct." : "The eval scored this answer wrong."}
          </p>
        ) : null}
        {t.error ? <p className="rounded-control bg-danger-soft px-3 py-2 font-mono text-xs text-danger [overflow-wrap:anywhere]">{t.error}</p> : null}
      </section>

      <dl className="grid grid-cols-2 overflow-clip rounded-control border-t border-l border-line sm:grid-cols-3">
        <Fact label="Provider">{t.provider ?? "Not recorded"}</Fact>
        <Fact label="Model">
          <span className="font-mono text-[13px]">{t.served_model ?? t.model ?? "Not recorded"}</span>
        </Fact>
        <Fact label="Rows returned">{t.row_count != null ? fmtNumber(t.row_count) : "None"}</Fact>
        <Fact label="Latency">{fmtLatency(t.latency_ms)}</Fact>
        <Fact label="Estimated cost">{fmtUsd(t.est_cost_usd)}</Fact>
        <Fact label="Tool calls">
          {fmtNumber(t.tool_calls.length)}
          {failed ? <span className="text-danger">, {fmtNumber(failed)} failed</span> : null}
        </Fact>
        {tokens.map(([k, n]) => (
          <Fact key={k} label={`${tokenLabel(k)} tokens`}>
            {fmtNumber(n)}
          </Fact>
        ))}
      </dl>

      {t.final_sql.length ? (
        <section className="flex flex-col gap-2">
          <h4 className="text-sm font-semibold text-ink">{t.final_sql.length === 1 ? "Final SQL" : `Final SQL (${t.final_sql.length} queries)`}</h4>
          {t.final_sql.map((sql, i) => (
            <SqlBlock key={i} sql={sql} />
          ))}
        </section>
      ) : null}

      <section className="flex flex-col gap-3">
        <h4 className="text-sm font-semibold text-ink">Tool calls</h4>
        {t.tool_calls.length === 0 ? (
          <p className="text-sm text-muted">The analyst answered without calling a tool.</p>
        ) : (
          <ol className="flex flex-col gap-3">
            {t.tool_calls.map((c, i) => (
              <li key={c.id ?? i} className="flex flex-col gap-3 rounded-control border border-line bg-surface p-3.5">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="flex size-6 items-center justify-center rounded-full bg-sunken text-xs font-medium text-muted ring-1 ring-line ring-inset">{i + 1}</span>
                  <span className="inline-flex items-center gap-1.5 font-mono text-[13px] font-medium text-ink">
                    <Wrench size={14} {...ICON} className="text-subtle" aria-hidden />
                    {c.name}
                  </span>
                  <span className="ml-auto flex items-center gap-3 text-xs text-muted">
                    {c.row_count != null ? <span>{fmtNumber(c.row_count)} rows</span> : null}
                    {c.duration_ms != null ? <span>{fmtLatency(c.duration_ms)}</span> : null}
                    {c.error ? <Badge tone="danger">Failed</Badge> : null}
                  </span>
                </div>
                {c.input != null && c.input !== "" ? (
                  <details className="group">
                    <summary className="w-fit text-xs text-muted underline decoration-line-strong underline-offset-4 hover:text-ink">Input</summary>
                    <pre className="mt-2 max-h-60 overflow-auto rounded-control bg-sunken p-3 font-mono text-[12px]/5 text-ink">{json(c.input)}</pre>
                  </details>
                ) : null}
                {c.sql ? <SqlBlock sql={c.sql} /> : null}
                {c.output ? (
                  <div className="flex flex-col gap-1">
                    <p className="text-xs text-muted">Output, first 300 characters</p>
                    <pre className="max-h-40 overflow-auto rounded-control bg-sunken p-3 font-mono text-[12px]/5 whitespace-pre-wrap text-ink">{c.output}</pre>
                  </div>
                ) : null}
                {c.error ? <p className="rounded-control bg-danger-soft px-3 py-2 font-mono text-xs text-danger [overflow-wrap:anywhere]">{c.error}</p> : null}
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}

export function TraceDetailSkeleton() {
  return (
    <div aria-busy="true" className="flex flex-col gap-4 px-5 py-5">
      <span className="sr-only">Loading the trace</span>
      <Skeleton className="h-6 w-40" />
      <Skeleton className="h-6 w-4/5" />
      <Skeleton className="h-20 w-full" />
      <Skeleton className="h-40 w-full" />
    </div>
  );
}

export function TraceSummarySkeleton() {
  return (
    <div aria-busy="true" className="flex flex-col gap-2">
      <span className="sr-only">Loading trace totals</span>
      <Skeleton className="h-4 w-56" />
      <Skeleton className="h-[116px] w-full rounded-panel" />
    </div>
  );
}
