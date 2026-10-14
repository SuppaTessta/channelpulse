import { ArrowDownRight, ArrowUpRight, Database, Minus, WarningCircle } from "@phosphor-icons/react/dist/ssr";
import { query, type DataWindow, type Metric, type Query, type Result } from "@/lib/api";
import type { Region } from "@/lib/config";
import { daysBetween, type Grain } from "@/lib/dates";
import { fmtDate, fmtDayMonth, fmtRange, formatDelta, formatValue } from "@/lib/format";
import { fallbackMetric, GOOD_DIRECTION, isCohortTimed, isHorizonBound, metricKind, shortLabel, toDefMetric, toDefQuery } from "@/lib/metrics";
import type { Period } from "@/lib/params";
import { alignSeries, timeBuckets } from "@/lib/series";
import { scalar } from "@/lib/table";
import { DefinitionButton } from "./definition";
import { InfoTip } from "./info-tip";
import { Sparkline } from "./sparkline";
import { describeError, ErrorState } from "./states";
import { cx, Figure, ICON, Sheet, Skeleton, TYPE } from "./ui";

const KPI_METRICS = ["primary_sales_value", "secondary_sales_value", "channel_days_of_stock", "claims_per_1000_units", "dso"];

type Ctx = { period: Period; win: DataWindow; region: Region; cat: Record<string, Metric> };
type Loaded = { name: string; current: Result<Query>; prior: Result<Query> | null; trend: Result<Query>; grain: Grain };

// Five tiles: three then two on tablets, one row on desktop, one column on phones (DESIGN.md).
const SPANS = ["md:col-span-2", "md:col-span-2", "md:col-span-2", "md:col-span-3", "md:col-span-3"];

async function load(name: string, { period, region }: Ctx): Promise<Loaded> {
  const { range, prior, priorCovered } = period;
  // Weekly up to about half a year: the channel-stock chart asks for the same weekly query, so the two share one call.
  const grain: Grain = daysBetween(range.from, range.to) <= 190 ? "week" : "month";
  const [current, priorResult, trend] = await Promise.all([
    query({ metric_name: name, date_range: { start: range.from, end: range.to } }, region),
    priorCovered ? query({ metric_name: name, date_range: { start: prior.from, end: prior.to } }, region) : Promise.resolve(null),
    query({ metric_name: name, group_by: [`metric_time__${grain}`], date_range: { start: range.from, end: range.to } }, region),
  ]);
  return { name, current, prior: priorResult, trend, grain };
}

