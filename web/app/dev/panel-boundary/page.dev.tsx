// Development-only story (excluded from production builds by pageExtensions): a panel whose server component throws
// and one whose client component throws, beside a healthy one. Each failure must stay inside its own panel.
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Panel } from "@/components/panel";
import { PageBody, TopBar } from "@/components/top-bar";
import { PanelSkeleton, Sheet } from "@/components/ui";
import { ThrowOnRender } from "./throw.dev";

export const metadata: Metadata = { title: "Panel boundary (development only)" };

async function ServerThrows(): Promise<never> {
  await new Promise((resolve) => setTimeout(resolve, 300));
  throw new Error("fixture: a server component failed");
}

export default function PanelBoundaryStory() {
  if (process.env.NODE_ENV === "production") notFound();
  const skeleton = (label: string) => <PanelSkeleton label={label} className="md:col-span-4" />;
  return (
    <>
      <TopBar title="Panel boundary" region="ALL" win={{ ok: false, error: { kind: "empty", detail: "fixture", endpoint: "none" } }} catalog={{ ok: true, value: {} }} />
      <PageBody>
        <Sheet className="md:grid-cols-12">
          <Panel title="Server component throws" className="md:col-span-4" fallback={skeleton("server")}>
            <ServerThrows />
          </Panel>
          <Panel title="Client component throws" className="md:col-span-4" fallback={skeleton("client")}>
            <ThrowOnRender />
          </Panel>
          <Panel title="Healthy neighbour" className="md:col-span-4" fallback={skeleton("healthy")}>
            <section className="bg-surface p-4 md:col-span-4 md:p-5">
              <h2 className="text-sm font-semibold text-ink">Healthy neighbour</h2>
              <p className="mt-1 text-sm text-muted">Still here.</p>
            </section>
          </Panel>
        </Sheet>
      </PageBody>
    </>
  );
}
