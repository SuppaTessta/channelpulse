import { CheckCircle, HandPalm, SealCheck, SealWarning } from "@phosphor-icons/react/dist/ssr";
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
import { Badge, cx, ICON } from "../ui";

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

function TraceId({ id }: { id: string }) {
  return (
    <p className="flex flex-wrap items-center gap-x-2 text-xs text-muted">
      Trace <code className="font-mono text-subtle [overflow-wrap:anywhere]">{id}</code>
      <CopyButton text={id} label="Copy trace id" />
    </p>
  );
}

/** Shared frame for an answer: an outer tray and an inner plate, because the answer is the one elevated thing here. */
function Frame({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className="rounded-[14px] bg-hover p-1 ring-1 ring-line">
      <div className={cx("flex flex-col gap-4 rounded-panel bg-raised p-4 shadow-raised md:p-5", className)}>{children}</div>
    </div>
  );
}

export function AnswerHeader({ question, meta, badge }: { question: string; meta: string; badge?: ReactNode }) {
  return (
    <header className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        {badge}
        <span className="text-xs text-muted">{meta}</span>
      </div>
      <h3 className="text-[15px]/6 font-semibold text-ink">{question}</h3>
    </header>
  );
}

/** The five parts of an answer (DESIGN.md): text, chart from chart_spec, data table, label, and the confidence note with SQL and trace. */
export function Answer({ response, question, meta }: { response: AskResponse; question: string; meta: string }) {
  if (response.label === "refused") {
    return (
      <article className="flex flex-col gap-3 rounded-panel border border-l-4 border-line border-l-refused-edge bg-refused-soft p-4 md:p-5">
        <AnswerHeader question={question} meta={meta} badge={<LabelBadge label="refused" />} />
        <p className="max-w-[70ch] text-base/7 text-ink">{response.answer_text}</p>
        <p className="max-w-[70ch] text-sm text-muted">{response.confidence_note}</p>
        <p className="max-w-[70ch] text-sm text-muted">
          Declining is a normal outcome: the analyst only states figures it can trace to governed data in the marts.
        </p>
        <TraceId id={response.trace_id} />
      </article>
    );
  }
  const chart = buildAskChart(response);
  const data = response.data;
  return (
    <Frame>
      <AnswerHeader question={question} meta={meta} badge={<LabelBadge label={response.label} />} />
      <p className="max-w-[70ch] text-base/7 text-ink">{response.answer_text}</p>
      {response.label === "ad_hoc_sql_verify" ? (
        <p className="max-w-[70ch] rounded-control bg-adhoc-soft px-3 py-2 text-sm text-ink">
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
      <p className="flex items-start gap-2 text-sm text-ink">
        <CheckCircle size={18} {...ICON} className="mt-px shrink-0 text-accent" aria-hidden />
        <span>
          <span className="font-medium">Confidence note.</span> {response.confidence_note}
        </span>
      </p>
      {response.sql.length ? (
        <details className="group flex flex-col gap-2">
          <summary className="w-fit rounded-control text-sm font-medium text-ink underline decoration-line-strong underline-offset-4 hover:decoration-control">
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
        <div className="h-4 w-11/12 rounded-control bg-hover" />
        <div className="h-4 w-3/4 rounded-control bg-hover" />
        <div className="mt-2 h-40 w-full rounded-control bg-hover" />
      </div>
      {onCancel}
    </Frame>
  );
}
