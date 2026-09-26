// Replay mode (decisions D29): when the API doesn't answer live, the Ask page shows answers recorded by a full eval
// run, exactly as /api/ask returned them, with when, which model and how the eval scored each one. Nothing here
// calls a model. The selected question is a URL parameter (?q=), like every other filter on the dashboard.
import { CheckCircle, ClockCounterClockwise, EyeSlash, GridFour, Key, PresentationChart, Storefront, XCircle } from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";
import type { AskStatus, Recording, Replay, ReplayAnswer } from "@/lib/ask";
import { regionName, type Region } from "@/lib/config";
import { fmtDate } from "@/lib/format";
import { EmptyState } from "../states";
import { buttonClass, cx, ICON } from "../ui";
import { Answer } from "./answer";

const CATEGORIES: [string, string][] = [
  ["simple_lookup", "Simple lookups"],
  ["filtered_grouped", "Filtered and grouped"],
  ["time_comparison", "Time comparisons"],
  ["multi_hop_why", "Multi-hop “why”"],
  ["trap", "Traps that should be refused"],
];

const WHY_NOT_LIVE: Record<NonNullable<AskStatus["reason"]>, string> = {
  no_credentials: "This server has no Anthropic API key, so no question is sent to a model.",
  live_off: "The live analyst is switched off on this server (ASK_LIVE), so no question is sent to a model.",
};

const day = (iso: string) => fmtDate(iso.slice(0, 10));

/** Links to the pages that work the same in every mode: every figure there comes from the governed metrics. */
export function OtherPages({ query, className }: { query: string; className?: string }) {
  const links = [
    { href: "/", label: "Executive KPIs", icon: PresentationChart },
    { href: "/distributors", label: "Distributor 360", icon: Storefront },
    { href: "/quality", label: "Batch cohort heatmap", icon: GridFour },
  ];
  return (
    <ul className={cx("flex flex-wrap gap-2", className)}>
      {links.map(({ href, label, icon: Icon }) => (
        <li key={href}>
          <Link href={`${href}${query}`} className={buttonClass("secondary", "sm")}>
            <Icon size={16} {...ICON} aria-hidden />
            {label}
          </Link>
        </li>
      ))}
    </ul>
  );
}

function ModeNotice({ status, recording }: { status: AskStatus; recording: Recording | null }) {
  return (
    <section aria-labelledby="mode-title" className="flex items-start gap-3 rounded-panel border border-line bg-surface p-4 md:p-5">
      <Key size={22} {...ICON} className="mt-0.5 shrink-0 text-adhoc" aria-hidden />
      <div className="max-w-[72ch]">
        <h2 id="mode-title" className="text-[15px]/6 font-semibold text-ink">
          {recording
            ? "Replay mode: recorded answers, not live ones"
            : status.reason === "live_off"
              ? "The live analyst is switched off on this server"
              : "The live analyst isn't configured on this server"}
        </h2>
        <p className="mt-1 text-sm text-muted">
          {status.reason ? WHY_NOT_LIVE[status.reason] : null}{" "}
          {recording
            ? `The answers below were recorded by the evaluation run on ${day(recording.recorded_at)} with ${recording.model} (${recording.effort} effort), on data as of ${fmtDate(recording.as_of)}. Each is shown exactly as the API returned it, with the eval's verdict.`
            : "Replay mode shows answers recorded by a full evaluation run, and none has been recorded yet."}
        </p>
      </div>
    </section>
  );
}

function Verdict({ answer, long = false }: { answer: ReplayAnswer; long?: boolean }) {
  const ok = answer.eval.correct;
  const Icon = ok ? CheckCircle : XCircle;
  const text = long
    ? ok
      ? "The eval scored this answer correct against its golden answer."
      : "The eval scored this answer wrong against its golden answer. It's shown as recorded, not corrected."
    : ok
      ? "Scored correct"
      : "Scored wrong";
  return (
    <span className={cx("inline-flex items-center gap-1.5 text-xs", ok ? "text-good" : "text-danger")}>
      <Icon size={14} {...ICON} className="shrink-0" aria-hidden />
      {text}
    </span>
  );
}

