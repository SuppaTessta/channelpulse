import { Newspaper } from "@phosphor-icons/react/dist/ssr";
import type { Metadata } from "next";
import { BriefReport, BriefSkeleton, BriefUnavailable } from "@/components/brief/brief-report";
import { Panel } from "@/components/panel";
import { ParamSelect } from "@/components/param-select";
import { PrintButton } from "@/components/print-button";
import { PendingStatus } from "@/components/providers";
import { EmptyState, ErrorState } from "@/components/states";
import { FilterBar, PageBody, TopBar } from "@/components/top-bar";
import { ICON } from "@/components/ui";
import { getBriefWeeks, getDataWindow, getMetrics } from "@/lib/api";
import { parseRegion } from "@/lib/config";
import { fmtDate } from "@/lib/format";
import { param, type SearchParams } from "@/lib/params";

export const metadata: Metadata = { title: "Weekly Brief" };

export default async function BriefPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const sp = await searchParams;
  const region = parseRegion(param(sp, "region"));
  const [win, catalog, weeks] = await Promise.all([getDataWindow(region), getMetrics(), getBriefWeeks(region)]);
  const list = weeks.ok ? weeks.value.weeks : [];
  // Only weeks the API lists are accepted; no week in the URL means the newest.
  const week = list.find((w) => w === param(sp, "week")) ?? list[0] ?? null;

  let body;
  if (!weeks.ok) {
    body = (
      <BriefUnavailable>
        <ErrorState error={weeks.error} />
      </BriefUnavailable>
    );
  } else if (!week) {
    body = (
      <BriefUnavailable>
        <EmptyState
          icon={<Newspaper size={20} {...ICON} aria-hidden />}
          title="No brief has been written yet"
          body="The API lists no weeks with a brief. One appears here once the first week's facts are built and checked."
        />
      </BriefUnavailable>
    );
  } else {
    body = (
      <Panel title="Weekly Brief" key={week} fallback={<BriefSkeleton />}>
        <BriefReport week={week} region={region} />
      </Panel>
    );
  }

  return (
    <>
      <TopBar title="Weekly Brief" region={region} win={win} catalog={catalog} />
      <div className="print:hidden">
        <FilterBar>
          {list.length ? (
            <ParamSelect
              param="week"
              label="Week"
              value={week === list[0] ? null : week}
              allLabel={`Latest, week of ${fmtDate(list[0])}`}
              options={list.slice(1).map((w) => ({ value: w, label: `Week of ${fmtDate(w)}` }))}
            />
          ) : null}
          {week ? <PrintButton label="Print the brief" /> : null}
          <PendingStatus />
        </FilterBar>
      </div>
      <PageBody>{body}</PageBody>
    </>
  );
}
