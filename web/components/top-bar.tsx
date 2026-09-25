import type { ReactNode } from "react";
import type { DataWindow, Metric, Result } from "@/lib/api";
import { REGIONS, regionSlug, type Region } from "@/lib/config";
import { fmtDate, fmtDayMonth } from "@/lib/format";
import { toDefMetric, toDefQuery } from "@/lib/metrics";
import { DefinitionButton } from "./definition";
import { InfoTip } from "./info-tip";
import { MobileNav } from "./nav";
import { ParamSelect } from "./param-select";

function DataAsOf({ win, catalog }: { win: Result<DataWindow>; catalog: Result<Record<string, Metric>> }) {
  if (!win.ok) return <p className="text-xs text-muted">Data as of: unavailable</p>;
  const { asOf, provisionalFrom, queries } = win.value;
  const metric = catalog.ok ? catalog.value.secondary_units : undefined;
  return (
    <DefinitionButton
      title="Data as of"
      className="-ml-2.5 h-auto min-h-10 flex-wrap justify-start gap-x-1.5 gap-y-0 py-1 text-left md:min-h-8 lg:-mr-2 lg:ml-0 lg:justify-end lg:text-right"
      trigger={
        <>
          <span className="text-muted">Data as of</span>
          <span className="font-semibold text-ink">{fmtDate(asOf)}</span>
          {provisionalFrom ? <span className="text-muted">· provisional from {fmtDayMonth(provisionalFrom)}</span> : null}
        </>
      }
      note={
        <>
          <p>
            <strong className="font-semibold">Data as of</strong> is the latest sale date with reported sell-out, read from the governed
            metric <code className="font-mono text-[13px]">secondary_units</code>.
          </p>
          {provisionalFrom ? (
            <p className="mt-3">
              Distributors report sell-out late (decisions D12), so the warehouse has not settled sale dates from{" "}
              <strong className="font-semibold">{fmtDate(provisionalFrom)}</strong> onward. Figures built on sell-out are provisional over
              that stretch, and charts shade it.
            </p>
          ) : null}
        </>
      }
      metrics={metric ? [toDefMetric(metric)] : []}
      queries={queries.map((q, i) =>
        toDefQuery(q, i === 0 ? "Months with sell-out (gives the data start)" : i === 1 ? "Sale days not yet settled (gives the as-of)" : "Sale days in the last month"),
      )}
    />
  );
}

export function TopBar({
  title,
  region,
  win,
  catalog,
  children,
}: {
  title: string;
  region: Region;
  win: Result<DataWindow>;
  catalog: Result<Record<string, Metric>>;
  children?: ReactNode;
}) {
  return (
    <header className="border-b border-line bg-canvas md:sticky md:top-0 md:z-20 md:bg-canvas/85 md:backdrop-blur-md">
      <div className="mx-auto flex max-w-[1440px] flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2 md:px-6 lg:min-h-14 lg:flex-nowrap">
        <MobileNav />
        <div className="min-w-0 flex-1 py-1">
          {children ? <div className="text-xs text-muted">{children}</div> : null}
          <h1 className="truncate text-base font-semibold text-ink md:text-lg">{title}</h1>
        </div>
        <div className="flex w-full flex-wrap items-center justify-between gap-x-4 gap-y-1 lg:w-auto lg:flex-nowrap lg:justify-end">
          <ParamSelect
            param="region"
            label="Viewing as"
            value={region === "ALL" ? null : regionSlug(region)}
            allLabel="All regions"
            options={REGIONS.map((r) => ({ value: regionSlug(r), label: r }))}
            hint={
              <InfoTip label="About the region claim">
                A demo region claim, sent to the API as <code className="font-mono">X-Demo-Region</code>. Postgres row-level security then limits
                distributor-level data to that region. This demo has no login.
              </InfoTip>
            }
          />
          <DataAsOf win={win} catalog={catalog} />
        </div>
      </div>
    </header>
  );
}

/** The single filter row under the top bar (dataviz: filters sit in one row above what they scope). */
export function FilterBar({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto flex max-w-[1440px] flex-wrap items-center gap-x-3 gap-y-2 px-4 pt-4 md:px-6 md:pt-5">{children}</div>
  );
}

export function PageBody({ children }: { children: ReactNode }) {
  return <div className="mx-auto flex max-w-[1440px] flex-col gap-4 px-4 pt-4 pb-12 md:gap-5 md:px-6 md:pt-5">{children}</div>;
}
