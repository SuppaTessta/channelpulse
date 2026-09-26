import type { Metadata } from "next";
import { PageError } from "@/components/page-error";
import { Panel } from "@/components/panel";
import { ParamSelect } from "@/components/param-select";
import { PendingStatus } from "@/components/providers";
import { CohortHeatmap, EntityDrill, loadOptions, LotFlags, MonthDrill, type QualityCtx } from "@/components/quality-sections";
import { SegmentedParam } from "@/components/segmented-param";
import { FilterBar, PageBody, TopBar } from "@/components/top-bar";
import { PanelSkeleton, Sheet, Skeleton } from "@/components/ui";
import { getAnomalies, getDataWindow, getMetrics, type Filter } from "@/lib/api";
import { parseRegion } from "@/lib/config";
import { isISODate } from "@/lib/dates";
import { param, type SearchParams } from "@/lib/params";

export const metadata: Metadata = { title: "Batch cohort heatmap" };

const MODES = { all: "cohort_cumulative_claims_per_1000", "base-crack": "cohort_cumulative_base_crack_per_1000" } as const;
const DRILL_RESETS = ["lot", "batch", "month"];

export default async function QualityPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const sp = await searchParams;
  const region = parseRegion(param(sp, "region"));
  const [win, catalog, options, anomalies] = await Promise.all([getDataWindow(region), getMetrics(), loadOptions(region), getAnomalies(region)]);
  const title = "Batch cohort heatmap";
  if (!win.ok || !options.ok) {
    const error = !win.ok ? win.error : !options.ok ? options.error : null;
    return (
      <>
        <TopBar title={title} region={region} win={win} catalog={catalog} />
        <PageBody>{error ? <PageError error={error} /> : null}</PageBody>
      </>
    );
  }

  // Only values the cohorts themselves offer are used as filters.
  const plant = options.value.plants.find((o) => o.value === param(sp, "plant"))?.value ?? null;
  const product = options.value.products.find((o) => o.value === param(sp, "product"))?.value ?? null;
  const mode = param(sp, "mode") === "base-crack" ? "base-crack" : "all";
  const filters: Filter[] = [
    ...(plant ? [{ dimension: "batch__plant_id", op: "=" as const, value: plant }] : []),
    ...(product ? [{ dimension: "batch__product__product_name", op: "=" as const, value: product }] : []),
  ];
  const ctx: QualityCtx = { region, win: win.value, catalog, filters, metric: MODES[mode], sp };
  const lot = param(sp, "lot") ?? null;
  const batch = param(sp, "batch") ?? null;
  const month = isISODate(param(sp, "month")) ? param(sp, "month")! : null;

  return (
    <>
      <TopBar title={title} region={region} win={win} catalog={catalog} />
      <FilterBar>
        <ParamSelect param="plant" label="Plant" value={plant} allLabel="All plants" options={options.value.plants} resets={DRILL_RESETS} />
        <ParamSelect param="product" label="Product" value={product} allLabel="All tank SKUs" options={options.value.products} resets={DRILL_RESETS} />
        <SegmentedParam
          param="mode"
          label="Claims"
          value={mode === "all" ? null : mode}
          options={[
            { value: null, label: "All failure modes" },
            { value: "base-crack", label: "Base crack" },
          ]}
        />
        <PendingStatus />
      </FilterBar>
      <PageBody>
        {region !== "ALL" ? (
          <p className="text-xs text-muted">Batch cohorts are plant-level, so the region claim doesn&apos;t narrow them. It does apply to the lot-scan flags.</p>
        ) : null}
        <div className="grid grid-cols-1 gap-4 md:gap-5 xl:grid-cols-[minmax(0,1fr)_400px]">
          <Sheet className="self-start">
            <Panel title="Cohort heatmap" fallback={<PanelSkeleton label="cohort heatmap" chartHeight="h-[520px]" />}>
              <CohortHeatmap ctx={ctx} activeMonth={month} />
            </Panel>
          </Sheet>
          <div className="flex flex-col gap-4 md:gap-5" data-dim="">
            {lot || batch ? (
              <Panel title="Drill-down" key={`${lot}|${batch}`} fallback={<Skeleton className="h-96 w-full rounded-panel" />}>
                <EntityDrill ctx={ctx} kind={lot ? "lot" : "batch"} id={(lot ?? batch)!} anomalies={anomalies} />
              </Panel>
            ) : month ? (
              <Panel title="Month drill-down" key={month} fallback={<Skeleton className="h-72 w-full rounded-panel" />}>
                <MonthDrill ctx={ctx} month={month} />
              </Panel>
            ) : null}
            <LotFlags anomalies={anomalies} sp={sp} activeLot={lot} className="rounded-panel border border-line bg-surface p-4 md:p-5" />
          </div>
        </div>
      </PageBody>
    </>
  );
}
