import { WarningDiamond } from "@phosphor-icons/react/dist/ssr";
import { query, queryAll, type Anomaly, type DataWindow, type Filter, type Metric, type Result } from "@/lib/api";
import type { Region } from "@/lib/config";
import { fmtDate, fmtRange, formatValue } from "@/lib/format";
import { fallbackMetric, metricKind, shortLabel, toDefMetric, toDefQuery } from "@/lib/metrics";
import type { Period } from "@/lib/params";
import { alignSeries, coverageText, timeBuckets } from "@/lib/series";
import { num, records, scalar, str } from "@/lib/table";
import { ChartPanel } from "./chart-panel";
import { TimeChart } from "./charts/time-chart";
import { DataTable } from "./data-table";
import { DefinitionButton } from "./definition";
import { InfoTip } from "./info-tip";
import { EmptyState, ErrorState } from "./states";
import { Badge, ICON } from "./ui";

type Ctx = { period: Period; win: DataWindow; region: Region; catalog: Result<Record<string, Metric>>; filters: Filter[] };
const metricOf = (catalog: Ctx["catalog"], name: string) => (catalog.ok ? catalog.value[name] : undefined) ?? fallbackMetric(name);

export const HEALTH = "distributor_health_score";
const COMPONENTS = ["health_secondary_trend_score", "health_gap_score", "health_stock_score", "health_dso_score", "health_visit_score"];

/** The at-risk score line, read from the governed at_risk_distributors definition ("score < 30 ..."), if it states one. */
function riskThreshold(catalog: Ctx["catalog"]): number | null {
  const m = catalog.ok ? catalog.value.at_risk_distributors?.description.match(/score\s*<\s*(\d+)/) : null;
  return m ? Number(m[1]) : null;
}

const flagWeek = (a: Anomaly) => String((a.details?.week_start as string | undefined) ?? a.snapshot_date).slice(0, 10);

export async function HealthPanel({ ctx, flag, pastFlag, className }: { ctx: Ctx; flag: Anomaly | undefined; pastFlag: Anomaly | undefined; className?: string }) {
  const names = [HEALTH, ...COMPONENTS];
  const title = "Distributor health score";
  const r = await queryAll(
    names.map((name) => ({ metric_name: name, filters: ctx.filters, group_by: ["metric_time__week"], date_range: { start: ctx.period.range.from, end: ctx.period.range.to } })),
    ctx.region,
  );
  const buckets = timeBuckets("week", ctx.period.range, ctx.win);
  const subtitle = `Weekly, 0 to 100, higher is healthier, ${coverageText(buckets, ctx.period.range, ctx.win, "week")}`;
  if (!r.ok) return <ChartPanel id="health" title={title} subtitle={subtitle} className={className} chart={<ErrorState compact error={r.error} />} />;

  const series = names.map((name, i) => ({
    key: name,
    label: shortLabel(metricOf(ctx.catalog, name).label),
    slot: 1 as const,
    values: alignSeries(buckets, r.value[i], "metric_time__week", name, false),
    horizonBound: false,
  }));
  const definition = <DefinitionButton title={title} metrics={names.map((n) => toDefMetric(metricOf(ctx.catalog, n)))} queries={r.value.map((q, i) => toDefQuery(q, `${series[i].label} by week`))} />;
  const scored = series[0].values.findLastIndex((v) => v != null);
  if (scored < 0) {
    return (
      <ChartPanel
        id="health"
        title={title}
        subtitle={subtitle}
        actions={definition}
        className={className}
        chart={<EmptyState title="No scored weeks in this range" body="The score needs 52 weeks of history before a distributor is scored. Try a later or longer range." />}
      />
    );
  }
  const threshold = riskThreshold(ctx.catalog);
  const weight = (name: string) => metricOf(ctx.catalog, name).description.match(/weight (\d+%)/)?.[1];

  return (
    <ChartPanel
      id="health"
      title={title}
      subtitle={subtitle}
      actions={definition}
      className={className}
      chart={
        <div className="flex flex-col gap-5">
          <div className="grid gap-5 lg:grid-cols-[220px_1fr]">
            <div className="flex flex-col gap-2">
              <p className="text-[52px]/none font-semibold tracking-tight text-ink">{formatValue("score", series[0].values[scored])}</p>
              <p className="text-sm text-muted">{buckets[scored].label}</p>
              {flag ? (
                <Badge tone="danger" className="w-fit" icon={<WarningDiamond size={14} {...ICON} aria-hidden />}>
                  At risk since {flag.first_flag_date ? fmtDate(String(flag.first_flag_date).slice(0, 10)) : "this snapshot"}
                </Badge>
              ) : pastFlag ? (
                <p className="text-xs text-muted">Not at risk now. The detector last flagged it in the week of {fmtDate(flagWeek(pastFlag))}.</p>
              ) : (
                <p className="text-xs text-subtle">The distributor-health detector has never flagged it.</p>
              )}
              <p className="max-w-[40ch] text-xs text-muted">{metricOf(ctx.catalog, HEALTH).description}</p>
            </div>
            <TimeChart
              buckets={buckets}
              series={[series[0]]}
              mark="line"
              kind="score"
              yDomain={[0, 100]}
              height={220}
              title={title}
              grain="week"
              refLine={threshold != null ? { value: threshold, label: `Score ${threshold}: an at-risk condition` } : undefined}
            />
          </div>
          <div>
            <h3 className="mb-2 text-xs font-medium text-muted">Components: percentile among region peers, weighted into the score</h3>
            <div className="grid grid-cols-1 gap-px overflow-clip rounded-control border border-line bg-line sm:grid-cols-2 lg:grid-cols-5">
              {series.slice(1).map((s, i) => (
                <div key={s.key} className="flex min-w-0 flex-col gap-1 bg-surface p-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate text-xs font-medium text-ink" title={s.label}>
                      {s.label}
                    </p>
                    <span className="shrink-0 text-xs text-subtle">{weight(COMPONENTS[i]) ?? ""}</span>
                  </div>
                  <TimeChart buckets={buckets} series={[s]} mark="line" kind="score" yDomain={[0, 100]} height={104} title={s.label} grain="week" footnote={false} />
                </div>
              ))}
            </div>
          </div>
        </div>
      }
      table={
        <DataTable
          caption={`${title} and its components by week`}
          columns={[{ label: "Week" }, ...series.map((s) => ({ label: s.label, numeric: true }))]}
          rows={buckets.map((b, i) => [b.label, ...series.map((s) => formatValue("score", s.values[i]))])}
        />
      }
    />
  );
}

