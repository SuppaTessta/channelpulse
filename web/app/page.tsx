import type { Metadata } from "next";
import { Suspense } from "react";
import { DateRangeControl } from "@/components/date-range";
import { KpiStrip, KpiStripSkeleton } from "@/components/kpi-strip";
import { PageError } from "@/components/page-error";
import { PendingStatus } from "@/components/providers";
import { RegionStockPanel } from "@/components/region-stock-panel";
import { FilterBar, PageBody, TopBar } from "@/components/top-bar";
import { TrendPanel, TrendSkeleton } from "@/components/trend-panel";
import { Sheet } from "@/components/ui";
import { getDataWindow, getMetrics } from "@/lib/api";
import { parseRegion } from "@/lib/config";
import { param, resolvePeriod, type SearchParams } from "@/lib/params";

export const metadata: Metadata = { title: "Executive KPIs" };

const SALES = "md:col-span-12 lg:col-span-8";
const STOCK = "md:col-span-6 lg:col-span-4";
const DSO = "md:col-span-6 lg:col-span-5";
const REGION = "md:col-span-12 lg:col-span-7";

export default async function ExecutivePage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const sp = await searchParams;
  const region = parseRegion(param(sp, "region"));
  const [win, catalog] = await Promise.all([getDataWindow(region), getMetrics()]);

  if (!win.ok) {
    return (
      <>
        <TopBar title="Executive KPIs" region={region} win={win} catalog={catalog} />
        <PageBody>
          <PageError error={win.error} />
        </PageBody>
      </>
    );
  }
  const period = resolvePeriod(sp, win.value);
  const common = { period, win: win.value, region, catalog };

  return (
    <>
      <TopBar title="Executive KPIs" region={region} win={win} catalog={catalog} />
      <FilterBar>
        <DateRangeControl range={period.range} presetKey={period.presetKey} presets={period.options} min={win.value.dataStart} max={win.value.asOf} />
        <PendingStatus />
      </FilterBar>
      <PageBody>
        <Suspense fallback={<KpiStripSkeleton />}>
          <KpiStrip {...common} />
        </Suspense>
        <Sheet className="md:grid-cols-12">
          <Suspense fallback={<TrendSkeleton title="Primary and secondary sales" className={SALES} />}>
            <TrendPanel
              {...common}
              id="sales"
              title="Primary and secondary sales"
              subtitle="Sell-in by invoice month, sell-out by sale month"
              metrics={[
                { name: "primary_sales_value", slot: 1 },
                { name: "secondary_sales_value", slot: 2 },
              ]}
              grain="month"
              mark="bar"
              className={SALES}
            />
          </Suspense>
          <Suspense fallback={<TrendSkeleton title="Channel days of stock" className={STOCK} />}>
            <TrendPanel
              {...common}
              id="stock"
              title="Channel days of stock"
              subtitle="Whole channel, read on each week's last day"
              metrics={[{ name: "channel_days_of_stock", slot: 1 }]}
              grain="week"
              mark="line"
              className={STOCK}
            />
          </Suspense>
          <Suspense fallback={<TrendSkeleton title="Days sales outstanding" className={DSO} />}>
            <TrendPanel
              {...common}
              id="dso"
              title="Days sales outstanding"
              subtitle="Amount-weighted, by invoice month"
              metrics={[{ name: "dso", slot: 1 }]}
              grain="month"
              mark="line"
              className={DSO}
              footer={<p className="text-xs text-subtle">Recent months include invoices still open, aged to the as-of date.</p>}
            />
          </Suspense>
          <Suspense fallback={<TrendSkeleton title="Stock-out and overstock by region" className={REGION} />}>
            <RegionStockPanel period={period} region={region} catalog={catalog} className={REGION} />
          </Suspense>
        </Sheet>
      </PageBody>
    </>
  );
}
