import { CalendarCheck, Hourglass } from "@phosphor-icons/react/dist/ssr";
import type { ReactNode } from "react";
import type { DataWindow, Metric, Result } from "@/lib/api";
import { REGIONS, regionSlug, type Region } from "@/lib/config";
import { fmtDate, fmtDayMonth } from "@/lib/format";
import { toDefMetric, toDefQuery } from "@/lib/metrics";
import { DefinitionButton } from "./definition";
import { InfoTip } from "./info-tip";
import { MobileNav } from "./nav";
import { ParamSelect } from "./param-select";
import { cx, ICON, TYPE } from "./ui";

function DataAsOf({ win, catalog }: { win: Result<DataWindow>; catalog: Result<Record<string, Metric>> }) {
  if (!win.ok) return <p className="text-xs text-muted">Data as of: unavailable</p>;
  const { asOf, provisionalFrom, queries } = win.value;
  const metric = catalog.ok ? catalog.value.secondary_units : undefined;
  return (
    <DefinitionButton
      title="Data as of"
      className="-ml-2.5 h-auto min-h-10 flex-wrap justify-start gap-x-1.5 gap-y-0 py-1 text-left md:min-h-8 lg:-mr-2.5 lg:ml-0 lg:justify-end lg:text-right"
      trigger={
        <>
          <CalendarCheck size={16} {...ICON} className="shrink-0 text-accent" aria-hidden />
          <span className="text-muted">Data as of</span>
          <span className="font-semibold text-ink">{fmtDate(asOf)}</span>
          {provisionalFrom ? (
            <span className="inline-flex items-center gap-1 text-muted">
              <Hourglass size={14} {...ICON} className="ml-1 shrink-0" aria-hidden />
              provisional from {fmtDayMonth(provisionalFrom)}
            </span>
          ) : null}
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

/** The upper tier of every page's header: where you are, whose data you see, and how fresh it is. */
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
    <header className="border-b border-line bg-canvas md:sticky md:top-0 md:z-20 md:bg-canvas/85 md:backdrop-blur-md print:hidden">
      <div className="mx-auto flex max-w-[1440px] flex-wrap items-center gap-x-5 gap-y-1 px-4 py-2 md:px-6 lg:min-h-16 lg:flex-nowrap">
        <MobileNav />
        <div className="min-w-0 flex-1 py-1">
          {children ? <div className="text-xs text-muted">{children}</div> : null}
          <h1 className={cx(TYPE.pageTitle, "truncate")}>{title}</h1>
        </div>
        <div className="flex w-full flex-wrap items-center justify-between gap-x-5 gap-y-1 lg:w-auto lg:flex-nowrap lg:justify-end">
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
          <span aria-hidden className="hidden h-5 w-px bg-line-strong lg:block" />
          <DataAsOf win={win} catalog={catalog} />
        </div>
      </div>
    </header>
  );
}

/** The page's filter row, the lower tier of the header (dashboard layout: filters sit above everything they scope). */
export function FilterBar({ children }: { children: ReactNode }) {
  return (
    <div className="border-b border-line">
      <div className="mx-auto flex max-w-[1440px] flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 md:px-6">{children}</div>
    </div>
  );
}

export function PageBody({ children }: { children: ReactNode }) {
  return <div className="cp-stagger mx-auto flex max-w-[1440px] flex-col gap-5 px-4 pt-5 pb-16 md:gap-6 md:px-6 md:pt-6">{children}</div>;
}
