import type { Metadata } from "next";
import { AskPanel } from "@/components/ask/ask-panel";
import { ReplayPanel } from "@/components/ask/replay-panel";
import { Panel } from "@/components/panel";
import { ErrorState } from "@/components/states";
import { PageBody, TopBar } from "@/components/top-bar";
import { getAskStatus, getDataWindow, getMetrics, getReplay } from "@/lib/api";
import { parseRegion } from "@/lib/config";
import { param, sharedQuery, type SearchParams } from "@/lib/params";

export const metadata: Metadata = { title: "Ask ChannelPulse" };

export default async function AskPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const sp = await searchParams;
  const region = parseRegion(param(sp, "region"));
  // The analyst doesn't depend on these; they only feed the top bar, so a warehouse outage doesn't block the page.
  const [win, catalog, status] = await Promise.all([getDataWindow(region), getMetrics(), getAskStatus()]);
  const query = sharedQuery(sp);

  let body;
  if (!status.ok) {
    body = (
      <section aria-label="Ask ChannelPulse" className="rounded-panel border border-line bg-surface px-4 md:px-5">
        <ErrorState error={status.error} />
      </section>
    );
  } else if (status.value.mode === "live") {
    body = (
      <div className="mx-auto w-full max-w-[960px]">
        <AskPanel region={region} pagesQuery={query} />
      </div>
    );
  } else {
    const replay = await getReplay(region);
    body = replay.ok ? (
      <ReplayPanel status={status.value} replay={replay.value} region={region} selected={param(sp, "q")} query={query} />
    ) : (
      <section aria-label="Recorded answers" className="rounded-panel border border-line bg-surface px-4 md:px-5">
        <ErrorState error={replay.error} />
      </section>
    );
  }

  return (
    <>
      <TopBar title="Ask ChannelPulse" region={region} win={win} catalog={catalog} />
      <PageBody>
        <Panel title="Ask ChannelPulse" fallback={null}>
          {body}
        </Panel>
      </PageBody>
    </>
  );
}