function Tile({ k, ctx, span }: { k: Loaded; ctx: Ctx; span: string }) {
  const metric = ctx.cat[k.name] ?? fallbackMetric(k.name);
  const label = shortLabel(metric.label);
  const kind = metricKind(k.name, metric.label);
  const head = (
    <div className="flex min-w-0 items-center gap-0.5">
      <p className="text-[13px] font-medium text-muted">{label}</p>
      {metric.description ? <InfoTip label={`Definition of ${label}`}>{metric.description}</InfoTip> : null}
    </div>
  );
  if (!k.current.ok || !k.trend.ok) {
    const error = !k.current.ok ? k.current.error : !k.trend.ok ? k.trend.error : null;
    return (
      <div className={cx("flex flex-col gap-2 bg-surface p-4 md:p-5", span)}>
        {head}
        <p className="flex items-start gap-1.5 text-sm text-danger">
          <WarningCircle size={16} {...ICON} className="mt-0.5 shrink-0" aria-hidden />
          {error ? describeError(error).title : "Couldn't load"}
        </p>
      </div>
    );
  }
  const value = scalar(k.current.value.result.data, k.name);
  const priorValue = k.prior?.ok ? scalar(k.prior.value.result.data, k.name) : null;
  const delta = value != null && priorValue != null ? formatDelta(kind, value, priorValue) : null;
  const cohort = isCohortTimed(metric);
  const good = cohort ? 0 : (GOOD_DIRECTION[k.name] ?? 0);
  const tone = !delta || delta.sign === 0 || good === 0 ? "text-muted" : delta.sign === good ? "text-good" : "text-danger";
  const buckets = timeBuckets(k.grain, ctx.period.range, ctx.win);
  const trend = alignSeries(buckets, k.trend.value, `metric_time__${k.grain}`, k.name, false);
  const provisional = isHorizonBound(metric) && ctx.win.provisionalFrom && ctx.period.range.to >= ctx.win.provisionalFrom;
  const queries = [
    toDefQuery(k.current.value, `Value, ${fmtRange(ctx.period.range)}`),
    ...(k.prior?.ok ? [toDefQuery(k.prior.value, `Comparison, ${fmtRange(ctx.period.prior)}`)] : []),
    toDefQuery(k.trend.value, `Trend by ${k.grain}`),
  ];

  const Arrow = !delta || delta.sign === 0 ? Minus : delta.sign > 0 ? ArrowUpRight : ArrowDownRight;
  const note = cohort
    ? "By manufacture date: newer batches have had less time to collect claims."
    : provisional
      ? `Includes provisional sell-out from ${fmtDayMonth(ctx.win.provisionalFrom!)}.`
      : null;

  return (
    <div className={cx("flex min-w-0 flex-col gap-3 bg-surface p-4 md:p-5", span)}>
      {head}
      <div className="grid grid-cols-[1fr_minmax(96px,38%)] items-end gap-x-4 gap-y-3 md:grid-cols-1">
        <div className="flex min-w-0 flex-col gap-1.5">
          <Figure text={formatValue(kind, value)} className={TYPE.figureHero} />
          <p className="flex flex-wrap items-center gap-x-1.5 text-xs">
            {delta ? (
              <span className={cx("inline-flex items-center gap-0.5 font-semibold", tone)}>
                <Arrow size={13} weight="bold" className="shrink-0" aria-hidden />
                {delta.text}
              </span>
            ) : (
              <span className="text-muted">No comparison</span>
            )}
            {priorValue != null ? <span className="text-muted">vs {formatValue(kind, priorValue)}</span> : null}
          </p>
        </div>
        <Sparkline
          values={trend}
          label={`${label} by ${k.grain}, ${buckets.length} ${k.grain}s; latest ${formatValue(kind, trend.findLast((v) => v != null))}`}
        />
      </div>
      <div className="mt-auto flex items-end justify-between gap-3">
        <p className="text-[11.5px]/4 text-subtle">{note}</p>
        <DefinitionButton
          className="-mr-2 -mb-1 h-8 shrink-0 px-2 text-xs max-md:h-10"
          label={`Definition and SQL: ${label}`}
          trigger={
            <>
              <Database size={14} {...ICON} aria-hidden />
              SQL
            </>
          }
          title={label}
          metrics={[toDefMetric(metric)]}
          queries={queries}
        />
      </div>
    </div>
  );
}

export async function KpiStrip({ period, win, region, catalog }: { period: Period; win: DataWindow; region: Region; catalog: Result<Record<string, Metric>> }) {
  const ctx: Ctx = { period, win, region, cat: catalog.ok ? catalog.value : {} };
  const loaded = await Promise.all(KPI_METRICS.map((name) => load(name, ctx)));
  const failures = loaded.map((k) => (!k.current.ok ? k.current.error : !k.trend.ok ? k.trend.error : null));
  if (failures.every(Boolean)) {
    return (
      <section aria-label="Key figures" className="rounded-panel border border-line bg-surface px-4">
        <ErrorState error={failures[0]!} />
      </section>
    );
  }
  return (
    <section aria-labelledby="kpi-heading" className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id="kpi-heading" className="text-sm font-semibold text-ink">
          Key figures, {fmtRange(period.range)}
        </h2>
        <p className="text-xs text-muted">
          {period.priorCovered
            ? `Changes compare with ${period.priorLabel}, ${fmtRange(period.prior)}.`
            : `No changes shown: the data starts ${fmtDate(win.dataStart)}, so the comparison window isn't covered.`}
        </p>
      </div>
      <Sheet className="md:grid-cols-6 lg:grid-cols-5">
        {loaded.map((k, i) => (
          <Tile key={k.name} k={k} ctx={ctx} span={cx(SPANS[i], "lg:col-span-1")} />
        ))}
      </Sheet>
    </section>
  );
}

export function KpiStripSkeleton() {
  return (
    <div aria-busy="true" className="flex flex-col gap-2">
      <span className="sr-only">Loading key figures</span>
      <Skeleton className="h-4 w-48" />
      <div className="grid grid-cols-1 gap-px overflow-clip rounded-panel border border-line bg-line md:grid-cols-6 lg:grid-cols-5">
        {SPANS.map((span, i) => (
          <div key={i} className={cx("flex flex-col gap-3 bg-surface p-4 md:p-5", span, "lg:col-span-1")}>
            <Skeleton className="h-3.5 w-32" />
            <Skeleton className="h-8 w-28" />
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-8 w-full" />
          </div>
        ))}
      </div>
    </div>
  );
}

