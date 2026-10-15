// Replay mode (decisions D29): when the API doesn't answer live, the Ask page shows answers recorded by a full eval
// run, exactly as /api/ask returned them, with when, which model and how the eval scored each one. Nothing here
// calls a model. The selected question is a URL parameter (?q=), like every other filter on the dashboard.
import { CheckCircle, ClockCounterClockwise, EyeSlash, GridFour, PresentationChart, Storefront, XCircle } from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";
import type { AskStatus, Recording, Replay, ReplayAnswer } from "@/lib/ask";
import { regionName, type Region } from "@/lib/config";
import { fmtDate, fmtNumber } from "@/lib/format";
import { EmptyState } from "../states";
import { buttonClass, cx, Figure, ICON, NAV_ACTIVE, NAV_IDLE, TYPE } from "../ui";
import { Answer } from "./answer";

const CATEGORIES: [string, string][] = [
  ["simple_lookup", "Simple lookups"],
  ["filtered_grouped", "Filtered and grouped"],
  ["time_comparison", "Time comparisons"],
  ["multi_hop_why", "Multi-hop “why”"],
  ["trap", "Traps that should be refused"],
];

const WHY_NOT_LIVE: Record<NonNullable<AskStatus["reason"]>, string> = {
  no_credentials: "This server has no model provider configured, so no question is sent to a model.",
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

/** The recording's own scorecard: how the eval judged the answers shown below, counted from them. */
function Scorecard({ answers }: { answers: ReplayAnswer[] }) {
  const correct = answers.filter((a) => a.eval.correct).length;
  const traps = answers.filter((a) => a.category === "trap");
  const figures: [string, string][] = [
    ["Scored correct", `${fmtNumber(correct)} of ${fmtNumber(answers.length)}`],
    ["Traps handled", `${fmtNumber(traps.filter((a) => a.eval.correct).length)} of ${fmtNumber(traps.length)}`],
    ["Governed answers", fmtNumber(answers.filter((a) => a.response.label === "governed_metric").length)],
  ];
  return (
    <dl className="cp-sheet grid shrink-0 grid-cols-3 gap-px overflow-clip rounded-panel border border-line bg-line">
      {figures.map(([label, value]) => (
        <div key={label} className="flex min-w-0 flex-col gap-0.5 bg-surface px-3.5 py-2.5">
          <dt className="text-[11.5px]/4 text-muted">{label}</dt>
          <dd>
            <Figure text={value} className={TYPE.figureLg} animate />
          </dd>
        </div>
      ))}
    </dl>
  );
}

function ModeNotice({ status, recording, answers }: { status: AskStatus; recording: Recording | null; answers?: ReplayAnswer[] }) {
  return (
    <section aria-labelledby="mode-title" className="flex flex-col gap-4 rounded-panel border border-line bg-surface p-4 md:p-5 xl:flex-row xl:items-center xl:justify-between">
      <div className="flex max-w-[76ch] items-start gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-control bg-adhoc-soft text-adhoc">
          <ClockCounterClockwise size={20} {...ICON} aria-hidden />
        </span>
        <div>
        <h2 id="mode-title" className={TYPE.stateTitle}>
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
      </div>
      {answers?.length ? <Scorecard answers={answers} /> : null}
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
  if (!long) {
    return (
      <span className={cx("mt-0.5 shrink-0", ok ? "text-good" : "text-danger")}>
        <Icon size={15} {...ICON} weight={ok ? "light" : "regular"} aria-hidden />
        <span className="sr-only">{text}</span>
      </span>
    );
  }
  return (
    <span className={cx("inline-flex items-center gap-1.5 text-xs", ok ? "text-good" : "text-danger")}>
      <Icon size={14} {...ICON} className="shrink-0" aria-hidden />
      {text}
    </span>
  );
}

function QuestionList({ answers, active, hrefFor }: { answers: ReplayAnswer[]; active: string; hrefFor: (id: string) => string }) {
  return (
    // From 1024px the list scrolls on its own beside the pinned answer, its category names pinned as it goes.
    <nav
      aria-label="Recorded questions"
      className="flex flex-col rounded-panel border border-line bg-surface lg:sticky lg:top-24 lg:max-h-[calc(100dvh-8rem)] lg:overflow-y-auto lg:overscroll-contain"
    >
      {CATEGORIES.map(([key, label]) => {
        const items = answers.filter((a) => a.category === key);
        if (!items.length) return null;
        const correct = items.filter((a) => a.eval.correct).length;
        return (
          <div key={key} className="border-b border-line pb-2 last:border-0">
            <h3 className="sticky top-0 z-[1] flex items-baseline justify-between gap-2 bg-surface/95 px-4 pt-3 pb-1.5 text-xs font-semibold text-ink backdrop-blur-sm">
              {label}
              <span className="font-normal text-subtle">
                {correct} of {items.length} correct
              </span>
            </h3>
            <ul className="flex flex-col gap-px px-2">
              {items.map((a) => (
                <li key={a.id}>
                  <Link
                    href={hrefFor(a.id)}
                    scroll={false}
                    aria-current={a.id === active ? "page" : undefined}
                    className={cx(
                      "flex items-start gap-2.5 rounded-control px-2 py-2 text-[13px]/5",
                      a.id === active ? NAV_ACTIVE : NAV_IDLE,
                    )}
                  >
                    <Verdict answer={a} />
                    <span className={a.id === active ? "font-medium" : undefined}>{a.question}</span>
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
  const notice = <ModeNotice status={status} recording={recording} answers={replay.withheld ? undefined : answers} />;

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
                A complete run of the 102-question evaluation (<code className="font-mono text-[13px] text-ink">make eval</code>, with an API key) records every answer here.
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
