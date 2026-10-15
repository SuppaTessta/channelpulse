import { CaretRight, ChatCircleDots, CheckCircle, HandPalm, SealCheck, SealWarning } from "@phosphor-icons/react/dist/ssr";
import type { ReactNode } from "react";
import { buildAskChart, LABEL_TEXT, type AskResponse } from "@/lib/ask";
import { toISODate } from "@/lib/dates";
import { fmtDate, fmtMonth, formatValue } from "@/lib/format";
import { metricKind } from "@/lib/metrics";
import { num } from "@/lib/table";
import { BarList } from "../charts/bar-list";
import { TimeChart } from "../charts/time-chart";
import { CopyButton } from "../copy-button";
import { DataTable } from "../data-table";
import { SqlBlock } from "../sql";
import { Badge, cx, ICON, TYPE } from "../ui";

export function LabelBadge({ label }: { label: AskResponse["label"] }) {
  if (label === "governed_metric") {
    return (
      <Badge tone="governed" icon={<SealCheck size={14} {...ICON} aria-hidden />}>
        {LABEL_TEXT[label]}
      </Badge>
    );
  }
  if (label === "ad_hoc_sql_verify") {
    return (
      <Badge tone="adhoc" icon={<SealWarning size={14} {...ICON} aria-hidden />}>
        {LABEL_TEXT[label]}
      </Badge>
    );
  }
  if (label === "needs_clarification") {
    return (
      <Badge tone="neutral" icon={<ChatCircleDots size={14} {...ICON} aria-hidden />}>
        {LABEL_TEXT[label]}
      </Badge>
    );
  }
  return (
    <Badge tone="refused" icon={<HandPalm size={14} {...ICON} aria-hidden />}>
      {LABEL_TEXT[label]}
    </Badge>
  );
}

/** A formatter per column: metric-aware numbers, and dates at their grain (a column of month starts reads "Apr 2026"). */
function columnFormatter(column: string, values: unknown[]): (v: unknown) => string {
  const dates = values.map((v) => (typeof v === "string" && v.length >= 10 ? toISODate(v) : null));
  const isDate = values.every((v, i) => v == null || dates[i]);
  const monthly = isDate && dates.every((d) => !d || d.endsWith("-01"));
  return (v) => {
    if (v == null) return "";
    const n = num(v);
    if (n != null) return formatValue(metricKind(column), n);
    const d = isDate && typeof v === "string" ? toISODate(v) : null;
    return d ? (monthly ? fmtMonth(d) : fmtDate(d)) : String(v);
  };
}

function TraceId({ id, className }: { id: string; className?: string }) {
  return (
    <p className={cx("flex flex-wrap items-center gap-x-2 text-xs text-muted", className)}>
      Trace <code className="font-mono text-subtle [overflow-wrap:anywhere]">{id}</code>
      <CopyButton text={id} label="Copy trace id" />
    </p>
  );
}

/** The plate's edge light names the answer's family: teal for governed, amber for ad hoc, plain while pending. */
const GLOW = {
  governed: "shadow-[var(--glow-accent)]",
  adhoc: "shadow-[0_0_0_1px_color-mix(in_oklab,var(--adhoc)_40%,transparent),0_0_24px_-6px_color-mix(in_oklab,var(--adhoc)_45%,transparent)]",
  plain: "shadow-raised",
};

/** Shared frame for an answer: an outer tray and an inner glass plate, because the answer is the one elevated thing here. */
function Frame({ children, className, glow = "plain" }: { children: ReactNode; className?: string; glow?: keyof typeof GLOW }) {
  return (
    <div className="rounded-[16px] bg-sunken p-1 ring-1 ring-line">
      <div className={cx("cp-reveal flex flex-col gap-5 rounded-panel border border-line-strong/70 bg-raised/90 p-4 backdrop-blur-xl md:p-6", GLOW[glow], className)}>
        {children}
      </div>
    </div>
  );
}

export function AnswerHeader({ question, meta, badge }: { question: string; meta: string; badge?: ReactNode }) {
  return (
    <header className="flex flex-col gap-2.5">
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
        {badge}
        <span className="text-xs text-muted">{meta}</span>
      </div>
      <h3 className={TYPE.question}>{question}</h3>
    </header>
  );
}

/**
 * The answers that state no figures (refused, needs clarification): plain, on a neutral surface, with a left edge
 * that names the outcome's family. Declining and asking back are normal outcomes, not errors.
 */
function NoFigures({ response, question, meta, edge, children }: { response: AskResponse; question: string; meta: string; edge: string; children: ReactNode }) {
  return (
    <article className={cx("cp-reveal flex flex-col gap-3 rounded-panel border border-l-[3px] border-line bg-refused-soft p-4 md:p-6", edge)}>
      <AnswerHeader question={question} meta={meta} badge={<LabelBadge label={response.label} />} />
      <p className="max-w-[70ch] font-display text-[18px]/[30px] text-ink">{response.answer_text}</p>
      {children}
      <TraceId id={response.trace_id} className="border-t border-line pt-3" />
    </article>
  );
}

