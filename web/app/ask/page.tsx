import type { Metadata } from "next";
import { AskPanel } from "@/components/ask/ask-panel";
import { PageBody, TopBar } from "@/components/top-bar";
import { getDataWindow, getMetrics } from "@/lib/api";
import { parseRegion } from "@/lib/config";
import { param, sharedQuery, type SearchParams } from "@/lib/params";

export const metadata: Metadata = { title: "Ask ChannelPulse" };

export default async function AskPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const sp = await searchParams;
  const region = parseRegion(param(sp, "region"));
  // The analyst doesn't depend on these; they only feed the top bar, so a warehouse outage doesn't block the page.
  const [win, catalog] = await Promise.all([getDataWindow(region), getMetrics()]);
  return (
    <>
      <TopBar title="Ask ChannelPulse" region={region} win={win} catalog={catalog} />
      <PageBody>
        <div className="mx-auto w-full max-w-[960px]">
          <AskPanel region={region} pagesQuery={sharedQuery(sp)} />
        </div>
      </PageBody>
    </>
  );
}