/** Current receivables: all invoices, open amounts aged to the as-of date. Not limited to the date range. */
export async function Receivables({ ctx }: { ctx: Ctx }) {
  const names = ["open_receivables", "overdue_receivables"];
  const r = await queryAll(names.map((name) => ({ metric_name: name, filters: ctx.filters })), ctx.region);
  if (!r.ok) return <ErrorState compact error={r.error} />;
  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-2 gap-px overflow-clip rounded-control border border-line bg-line">
        {names.map((name, i) => {
          const m = metricOf(ctx.catalog, name);
          return (
            <div key={name} className="bg-surface p-3">
              <p className="text-xs text-muted">{shortLabel(m.label)}</p>
              <p className="text-xl font-semibold text-ink">{formatValue("inr", scalar(r.value[i].result.data, name))}</p>
            </div>
          );
        })}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-subtle">All invoices as of {fmtDate(ctx.win.asOf)}, whatever the date range.</p>
        <DefinitionButton
          title="Receivables"
          metrics={names.map((n) => toDefMetric(metricOf(ctx.catalog, n)))}
          queries={r.value.map((q, i) => toDefQuery(q, shortLabel(metricOf(ctx.catalog, names[i]).label)))}
        />
      </div>
    </div>
  );
}

const SCHEME = ["stuffing_rate_ratio", "scheme_concentration_ratio", "stuffing_flags"];
const QUARTER = "distributor_scheme_window__fiscal_quarter_label";
const CATEGORY = "distributor_scheme_window__category";
const COMPLETE = "distributor_scheme_window__is_window_complete";

