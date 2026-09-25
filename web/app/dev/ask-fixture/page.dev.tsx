// Development-only story for the Ask answer view. Not a product page: pageExtensions leaves *.dev.tsx out of
// production builds. The API answers 503 "LLM not configured" on machines without an Anthropic key, so these
// hand-written responses are the only way to see a governed, ad-hoc or refused answer rendered locally.
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Answer } from "@/components/ask/answer";
import type { AskResponse } from "@/lib/ask";

export const metadata: Metadata = { title: "Ask fixtures (development only)" };

const SQL_GOVERNED = `SELECT
  DATE_TRUNC('month', invoice_date) AS metric_time__month
  , distributors_src_10000.region AS distributor__region
  , SUM(primary_sales_src_10000.primary_value_inr) AS primary_sales_value
FROM "marts"."fct_primary_sales" primary_sales_src_10000
WHERE DATE_TRUNC('day', invoice_date) BETWEEN '2026-04-01' AND '2026-06-30'
GROUP BY 1, 2
ORDER BY metric_time__month
LIMIT 500`;

// FIXTURE VALUES: invented for layout testing, not taken from the warehouse.
const FIXTURES: { title: string; question: string; response: AskResponse }[] = [
  {
    title: "Governed metric, line chart with a series column",
    question: "FIXTURE: How did primary sales move by region this quarter?",
    response: {
      answer_text: "FIXTURE TEXT. Primary sales value rose in all three regions shown across April to June, with South Bengal highest each month.",
      sql: [SQL_GOVERNED],
      data: {
        columns: ["metric_time__month", "distributor__region", "primary_sales_value"],
        rows: [
          ["2026-04-01T00:00:00+00:00", "South Bengal", 101000000],
          ["2026-04-01T00:00:00+00:00", "Assam", 52000000],
          ["2026-04-01T00:00:00+00:00", "Odisha", 43000000],
          ["2026-05-01T00:00:00+00:00", "South Bengal", 108000000],
          ["2026-05-01T00:00:00+00:00", "Assam", 55000000],
          ["2026-05-01T00:00:00+00:00", "Odisha", 44000000],
          ["2026-06-01T00:00:00+00:00", "South Bengal", 112000000],
          ["2026-06-01T00:00:00+00:00", "Assam", 58000000],
          ["2026-06-01T00:00:00+00:00", "Odisha", 47000000],
        ],
      },
      chart_spec: { type: "line", x: "metric_time__month", y: "primary_sales_value", series: "distributor__region" },
      label: "governed_metric",
      confidence_note: "FIXTURE NOTE. 3/3 figures traced to query results.",
      trace_id: "00000000-fixture-0000-0000-000000000001",
    },
  },
  {
    title: "Ad-hoc SQL, verify: bar chart over categories",
    question: "FIXTURE: Which installers have the most claims per 1,000 installs?",
    response: {
      answer_text: "FIXTURE TEXT. No governed metric ranks installers this way, so this is ad-hoc SQL: installer INS0000 leads the list.",
      sql: ["SELECT installer_id, round(1000.0 * sum(claims) / nullif(sum(units_installed), 0), 2) AS claims_per_1000\nFROM marts.mart_installer_claim_cohorts\nGROUP BY installer_id\nORDER BY claims_per_1000 DESC\nLIMIT 5"],
      data: {
        columns: ["installer_id", "claims_per_1000"],
        rows: [
          ["INS0000", 61.2],
          ["INS0001", 24.8],
          ["INS0002", 22.1],
          ["INS0003", 19.7],
          ["INS0004", 18.3],
        ],
      },
      chart_spec: { type: "bar", x: "installer_id", y: "claims_per_1000", series: null },
      label: "ad_hoc_sql_verify",
      confidence_note: "FIXTURE NOTE. 1/1 figure traced to query results.",
      trace_id: "00000000-fixture-0000-0000-000000000002",
    },
  },
  {
    title: "Chart hint that doesn't match the columns: table only, with the reason",
    question: "FIXTURE: List the five largest distributors by open receivables.",
    response: {
      answer_text: "FIXTURE TEXT. The five largest open balances are listed below.",
      sql: ["SELECT 1"],
      data: {
        columns: ["distributor", "open_receivables"],
        rows: [
          ["D0000", 4200000],
          ["D0001", 3900000],
          ["D0002", 3100000],
          ["D0003", 2800000],
          ["D0004", 2500000],
        ],
      },
      chart_spec: { type: "bar", x: "distributor__distributor_name", y: "open_receivables", series: null },
      label: "governed_metric",
      confidence_note: "FIXTURE NOTE. No figures stated, so there was nothing to trace.",
      trace_id: "00000000-fixture-0000-0000-000000000003",
    },
  },
  {
    title: "Refused, styled as a normal outcome",
    question: "FIXTURE: What will primary sales be next year?",
    response: {
      answer_text: "FIXTURE TEXT. I can't forecast future sales: the marts hold recorded history only, and every figure I give has to come from a query you can see.",
      sql: [],
      data: null,
      chart_spec: null,
      label: "refused",
      confidence_note: "Refused by the model; no figures reported.",
      trace_id: "00000000-fixture-0000-0000-000000000004",
    },
  },
];

export default function AskFixturePage() {
  if (process.env.NODE_ENV === "production") notFound();
  return (
    <div className="mx-auto flex max-w-[960px] flex-col gap-6 px-4 py-6 md:px-6">
      <header className="flex flex-col gap-2">
        <h1 className="text-lg font-semibold text-ink">Ask answer fixtures</h1>
        <p role="note" className="rounded-control border border-l-4 border-line border-l-[var(--adhoc)] bg-adhoc-soft px-3 py-2 text-sm text-ink">
          Development-only preview. Every response here is a hand-written fixture marked FIXTURE, not data from the API, and this route is not part of production builds.
        </p>
      </header>
      {FIXTURES.map((f) => (
        <section key={f.title} className="flex flex-col gap-2">
          <h2 className="text-xs font-medium text-muted">{f.title}</h2>
          <Answer response={f.response} question={f.question} meta="Fixture" />
        </section>
      ))}
    </div>
  );
}
