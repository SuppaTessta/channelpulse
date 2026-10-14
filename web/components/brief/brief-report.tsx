import { Info, SealCheck, ShieldWarning } from "@phosphor-icons/react/dist/ssr";
import type { ReactNode } from "react";
import { getBrief } from "@/lib/api";
import { footnoteNumbers, type Brief, type BriefFact } from "@/lib/brief";
import type { Region } from "@/lib/config";
import { fmtDate, fmtRange } from "@/lib/format";
import { SqlBlock } from "../sql";
import { ErrorState } from "../states";
import { cx, Figure, ICON, Skeleton } from "../ui";
import { FactRef } from "./fact-ref";

/** What a cited fact is and where it came from: the same block in the popover and, without the SQL, in the endnotes. */
function FactCard({ n, fact }: { n: number; fact: BriefFact }) {
  return (
    <>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-xs text-muted">Source {n}</p>
          <p className="text-sm font-semibold text-ink">{fact.label}</p>
        </div>
        <Figure text={fact.display} className="shrink-0 text-lg/6 font-semibold tracking-[-0.02em] text-ink" />
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        {fact.metric ? (
          <>
            <dt className="text-muted">Metric</dt>
            <dd className="font-mono text-ink [overflow-wrap:anywhere]">{fact.metric}</dd>
          </>
        ) : null}
        {fact.source ? (
          <>
            <dt className="text-muted">Source</dt>
            <dd className="text-ink">{fact.source}</dd>
          </>
        ) : null}
        <dt className="text-muted">Kind</dt>
        <dd className="text-ink">{fact.kind}</dd>
      </dl>
      {fact.sql ? <SqlBlock sql={fact.sql} /> : <p className="text-xs text-subtle">No SQL recorded for this fact.</p>}
    </>
  );
}