function QuestionList({ answers, active, hrefFor }: { answers: ReplayAnswer[]; active: string; hrefFor: (id: string) => string }) {
  return (
    <nav aria-label="Recorded questions" className="flex flex-col gap-5 rounded-panel border border-line bg-surface p-4 md:p-5">
      {CATEGORIES.map(([key, label]) => {
        const items = answers.filter((a) => a.category === key);
        if (!items.length) return null;
        return (
          <div key={key}>
            <h3 className="text-xs font-semibold text-subtle">{label}</h3>
            <ul className="mt-2 flex flex-col gap-0.5">
              {items.map((a) => (
                <li key={a.id}>
                  <Link
                    href={hrefFor(a.id)}
                    scroll={false}
                    aria-current={a.id === active ? "page" : undefined}
                    className={cx(
                      "flex flex-col gap-0.5 rounded-control px-2.5 py-2 text-sm transition-colors duration-150 hover:bg-hover",
                      a.id === active ? "bg-hover text-ink" : "text-muted",
                    )}
                  >
                    <span className={a.id === active ? "font-medium" : undefined}>{a.question}</span>
                    <Verdict answer={a} />
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </nav>
  );
}

export function ReplayPanel({
  status,
  replay,
  region,
  selected,
  query,
}: {
  status: AskStatus;
  replay: Replay;
  region: Region;
  selected: string | undefined;
  /** The page's shared query (region, dates), for links that keep the viewer's claim. */
  query: string;
}) {
  const { recording, answers } = replay;
  const notice = <ModeNotice status={status} recording={recording} />;

  if (!recording) {
    return (
      <div className="flex flex-col gap-5">
        {notice}
        <section className="rounded-panel border border-line bg-surface px-4 md:px-5">
          <EmptyState
            icon={<ClockCounterClockwise size={20} {...ICON} aria-hidden />}
            title="No recorded answers yet"
            body={
              <>
                A complete run of the 40-question evaluation (<code className="font-mono text-[13px] text-ink">make eval</code>, with an API key) records every answer here.
                Until then there is nothing to replay, and no answer is invented in its place.
              </>
            }
            action={<OtherPages query={query} />}
          />
        </section>
      </div>
    );
  }

  if (replay.withheld) {
    const allRegions = new URLSearchParams(query.replace(/^\?/, ""));
    allRegions.delete("region");
    const qs = allRegions.toString();
    return (
      <div className="flex flex-col gap-5">
        {notice}
        <section className="rounded-panel border border-line bg-surface px-4 md:px-5">
          <EmptyState
            icon={<EyeSlash size={20} {...ICON} aria-hidden />}
            title={`Recorded under ${regionName(recording.region as Region)}, so hidden under ${regionName(region)}`}
            body={`These ${recording.count} answers were recorded viewing as ${regionName(recording.region as Region)}. Under the ${regionName(region)} claim they could show rows that claim can't see, so they aren't shown.`}
            action={
              <Link href={`/ask${qs ? `?${qs}` : ""}`} className={buttonClass("secondary", "sm")}>
                View as {regionName(recording.region as Region)}
              </Link>
            }
          />
        </section>
      </div>
    );
  }

  const current = answers.find((a) => a.id === selected) ?? answers[0];
  const hrefFor = (id: string) => {
    const params = new URLSearchParams(query.replace(/^\?/, ""));
    params.set("q", id);
    return `/ask?${params}`;
  };
  return (
    <div className="flex flex-col gap-5">
      {notice}
      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
        <div className="order-2 lg:order-1">
          <QuestionList answers={answers} active={current.id} hrefFor={hrefFor} />
        </div>
        <div className="order-1 flex flex-col gap-2 lg:sticky lg:top-24 lg:order-2">
          <Answer
            key={current.id}
            response={current.response}
            question={current.question}
            meta={`Recorded ${day(recording.recorded_at)} with ${current.served_model ?? recording.model}, viewing as ${regionName(recording.region as Region)}`}
          />
          <p className="px-1">
            <Verdict answer={current} long />
          </p>
        </div>
      </div>
    </div>
  );
}
