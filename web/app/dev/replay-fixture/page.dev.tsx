// Development-only story for replay mode (excluded from production builds by pageExtensions). Until a real eval run
// has recorded answers, fixtures are the only way to see the replay view; they are never written to recordings/.
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ReplayPanel } from "@/components/ask/replay-panel";
import { PageBody, TopBar } from "@/components/top-bar";
import type { AskResponse, AskStatus, Recording, Replay, ReplayAnswer } from "@/lib/ask";
import { param, type SearchParams } from "@/lib/params";

export const metadata: Metadata = { title: "Replay fixtures (development only)" };

// FIXTURE VALUES: invented for layout testing, not taken from the warehouse or from any eval run.
const RECORDING: Recording = {
  model: "claude-opus-5-5", effort: "medium", recorded_at: "2026-09-28T10:00:00+00:00", as_of: "2026-09-23",
  region: "ALL", status: "complete", git_commit: "fixture", count: 3,
};
const governed: AskResponse = {
  answer_text: "FIXTURE TEXT. DSO was 36.2 days over FY27 to date.",
  sql: ["SELECT 36.2 AS dso"], data: { columns: ["dso"], rows: [[36.2]] }, chart_spec: null,
  label: "governed_metric", confidence_note: "FIXTURE NOTE. 1/1 figure traced to query results.", trace_id: "fixture-1",
};
const refused: AskResponse = {
  answer_text: "FIXTURE TEXT. I can't forecast next quarter's sales: no metric or mart holds forecasts.",
  sql: [], data: null, chart_spec: null, label: "refused", confidence_note: "FIXTURE NOTE. No figures reported.", trace_id: "fixture-2",
};
const answer = (id: string, category: string, question: string, response: AskResponse, correct: boolean): ReplayAnswer => ({
  id, category, question, response, eval: { correct, label_correct: correct }, served_model: RECORDING.model, latency_ms: 9000, cost_usd: 0.1,
});
const ANSWERS = [
  answer("SL01", "simple_lookup", "FIXTURE: What is DSO for FY27 to date?", governed, true),
  answer("TC01", "time_comparison", "FIXTURE: How did DSO change against last year?", governed, false),
  answer("TR01", "trap", "FIXTURE: Forecast next quarter's sales.", refused, true),
];
const STATUS: AskStatus = { mode: "replay", reason: "no_credentials", provider: "gemini", model: RECORDING.model, recording: RECORDING };
const STATES: Record<string, { status: AskStatus; replay: Replay }> = {
  recorded: { status: STATUS, replay: { recording: RECORDING, answers: ANSWERS, withheld: false } },
  withheld: { status: STATUS, replay: { recording: RECORDING, answers: [], withheld: true } },
  empty: { status: { ...STATUS, reason: "live_off", recording: null }, replay: { recording: null, answers: [], withheld: false } },
};

export default async function ReplayFixturePage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  if (process.env.NODE_ENV === "production") notFound();
  const sp = await searchParams;
  const state = STATES[param(sp, "state") ?? "recorded"] ?? STATES.recorded;
  const region = state.replay.withheld ? "Assam" : "ALL";
  return (
    <>
      <TopBar title="Replay fixtures" region={region} win={{ ok: false, error: { kind: "empty", detail: "fixture", endpoint: "none" } }} catalog={{ ok: true, value: {} }} />
      <PageBody>
        <ReplayPanel status={state.status} replay={state.replay} region={region} selected={param(sp, "q")} query="" />
      </PageBody>
    </>
  );
}
