// Development-only chart story (excluded from production builds by pageExtensions). It renders the chart components
// in the same panel composition the pages use, from fixed inputs, so chart states can be checked without the warehouse.
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ChartPanel } from "@/components/chart-panel";
import { BarList } from "@/components/charts/bar-list";
import { TimeChart, type ChartSeries } from "@/components/charts/time-chart";
import { Heatmap } from "@/components/charts/heatmap";
import { Sheet } from "@/components/ui";
import { timeBuckets } from "@/lib/series";

export const metadata: Metadata = { title: "Chart fixtures (development only)" };

// FIXTURE VALUES: invented for layout testing, not taken from the warehouse.
const WIN = { asOf: "2026-09-23", dataStart: "2023-10-01", provisionalFrom: "2026-09-07" };
const MONTHS = timeBuckets("month", { from: "2026-04-01", to: "2026-09-23" }, WIN);
const WEEKS = timeBuckets("week", { from: "2026-04-01", to: "2026-09-23" }, WIN);
const wave = (n: number, base: number, amp: number) => Array.from({ length: n }, (_, i) => Math.round(base + amp * Math.sin(i / 2.3)));

const SALES: ChartSeries[] = [
  { key: "p", label: "Primary sales value", slot: 1, values: [412, 398, 377, 351, 364, 263].map((v) => v * 1e6), horizonBound: false },
  { key: "s", label: "Secondary sales value", slot: 2, values: [455, 471, 402, 330, 348, 258].map((v) => v * 1e6), horizonBound: true },
];
const STOCK: ChartSeries[] = [{ key: "d", label: "Channel days of stock", slot: 1, values: wave(WEEKS.length, 31, 4), horizonBound: true }];
const HEALTH: ChartSeries[] = [{ key: "h", label: "Distributor health score", slot: 1, values: wave(WEEKS.length, 44, 14), horizonBound: false }];

export default function ChartFixturePage() {
  if (process.env.NODE_ENV === "production") notFound();
  const rows = Array.from({ length: 12 }, (_, r) => ({ key: `2025-${String(r + 1).padStart(2, "0")}-01`, label: `M${r + 1}`, units: 900 + r * 10 }));
  const cols = Array.from({ length: 14 }, (_, c) => c);
  const cells = rows.map((_, r) => cols.map((c) => (c <= 12 - r ? +(c * 1.1 + (r === 4 ? c * 0.9 : 0)).toFixed(2) : null)));
  return (
    <div className="mx-auto flex max-w-[1440px] flex-col gap-5 px-4 py-6 md:px-6">
      <header className="flex flex-col gap-2">
        <h1 className="text-lg font-semibold text-ink">Chart fixtures</h1>
        <p role="note" className="rounded-control border border-l-4 border-line border-l-[var(--adhoc)] bg-adhoc-soft px-3 py-2 text-sm text-ink">
          Development-only preview with invented values, to check chart states. Not data from the API; not part of production builds.
        </p>
      </header>
      <Sheet className="md:grid-cols-12">
        <ChartPanel
          id="f-sales"
          title="Grouped bars, provisional band, partial month"
          className="md:col-span-12 lg:col-span-8"
          chart={<TimeChart buckets={MONTHS} series={SALES} mark="bar" kind="inr" title="Sales fixture" grain="month" />}
        />
        <ChartPanel
          id="f-stock"
          title="Line with provisional dashed tail"
          className="md:col-span-12 lg:col-span-4"
          chart={<TimeChart buckets={WEEKS} series={STOCK} mark="line" kind="days" title="Stock fixture" grain="week" />}
        />
        <ChartPanel
          id="f-health"
          title="Fixed 0 to 100 domain with a threshold"
          className="md:col-span-12 lg:col-span-7"
          chart={<TimeChart buckets={WEEKS} series={HEALTH} mark="line" kind="score" yDomain={[0, 100]} title="Health fixture" grain="week" refLine={{ value: 30, label: "Score 30: an at-risk condition" }} />}
        />
        <ChartPanel
          id="f-region"
          title="Mirrored bars"
          className="md:col-span-12 lg:col-span-5"
          chart={
            <BarList
              mirrored
              kind="pct"
              title="Region fixture"
              rows={["South Bengal", "North Bengal & Sikkim", "Assam", "North East", "Bihar & Jharkhand", "Odisha"].map((x) => ({ key: x, label: x }))}
              series={[
                { key: "a", label: "Stock-out rate", slot: 1, values: [0.041, 0.063, 0.052, 0.088, 0.047, 0.036] },
                { key: "b", label: "Overstock rate", slot: 2, values: [0.112, 0.094, 0.071, 0.058, 0.133, 0.101] },
              ]}
            />
          }
        />
        <ChartPanel
          id="f-heat"
          title="Heatmap with an unobserved triangle"
          className="md:col-span-12"
          chart={<Heatmap rows={rows} cols={cols} cells={cells} thresholds={[2, 4, 6, 8, 10]} title="Heatmap fixture" valueLabel="Fixture claims per 1,000" activeRow={null} />}
        />
      </Sheet>
    </div>
  );
}
