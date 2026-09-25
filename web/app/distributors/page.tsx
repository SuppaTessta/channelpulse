import type { Metadata } from "next";
import { Suspense } from "react";
import { DateRangeControl } from "@/components/date-range";
import { DefinitionButton } from "@/components/definition";
import { DistributorTable, type DistributorRow, type RiskFlag } from "@/components/distributor-table";
import { PageError } from "@/components/page-error";
import { PendingStatus } from "@/components/providers";
import { describeError, ErrorState } from "@/components/states";
import { FilterBar, PageBody, TopBar } from "@/components/top-bar";
import { Skeleton } from "@/components/ui";
import { getAnomalies, getDataWindow, getMetrics, query, type Metric, type Result } from "@/lib/api";
import { parseRegion, type Region } from "@/lib/config";
import { toISODate } from "@/lib/dates";
import { fmtDate, fmtRange } from "@/lib/format";
import { anomaliesDefQuery, fallbackMetric, isCurrentFlag, latestSnapshot, shortLabel, toDefMetric, toDefQuery } from "@/lib/metrics";
import { param, resolvePeriod, sharedQuery, type Period, type SearchParams } from "@/lib/params";
import { num, records, str } from "@/lib/table";

export const metadata: Metadata = { title: "Distributor 360" };

async function DistributorList({ period, region, catalog, sp }: { period: Period; region: Region; catalog: Result<Record<string, Metric>>; sp: SearchParams }) {
  const [list, anomalies] = await Promise.all([
    query(
      {
        metric_name: "primary_sales_value",
        group_by: ["distributor", "distributor__distributor_name", "distributor__region", "distributor__tier"],
        date_range: { start: period.range.from, end: period.range.to },
      },
      region,
    ),
    getAnomalies(region, period.range.to),
  ]);
  if (!list.ok) {
    return (
      <section aria-label="Distributors" className="rounded-panel border border-line bg-surface px-4 md:px-6">
        <ErrorState error={list.error} />
      </section>
    );
  }
  const rows: DistributorRow[] = records(list.value.result.data).map((r) => ({
    id: str(r.distributor) ?? "",
    name: str(r.distributor__distributor_name) ?? str(r.distributor) ?? "",
    region: str(r.distributor__region) ?? "",
    tier: str(r.distributor__tier) ?? "",
    sales: num(r.primary_sales_value),
  }));
  const latest = anomalies.ok ? latestSnapshot(anomalies.value.rows) : null;
  const flags: RiskFlag[] | null = anomalies.ok
    ? anomalies.value.rows
        .filter((a) => a.detector === "distributor_health")
        .map((a) => ({
          id: a.entity_id,
          region: a.region,
          firstFlag: toISODate(a.first_flag_date),
          snapshot: toISODate(a.snapshot_date),
          week: toISODate(a.details?.week_start),
          // For this detector the effect size is the health score in the flagged week; the details carry its parts.
          score: num(a.effect_size),
          trendScore: num(a.details?.score_secondary_trend),
          current: isCurrentFlag(a, latest),
        }))
    : null;
  const cat = catalog.ok ? catalog.value : {};
  const sales = cat.primary_sales_value ?? fallbackMetric("primary_sales_value");
  const atRisk = cat.at_risk_distributors;
  const riskRule = [
    atRisk?.description ?? "Distributors the pre-registered distributor-health detector has flagged.",
    latest ? `At risk means flagged in the detector's latest weekly snapshot, ${fmtDate(latest)} (the last on or before ${fmtDate(period.range.to)}).` : "",
  ].join(" ");

  return (
    <DistributorTable
      rows={rows}
      flags={flags}
      flagsError={anomalies.ok ? null : `${describeError(anomalies.error).title}. ${anomalies.error.detail}`}
      initialView={param(sp, "view") === "at-risk" ? "at-risk" : "all"}
      initialQuery={param(sp, "q") ?? ""}
      linkQuery={sharedQuery(sp)}
      salesLabel={`${shortLabel(sales.label)}, ${fmtRange(period.range)}`}
      riskRule={riskRule}
      actions={
        <DefinitionButton
          title="Distributors"
          metrics={[toDefMetric(sales), ...(atRisk ? [toDefMetric(atRisk)] : [])]}
          queries={[
            toDefQuery(list.value, "Distributor list with primary sales in the range"),
            ...(anomalies.ok ? [anomaliesDefQuery(anomalies.value, "At-risk flags (distributor_health detector)")] : []),
          ]}
        />
      }
    />
  );
}

function ListSkeleton() {
  return (
    <div aria-busy="true" className="flex flex-col gap-3 rounded-panel border border-line bg-surface p-4 md:p-5">
      <span className="sr-only">Loading distributors</span>
      <div className="flex items-center justify-between">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-8 w-64" />
      </div>
      {Array.from({ length: 10 }, (_, i) => (
        <Skeleton key={i} className="h-7 w-full" />
      ))}
    </div>
  );
}

export default async function DistributorsPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const sp = await searchParams;
  const region = parseRegion(param(sp, "region"));
  const [win, catalog] = await Promise.all([getDataWindow(region), getMetrics()]);
  if (!win.ok) {
    return (
      <>
        <TopBar title="Distributor 360" region={region} win={win} catalog={catalog} />
        <PageBody>
          <PageError error={win.error} />
        </PageBody>
      </>
    );
  }
  const period = resolvePeriod(sp, win.value);
  return (
    <>
      <TopBar title="Distributor 360" region={region} win={win} catalog={catalog} />
      <FilterBar>
        <DateRangeControl range={period.range} presetKey={period.presetKey} presets={period.options} min={win.value.dataStart} max={win.value.asOf} />
        <PendingStatus />
      </FilterBar>
      <PageBody>
        <Suspense fallback={<ListSkeleton />}>
          <DistributorList period={period} region={region} catalog={catalog} sp={sp} />
        </Suspense>
      </PageBody>
    </>
  );
}
