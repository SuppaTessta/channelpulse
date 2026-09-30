import type { Metadata } from "next";
import { Panel } from "@/components/panel";
import { ParamSelect, type Option } from "@/components/param-select";
import { PendingStatus } from "@/components/providers";
import { SearchParam } from "@/components/search-param";
import { FilterBar, PageBody, TopBar } from "@/components/top-bar";
import { TraceDrawer } from "@/components/traces/trace-drawer";
import { TraceDetailSkeleton, TraceDetailView, TraceListPanel, TraceSummary, TraceSummarySkeleton } from "@/components/traces/trace-sections";
import { Skeleton } from "@/components/ui";
import { getDataWindow, getMetrics, getTraces } from "@/lib/api";
import { LABEL_TEXT, type AskLabel } from "@/lib/ask";
import { parseRegion } from "@/lib/config";
import { param, type SearchParams } from "@/lib/params";
import { categoryText, FACETS, facetPairs, type FacetKey } from "@/lib/traces";

export const metadata: Metadata = { title: "Agent traces" };

const LIMIT = 50;
const FILTERS = [...FACETS, "q"] as const;
const FACET_LABEL: Record<FacetKey, [string, string]> = {
  label: ["Label", "All labels"],
  provider: ["Provider", "All providers"],
  model: ["Model", "All models"],
  category: ["Category", "All categories"],
  source: ["Source", "Eval and live"],
};
const optionText: Record<FacetKey, (v: string) => string> = {
  label: (v) => LABEL_TEXT[v as AskLabel] ?? v,
  provider: (v) => v,
  model: (v) => v,
  category: categoryText,
  source: (v) => (v === "eval" ? "Eval runs" : v === "live" ? "Live" : v),
};
// A filter change starts the list again from the top and closes any open trace.
const RESETS = ["offset", "trace"];

export default async function TracesPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const sp = await searchParams;
  const region = parseRegion(param(sp, "region"));
  const offset = Math.max(0, Number.parseInt(param(sp, "offset") ?? "0", 10) || 0);
  const traceId = param(sp, "trace") ?? null;

  const api = new URLSearchParams();
  for (const key of FILTERS) {
    const v = param(sp, key);
    if (v) api.set(key, v);
  }
  api.set("limit", String(LIMIT));
  if (offset) api.set("offset", String(offset));
  const params = api.toString();

  const page = new URLSearchParams();
  for (const key of ["region", ...FILTERS, "offset"]) {
    const v = param(sp, key);
    if (v) page.set(key, v);
  }
  const pageQuery = page.toString();

  // The facets fill the filters; the panels below read the same call (React cache), so it runs once.
  const [win, catalog, list] = await Promise.all([getDataWindow(region), getMetrics(), getTraces(params, region)]);
  const facets = list.ok ? list.value.facets : {};
  const optionsFor = (key: FacetKey): Option[] => facetPairs(facets[key]).map(([v, n]) => ({ value: v, label: `${optionText[key](v)} (${n})` }));

  return (
    <>
      <TopBar title="Agent traces" region={region} win={win} catalog={catalog} />
      <FilterBar>
        {FACETS.map((key) => {
          const value = param(sp, key) ?? null;
          const options = optionsFor(key);
          // A value in the URL stays selectable even when the current facets no longer count it.
          if (value && !options.some((o) => o.value === value)) options.unshift({ value, label: optionText[key](value) });
          return <ParamSelect key={key} param={key} label={FACET_LABEL[key][0]} allLabel={FACET_LABEL[key][1]} value={value} options={options} resets={RESETS} />;
        })}
        <SearchParam param="q" label="Search" value={param(sp, "q") ?? null} placeholder="Question or SQL" resets={RESETS} />
        <PendingStatus />
      </FilterBar>
      <PageBody>
        <Panel title="Trace totals" fallback={<TraceSummarySkeleton />}>
          <TraceSummary params={params} region={region} />
        </Panel>
        <Panel title="Traces" fallback={<Skeleton className="h-96 w-full rounded-panel" />}>
          <TraceListPanel params={params} region={region} offset={offset} limit={LIMIT} pageQuery={pageQuery} />
        </Panel>
      </PageBody>
      {traceId ? (
        <TraceDrawer key={traceId} traceId={traceId} closeHref={`/traces${pageQuery ? `?${pageQuery}` : ""}`}>
          <Panel title="Trace" fallback={<TraceDetailSkeleton />}>
            <TraceDetailView id={traceId} region={region} />
          </Panel>
        </TraceDrawer>
      ) : null}
    </>
  );
}