/** The five parts of an answer (DESIGN.md): text, chart from chart_spec, data table, label, and the confidence note with SQL and trace. */
export function Answer({ response, question, meta }: { response: AskResponse; question: string; meta: string }) {
  if (response.label === "refused") {
    return (
      <NoFigures response={response} question={question} meta={meta} edge="border-l-refused-edge">
        <p className="max-w-[70ch] text-sm text-muted">{response.confidence_note}</p>
        <p className="max-w-[70ch] text-sm text-muted">
          Declining is a normal outcome: the analyst only states figures it can trace to governed data in the marts.
        </p>
      </NoFigures>
    );
  }
  if (response.label === "needs_clarification") {
    return (
      <NoFigures response={response} question={question} meta={meta} edge="border-l-control">
        <p className="max-w-[70ch] text-sm text-muted">
          {response.confidence_note} Ask again with the reading you mean.
        </p>
      </NoFigures>
    );
  }
  const chart = buildAskChart(response);
  const data = response.data;
  return (
    <Frame glow={response.label === "governed_metric" ? "governed" : "adhoc"}>
      <AnswerHeader question={question} meta={meta} badge={<LabelBadge label={response.label} />} />
      <p className="max-w-[70ch] font-display text-[18px]/[30px] text-ink">{response.answer_text}</p>
      {response.label === "ad_hoc_sql_verify" ? (
        <p className="flex max-w-[70ch] items-start gap-2 rounded-control bg-adhoc-soft px-3 py-2.5 text-sm text-ink">
          <SealWarning size={18} {...ICON} className="mt-px shrink-0 text-adhoc" aria-hidden />
          No governed metric covered this question, so the analyst wrote read-only SQL against the marts. Check the query below before relying on it.
        </p>
      ) : null}
      {chart.kind === "time" ? (
        <TimeChart buckets={chart.buckets} series={chart.series} mark={chart.mark} kind={chart.valueKind} height={240} title={`${chart.y} by ${chart.x}`} grain={chart.grain} />
      ) : chart.kind === "category" ? (
        <BarList rows={chart.rows} series={chart.series} kind={chart.valueKind} title={`${chart.y} by ${chart.x}`} />
      ) : chart.reason ? (
        <p className="text-xs text-subtle">{chart.reason}</p>
      ) : null}
      {data && data.rows.length ? (
        <div className="flex flex-col gap-1.5">
          <p className="text-xs text-muted">
            {data.rows.length} {data.rows.length === 1 ? "row" : "rows"} returned
          </p>
          <DataTable
            caption={`Data behind the answer to: ${question}`}
            columns={data.columns.map((c, i) => ({ label: c, numeric: data.rows.every((r) => r[i] == null || num(r[i]) != null) }))}
            rows={(() => {
              const format = data.columns.map((c, i) => columnFormatter(c, data.rows.map((r) => r[i])));
              return data.rows.map((r) => r.map((v, i) => format[i](v)));
            })()}
            maxHeight="max-h-[320px]"
          />
        </div>
      ) : null}
      <div className="-mx-4 -mb-4 flex flex-col gap-3 rounded-b-panel border-t border-line bg-surface px-4 py-4 md:-mx-6 md:-mb-6 md:px-6">
        <p className="flex items-start gap-2 text-sm text-ink">
          <CheckCircle size={18} {...ICON} className="mt-px shrink-0 text-accent" aria-hidden />
          <span>
            <span className="font-medium">Confidence note.</span> {response.confidence_note}
          </span>
        </p>
        {response.sql.length ? (
          <details className="group flex flex-col gap-2">
            <summary className="flex w-fit list-none items-center gap-1.5 rounded-control text-sm font-medium text-ink hover:text-accent [&::-webkit-details-marker]:hidden">
              <CaretRight size={14} {...ICON} weight="bold" className="transition-transform duration-150 ease-out group-open:rotate-90" aria-hidden />
              {response.sql.length === 1 ? "Show the SQL" : `Show the ${response.sql.length} SQL queries`}
            </summary>
            <div className="mt-2 flex flex-col gap-3">
              {response.sql.map((s, i) => (
                <SqlBlock key={i} sql={s} />
              ))}
            </div>
          </details>
        ) : null}
        <TraceId id={response.trace_id} />
      </div>
    </Frame>
  );
}

export function PendingAnswer({ question, meta, onCancel }: { question: string; meta: string; onCancel?: ReactNode }) {
  return (
    <Frame className="gap-3">
      <AnswerHeader question={question} meta={meta} />
      <p className="text-sm text-muted">
        Working on it. The analyst checks the governed metrics first, runs its queries, then writes the answer. This can take a minute or two.
      </p>
      <div aria-hidden className="flex flex-col gap-2">
        <div className="h-4 w-11/12 rounded-control bg-sunken" />
        <div className="h-4 w-3/4 rounded-control bg-sunken" />
        <div className="mt-2 h-40 w-full rounded-control bg-sunken" />
      </div>
      {onCancel}
    </Frame>
  );
}
