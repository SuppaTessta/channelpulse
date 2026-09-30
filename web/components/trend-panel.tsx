import { ChartLineDown } from "@phosphor-icons/react/dist/ssr";
import type { ReactNode } from "react";
import { queryAll, type DataWindow, type Filter, type Metric, type Result } from "@/lib/api";
import { regionName, type Region } from "@/lib/config";
import type { Grain } from "@/lib/dates";
import { fmtRange, formatValue } from "@/lib/format";
import { fallbackMetric, isHorizonBound, metricKind, shortLabel, toDefMetric, toDefQuery, zeroWhenEmpty } from "@/lib/metrics";
import type { Period } from "@/lib/params";
import { alignSeries, coverageText, timeBuckets } from "@/lib/series";
import { ChartPanel } from "./chart-panel";
import { TimeChart, type ChartSeries } from "./charts/time-chart";
import { DataTable } from "./data-table";
import { DefinitionButton } from "./definition";
import { EmptyState, ErrorState } from "./states";
import { ICON, PanelSkeleton, cx } from "./ui";

export type TrendMetric = { name: string; slot: number | "deemph"; label?: string };

export type TrendProps = {
  id: string;
  title: string;
  /** Describes the measure; the covered dates are appended. */
  subtitle: string;
  metrics: TrendMetric[];
  grain: Grain;
  mark: "line" | "bar";
  barMode?: "grouped" | "overlay";
  period: Period;
  win: DataWindow;
  region: Region;
  catalog: Result<Record<string, Metric>>;
  filters?: Filter[];
  yDomain?: [number, number];
  height?: number;
  className?: string;
  footer?: ReactNode;
  /** Shown above the chart, inside the chart view (headline figures that belong with it). */
  lead?: ReactNode;
  refLine?: { value: number; label: string };
};

const GRAIN_WORD: Record<Grain, string> = { day: "Day", week: "Week", month: "Month", quarter: "Quarter", year: "Year" };

export async function TrendPanel(p: TrendProps) {
  const cat = p.catalog.ok ? p.catalog.value : {};
  const metric = (name: string) => cat[name] ?? fallbackMetric(name);
  const timeColumn = `metric_time__${p.grain}`;
  const r = await queryAll(
    p.metrics.map((m) => ({
      metric_name: m.name,
      filters: p.filters ?? [],
      group_by: [timeColumn],
      date_range: { start: p.period.range.from, end: p.period.range.to },
    })),
    p.region,
  );
  const buckets = timeBuckets(p.grain, p.period.range, p.win);
  const kind = metricKind(p.metrics[0].name, metric(p.metrics[0].name).label);
  const definition = r.ok ? (
    <DefinitionButton
      source
      title={p.title}
      metrics={p.metrics.map((m) => toDefMetric(metric(m.name)))}
      queries={r.value.map((q, i) => toDefQuery(q, `${shortLabel(metric(p.metrics[i].name).label)} by ${p.grain}`))}
    />
  ) : null;
  const subtitle = `${p.subtitle}, ${coverageText(buckets, p.period.range, p.win, p.grain)}`;

  if (!r.ok) {
    return <ChartPanel id={p.id} title={p.title} subtitle={subtitle} className={p.className} chart={<ErrorState compact error={r.error} />} />;
  }
  if (r.value.every((q) => q.result.row_count === 0)) {
    return (
      <ChartPanel
        id={p.id}
        title={p.title}
        subtitle={subtitle}
        actions={definition}
        className={p.className}
        chart={
          <EmptyState
            icon={<ChartLineDown size={20} {...ICON} aria-hidden />}
            title="No figures in this range"
            body={`The governed query returned no rows for ${fmtRange(p.period.range)} under ${regionName(p.region)}. Try a wider range or another region.`}
          />
        }
      />
    );
  }

  const series: ChartSeries[] = p.metrics.map((m, i) => ({
    key: m.name,
    label: m.label ?? shortLabel(metric(m.name).label),
    slot: m.slot,
    values: alignSeries(buckets, r.value[i], timeColumn, m.name, zeroWhenEmpty(cat[m.name])),
    horizonBound: isHorizonBound(cat[m.name]),
  }));
  const capped = r.value.some((q) => q.result.row_cap_hit);

  return (
    <ChartPanel
      id={p.id}
      title={p.title}
      subtitle={subtitle}
      actions={definition}
      className={cx(p.className)}
      chart={
        <div className="flex flex-col gap-4">
          {p.lead}
          <TimeChart
            buckets={buckets}
            series={series}
            mark={p.mark}
            barMode={p.barMode}
            kind={kind}
            yDomain={p.yDomain}
            height={p.height}
            title={p.title}
            grain={p.grain}
            refLine={p.refLine}
          />
        </div>
      }
      table={
        <DataTable
          caption={`${p.title}, ${subtitle}`}
          columns={[{ label: GRAIN_WORD[p.grain] }, ...series.map((s) => ({ label: s.label, numeric: true }))]}
          rows={buckets.map((b, i) => [
            <span key="b">
              {b.label}
              {b.partial || (b.provisional && series.some((s) => s.horizonBound)) ? (
                <span className="text-xs text-muted"> ({b.partial ?? "provisional"})</span>
              ) : null}
            </span>,
            ...series.map((s) => formatValue(kind, s.values[i])),
          ])}
        />
      }
      footer={
        <>
          {capped ? <p className="text-xs text-adhoc">The API capped a result at its row limit, so the chart may be missing its newest buckets.</p> : null}
          {p.footer}
        </>
      }
    />
  );
}

export function TrendSkeleton({ title, className, height = "h-60" }: { title: string; className?: string; height?: string }) {
  return <PanelSkeleton label={title} className={className} chartHeight={height} />;
}
