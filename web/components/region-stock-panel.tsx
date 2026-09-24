import { queryAll, type Metric, type Result } from "@/lib/api";
import { REGIONS, regionName, type Region } from "@/lib/config";
import { fmtRange, formatValue } from "@/lib/format";
import { fallbackMetric, shortLabel, toDefMetric, toDefQuery } from "@/lib/metrics";
import type { Period } from "@/lib/params";
import { column, num } from "@/lib/table";
import { ChartPanel } from "./chart-panel";
import { BarList } from "./charts/bar-list";
import { DataTable } from "./data-table";
import { DefinitionButton } from "./definition";
import { EmptyState, ErrorState } from "./states";

const METRICS = ["stockout_rate", "overstock_rate"] as const;

/** Stock-out and overstock back to back per region: the two ways channel stock goes wrong, on one shared scale. */
export async function RegionStockPanel({ period, region, catalog, className }: { period: Period; region: Region; catalog: Result<Record<string, Metric>>; className?: string }) {
  const cat = catalog.ok ? catalog.value : {};
  const title = "Stock-out and overstock by region";
  const subtitle = `Share of distributor-SKU-days, ${fmtRange(period.range)}`;
  const r = await queryAll(
    METRICS.map((m) => ({ metric_name: m, group_by: ["distributor__region"], date_range: { start: period.range.from, end: period.range.to } })),
    region,
  );
  if (!r.ok) return <ChartPanel id="region-stock" title={title} subtitle={subtitle} className={className} chart={<ErrorState compact error={r.error} />} />;

  const byRegion = r.value.map((q, i) => {
    const names = column(q.result.data, "distributor__region") ?? [];
    const values = column(q.result.data, METRICS[i]) ?? [];
    return new Map(names.map((n, j) => [String(n), num(values[j])]));
  });
  const present = new Set(byRegion.flatMap((m) => [...m.keys()]));
  // Fixed geographic order, so a region keeps its row whichever claim is viewing.
  const rows = [...REGIONS.filter((x) => present.has(x)), ...[...present].filter((x) => !(REGIONS as readonly string[]).includes(x))].map((x) => ({ key: x, label: x }));
  const metric = (m: string) => cat[m] ?? fallbackMetric(m);
  const series = METRICS.map((m, i) => ({ key: m, label: shortLabel(metric(m).label), slot: i + 1, values: rows.map((row) => byRegion[i].get(row.key) ?? null) }));
  const definition = (
    <DefinitionButton
      title={title}
      metrics={METRICS.map((m) => toDefMetric(metric(m)))}
      queries={r.value.map((q, i) => toDefQuery(q, `${series[i].label} by region`))}
    />
  );
  if (!rows.length) {
    return (
      <ChartPanel
        id="region-stock"
        title={title}
        subtitle={subtitle}
        actions={definition}
        className={className}
        chart={<EmptyState title="No stock readings in this range" body={`No distributor-SKU-days had a days-of-stock value under ${regionName(region)}. Try a wider range.`} />}
      />
    );
  }
  return (
    <ChartPanel
      id="region-stock"
      title={title}
      subtitle={subtitle}
      actions={definition}
      className={className}
      chart={<BarList rows={rows} series={series} kind="pct" mirrored title={title} />}
      table={
        <DataTable
          caption={`${title}, ${subtitle}`}
          columns={[{ label: "Region" }, ...series.map((s) => ({ label: s.label, numeric: true }))]}
          rows={rows.map((row, i) => [row.label, ...series.map((s) => formatValue("pct", s.values[i]))])}
        />
      }
    />
  );
}