export async function SchemePanel({ ctx, className }: { ctx: Ctx; className?: string }) {
  const title = "Scheme participation";
  const subtitle = `Quarter-end scheme windows starting ${fmtRange(ctx.period.range)}`;
  const r = await queryAll(
    SCHEME.map((name) => ({ metric_name: name, filters: ctx.filters, group_by: [QUARTER, CATEGORY, COMPLETE], date_range: { start: ctx.period.range.from, end: ctx.period.range.to } })),
    ctx.region,
  );
  if (!r.ok) return <ChartPanel id="scheme" title={title} subtitle={subtitle} className={className} chart={<ErrorState compact error={r.error} />} />;

  const rows = new Map<string, { quarter: string; category: string; open: boolean; values: (number | null)[] }>();
  r.value.forEach((q, i) => {
    for (const rec of records(q.result.data)) {
      const quarter = str(rec[QUARTER]) ?? "";
      const category = str(rec[CATEGORY]) ?? "";
      const key = `${quarter}|${category}`;
      const row = rows.get(key) ?? { quarter, category, open: rec[COMPLETE] === false, values: [null, null, null] };
      row.values[i] = num(rec[SCHEME[i]]);
      rows.set(key, row);
    }
  });
  const sorted = [...rows.values()].sort((a, b) => b.quarter.localeCompare(a.quarter) || a.category.localeCompare(b.category));
  const metrics = SCHEME.map((n) => metricOf(ctx.catalog, n));
  const definition = <DefinitionButton title={title} metrics={metrics.map(toDefMetric)} queries={r.value.map((q, i) => toDefQuery(q, `${shortLabel(metrics[i].label)} by quarter and category`))} />;
  const head = (i: number) => (
    <span className="inline-flex items-center gap-0.5">
      {shortLabel(metrics[i].label)}
      {metrics[i].description ? <InfoTip label={`Definition of ${shortLabel(metrics[i].label)}`}>{metrics[i].description}</InfoTip> : null}
    </span>
  );

  return (
    <ChartPanel
      id="scheme"
      title={title}
      subtitle={subtitle}
      actions={definition}
      className={className}
      chart={
        sorted.length === 0 ? (
          <EmptyState title="No scheme windows in this range" body="This distributor had no scheme window starting in the selected dates. Try a longer range." />
        ) : (
          <div className="-mx-4 overflow-x-auto md:mx-0">
            <table className="w-full min-w-[560px] border-collapse text-[13px]">
              <caption className="sr-only">{title} by fiscal quarter and category</caption>
              <thead>
                <tr className="text-xs text-muted">
                  <th scope="col" className="border-b border-line px-3 py-2 text-left font-medium">
                    Quarter
                  </th>
                  <th scope="col" className="border-b border-line px-3 py-2 text-left font-medium">
                    Category
                  </th>
                  {[0, 1].map((i) => (
                    <th key={i} scope="col" className="border-b border-line px-3 py-2 text-right font-medium">
                      {head(i)}
                    </th>
                  ))}
                  <th scope="col" className="border-b border-line px-3 py-2 text-left font-medium">
                    {head(2)}
                  </th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((row) => (
                  <tr key={`${row.quarter}|${row.category}`} className="border-b border-line last:border-0">
                    <td className="px-3 py-2 whitespace-nowrap text-ink">
                      {row.quarter}
                      {row.open ? <span className="block text-xs text-subtle">Window still open</span> : null}
                    </td>
                    <td className="px-3 py-2 text-muted capitalize">{row.category}</td>
                    <td className="px-3 py-2 text-right text-ink">{formatValue(metricKind(SCHEME[0]), row.values[0])}</td>
                    <td className="px-3 py-2 text-right text-ink">{formatValue(metricKind(SCHEME[1]), row.values[1])}</td>
                    <td className="px-3 py-2">
                      {(row.values[2] ?? 0) > 0 ? (
                        <Badge tone="danger" icon={<WarningDiamond size={12} {...ICON} aria-hidden />}>
                          Flagged
                        </Badge>
                      ) : (
                        <span className="text-muted">Not flagged</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      }
    />
  );
}

export type Profile = { id: string; name: string; region: string; tier: string; district: string; state: string; rep: string; status: string };

export const PROFILE_DIMENSIONS = [
  "distributor",
  "distributor__distributor_name",
  "distributor__region",
  "distributor__tier",
  "distributor__district",
  "distributor__state",
  "distributor__rep_name",
  "distributor__distributor_status",
];

export async function loadProfile(id: string, region: Region) {
  const r = await query({ metric_name: "primary_sales_value", filters: [{ dimension: "distributor", op: "=", value: id }], group_by: PROFILE_DIMENSIONS }, region);
  if (!r.ok) return r;
  const rec = records(r.value.result.data)[0];
  const profile: Profile | null = rec
    ? {
        id: str(rec.distributor) ?? id,
        name: str(rec.distributor__distributor_name) ?? id,
        region: str(rec.distributor__region) ?? "",
        tier: str(rec.distributor__tier) ?? "",
        district: str(rec.distributor__district) ?? "",
        state: str(rec.distributor__state) ?? "",
        rep: str(rec.distributor__rep_name) ?? "",
        status: str(rec.distributor__distributor_status) ?? "",
      }
    : null;
  return { ok: true as const, value: { profile, query: r.value } };
}

export function ProfileFacts({ profile, flag, pastFlag }: { profile: Profile; flag: Anomaly | undefined; pastFlag: Anomaly | undefined }) {
  const facts: [string, string][] = [
    ["District", profile.district],
    ["State", profile.state],
    ["Sales rep", profile.rep],
  ];
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-subtle">{profile.id}</span>
        <Badge tone="neutral">{profile.region}</Badge>
        {profile.tier ? <Badge tone="neutral">{/^\d+$/.test(profile.tier) ? `Tier ${profile.tier}` : profile.tier}</Badge> : null}
        {profile.status && profile.status.toLowerCase() !== "active" ? <Badge tone="neutral">{profile.status}</Badge> : null}
        {flag ? (
          <Badge tone="danger" icon={<WarningDiamond size={12} {...ICON} aria-hidden />}>
            At risk
          </Badge>
        ) : pastFlag ? (
          <Badge tone="neutral">Flagged at risk in the week of {fmtDate(flagWeek(pastFlag))}</Badge>
        ) : null}
      </div>
      <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
        {facts
          .filter(([, v]) => v)
          .map(([k, v]) => (
            <div key={k} className="flex gap-2">
              <dt className="text-muted">{k}</dt>
              <dd className="text-ink">{v}</dd>
            </div>
          ))}
      </dl>
    </div>
  );
}

