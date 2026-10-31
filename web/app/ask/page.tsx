import type { Metadata } from "next";
import { AskPanel, ScoredExamples } from "@/components/ask/ask-panel";
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
  // The analyst doesn't depend on the first two; they only feed the top bar, so a warehouse outage doesn't block the
  // page. The recorded answers come in the same round, not after the status.
  const [win, catalog, status, replay] = await Promise.all([getDataWindow(region), getMetrics(), getAskStatus(), getReplay(region)]);
  const query = sharedQuery(sp);

  let body;
  if (!status.ok) {
    body = (
      <section aria-label="Ask ChannelPulse" className="rounded-panel border border-line bg-surface px-4 md:px-5">
        <ErrorState error={status.error} />
      </section>
    );
  } else {
    const recorded = replay.ok ? (
      <ReplayPanel status={status.value} replay={replay.value} region={region} selected={param(sp, "q")} query={query} />
    ) : (
      <section aria-label="Recorded answers" className="rounded-panel border border-line bg-surface px-4 md:px-5">
        <ErrorState error={replay.error} />
      </section>
    );
    // Live mode (layout A): the ask box leads, and the scored examples wait underneath, open only when one is chosen.
    body =
      status.value.mode === "live" ? (
        <div className="mx-auto flex w-full max-w-[960px] flex-col gap-6">
          <AskPanel region={region} pagesQuery={query} />
          <ScoredExamples open={!!param(sp, "q")}>{recorded}</ScoredExamples>
        </div>
      ) : (
        recorded
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