function CheckLine({ brief }: { brief: Brief }) {
  const n = brief.check.queries_rechecked;
  if (brief.status === "verified") {
    return (
      <p role="status" className="flex items-center gap-2 rounded-control bg-accent-soft px-3 py-2 text-sm font-medium text-ink print:bg-transparent print:px-0">
        <SealCheck size={18} {...ICON} weight="regular" className="shrink-0 text-accent" aria-hidden />
        Numbers check passed: {n} {n === 1 ? "query" : "queries"} re-executed
      </p>
    );
  }
  return (
    <div role="status" className="flex flex-col gap-2 rounded-control bg-danger-soft px-3 py-2.5 text-sm text-ink">
      <p className="flex items-center gap-2 font-medium">
        <ShieldWarning size={18} {...ICON} weight="regular" className="shrink-0 text-danger" aria-hidden />
        Numbers check failed, so this brief is withheld
      </p>
      <p className="text-muted">
        The API re-ran {n} {n === 1 ? "query" : "queries"} behind the brief&apos;s figures and they didn&apos;t all agree with the draft. No sentence is shown until they do.
      </p>
      {brief.check.problems.length ? (
        <ul className="ml-6 list-disc space-y-1 text-[13px] marker:text-danger">
          {brief.check.problems.map((p, i) => (
            <li key={i}>{p}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function NarrationNote({ brief }: { brief: Brief }) {
  const { by, model, blocked } = brief.narration;
  const reasons = blocked ?? [];
  if (by === "model") {
    return <p className="text-xs text-subtle">Written by {model ?? "a model"} from the checked facts; every figure is a cited fact.</p>;
  }
  return (
    <div className="flex items-start gap-2 text-xs text-muted">
      <Info size={15} {...ICON} className="mt-px shrink-0 text-subtle" aria-hidden />
      <div>
        <p>Written from the template, not by a model.{reasons.length ? " The model's draft was set aside:" : ""}</p>
        {reasons.length ? (
          <ul className="mt-1 ml-4 list-disc space-y-0.5">
            {reasons.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}

/** The brief as a printed one-page report: masthead, the numbers check, the sections, then the numbered sources. */
export async function BriefReport({ week, region }: { week: string; region: Region }) {
  const r = await getBrief(week, region);
  if (!r.ok) {
    return (
      <section aria-label="Weekly Brief" className="mx-auto w-full max-w-[800px] rounded-panel border border-line bg-surface px-4 md:px-6">
        <ErrorState error={r.error} />
      </section>
    );
  }
  const brief = r.value;
  const numbers = footnoteNumbers(brief);
  const verified = brief.status === "verified";
  const cited = [...numbers.entries()];

  return (
    <article
      aria-labelledby="brief-title"
      className="mx-auto flex w-full max-w-[800px] flex-col gap-8 rounded-panel border border-line bg-surface px-5 py-7 shadow-[0_1px_2px_rgb(22_38_48/0.04)] md:px-12 md:py-12 print:max-w-none print:border-0 print:p-0 print:shadow-none"
    >
      <header className={cx("flex flex-col gap-4", verified && "border-b border-line pb-6")}>
        <div>
          <h2 id="brief-title" className="text-[26px]/8 font-semibold tracking-[-0.02em] text-balance text-ink md:text-[30px]/9">
            Weekly Channel &amp; Quality Brief
          </h2>
          <p className="mt-1.5 text-[15px] text-ink">
            {fmtRange({ from: brief.week.start, to: brief.week.end })}
            {brief.provisional ? <span className="text-muted">. Sell-out for this week is still provisional.</span> : null}
          </p>
          <p className="mt-0.5 text-xs text-subtle">Gangasagar Polymers, data as of {fmtDate(brief.as_of)}</p>
        </div>
        <CheckLine brief={brief} />
        {verified ? <NarrationNote brief={brief} /> : null}
      </header>

      {verified ? (
        <>
          <div className="flex flex-col gap-7">
            {brief.sections.map((s, si) => (
              <section key={si} aria-labelledby={`brief-s${si}`} className="flex flex-col gap-2 break-inside-avoid">
                <h3 id={`brief-s${si}`} className="text-base font-semibold text-ink">
                  {s.title}
                </h3>
                <p className="max-w-[68ch] text-[16px]/7 text-pretty text-ink">
                  {s.sentences.map((sentence, i) => (
                    <span key={i}>
                      {sentence.text}
                      {sentence.facts
                        .filter((id) => numbers.has(id))
                        .map((id) => (
                          <FactRef key={id} n={numbers.get(id)!} label={brief.facts[id].label}>
                            <FactCard n={numbers.get(id)!} fact={brief.facts[id]} />
                          </FactRef>
                        ))}{" "}
                    </span>
                  ))}
                </p>
              </section>
            ))}
          </div>

          {cited.length ? (
            <footer className="flex flex-col gap-3 border-t border-line pt-6">
              <h3 className="text-sm font-semibold text-ink">Sources</h3>
              <p className="text-xs text-muted">Each number above is one of these facts. Select a footnote marker to see its SQL.</p>
              <ol className="grid grid-cols-1 gap-x-8 gap-y-1.5 text-[13px] sm:grid-cols-2 print:grid-cols-2">
                {cited.map(([id, n]) => {
                  const f = brief.facts[id];
                  return (
                    <li key={id} className="flex gap-2">
                      <span className="w-5 shrink-0 text-right font-semibold text-accent tabular-nums print:text-ink">{n}</span>
                      <span className="min-w-0">
                        <span className="text-ink">{f.label}</span>
                        <span className="text-muted">, {f.display}</span>
                        {f.metric ? <span className="block font-mono text-[11.5px] text-subtle [overflow-wrap:anywhere]">{f.metric}</span> : null}
                      </span>
                    </li>
                  );
                })}
              </ol>
            </footer>
          ) : null}
        </>
      ) : null}
    </article>
  );
}

export function BriefSkeleton({ className }: { className?: string }) {
  return (
    <div aria-busy="true" className={cx("mx-auto flex w-full max-w-[800px] flex-col gap-4 rounded-panel border border-line bg-surface px-5 py-7 md:px-12 md:py-12", className)}>
      <span className="sr-only">Loading the brief, and re-running the queries behind its numbers</span>
      <Skeleton className="h-4 w-64" />
      <Skeleton className="h-8 w-3/4" />
      <Skeleton className="h-9 w-full" />
      {Array.from({ length: 3 }, (_, i) => (
        <div key={i} className="mt-4 flex flex-col gap-2">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-11/12" />
          <Skeleton className="h-4 w-4/5" />
        </div>
      ))}
    </div>
  );
}

export function BriefUnavailable({ children }: { children: ReactNode }) {
  return <section className="mx-auto w-full max-w-[800px] rounded-panel border border-line bg-surface px-4 md:px-6">{children}</section>;
}
