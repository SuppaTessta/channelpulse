"use client";

import { ArrowClockwise, ChatCenteredText, GridFour, Key, PaperPlaneRight, PlugsConnected, PresentationChart, Storefront, Warning, X } from "@phosphor-icons/react";
import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { AskResponse } from "@/lib/ask";
import { API_URL, regionName, type Region } from "@/lib/config";
import { isAskResponse } from "@/lib/validate";
import { Answer, AnswerHeader, LabelBadge, PendingAnswer } from "./answer";
import { buttonClass, cx, ICON } from "../ui";

type Failure = { status: number | null; detail: string; retryAfter?: number; cancelled?: boolean };
type Entry = { id: string; question: string; region: Region; askedAt: string } & (
  | { state: "pending" }
  | { state: "answered"; response: AskResponse }
  | { state: "failed"; error: Failure }
);

const STORAGE_KEY = "channelpulse.ask.v1";
const MAX_QUESTION = 2000; // AskRequest.question max_length in api/app/main.py
const TIMEOUT_MS = 150_000; // a little over the agent's own 120 s budget

const STARTERS = [
  "What was primary sales value by region in FY26?",
  "Which distributors are at risk right now, and why?",
  "How did DSO change this quarter compared with last quarter?",
  "Which resin lots have elevated base-crack claims?",
  "What is the stock-out rate by region over the last 90 days?",
];

const clock = (iso: string) => new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });

async function readDetail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail)) return body.detail.map((d: { msg?: string }) => d.msg ?? "").join("; ");
    return JSON.stringify(body);
  } catch {
    return res.statusText || `HTTP ${res.status}`;
  }
}

const isUnconfigured = (e: Failure) => e.status === 503 && /llm not configured/i.test(e.detail);

/** The expected state on a machine without an Anthropic key: explained, with the pages that still work. */
function AnalystOffline({ pagesQuery }: { pagesQuery: string }) {
  const links = [
    { href: "/", label: "Executive KPIs", icon: PresentationChart },
    { href: "/distributors", label: "Distributor 360", icon: Storefront },
    { href: "/quality", label: "Batch cohort heatmap", icon: GridFour },
  ];
  return (
    <section aria-labelledby="offline-title" className="flex flex-col gap-3 rounded-panel border border-line bg-surface p-4 md:p-5">
      <div className="flex items-start gap-3">
        <Key size={22} {...ICON} className="mt-0.5 shrink-0 text-adhoc" aria-hidden />
        <div className="max-w-[68ch]">
          <h2 id="offline-title" className="text-[15px]/6 font-semibold text-ink">
            The analyst isn&apos;t configured on this server
          </h2>
          <p className="mt-1 text-base/7 text-muted">
            Ask ChannelPulse needs an Anthropic API key on the API server, set as <code className="font-mono text-[14px] text-ink">ANTHROPIC_API_KEY</code>. Until one is
            set, the API answers every question with &ldquo;LLM not configured&rdquo; and nothing is sent to a model.
          </p>
          <p className="mt-2 text-base/7 text-muted">
            Governed metrics still work everywhere else. Every figure on the other pages comes from the same semantic layer the analyst would query, with its SQL one click
            away.
          </p>
        </div>
      </div>
      <ul className="flex flex-wrap gap-2 pl-0 md:pl-9">
        {links.map(({ href, label, icon: Icon }) => (
          <li key={href}>
            <Link href={`${href}${pagesQuery}`} className={buttonClass("secondary", "sm")}>
              <Icon size={16} {...ICON} aria-hidden />
              {label}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Countdown({ until, children }: { until: number; children: (seconds: number) => ReactNode }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (now >= until) return;
    const t = setTimeout(() => setNow(Date.now()), 1000);
    return () => clearTimeout(t);
  }, [now, until]);
  return <>{children(Math.max(0, Math.ceil((until - now) / 1000)))}</>;
}

function FailedAnswer({ entry, onRetry, pagesQuery }: { entry: Entry & { state: "failed" }; onRetry: () => void; pagesQuery: string }) {
  const e = entry.error;
  const meta = `${clock(entry.askedAt)}, viewing as ${regionName(entry.region)}`;
  let title: string;
  let body: ReactNode;
  let icon = <Warning size={20} {...ICON} className="text-danger" aria-hidden />;
  if (isUnconfigured(e)) {
    return (
      <div className="flex flex-col gap-3">
        <AnswerHeader question={entry.question} meta={`${meta}, not answered`} />
        <AnalystOffline pagesQuery={pagesQuery} />
      </div>
    );
  }
  if (e.cancelled) {
    title = "You cancelled this question";
    body = "Nothing was answered. Ask it again when you're ready.";
    icon = <X size={20} {...ICON} className="text-subtle" aria-hidden />;
  } else if (e.status === 429) {
    const until = new Date(entry.askedAt).getTime() + (e.retryAfter ?? 10) * 1000;
    title = "Too many questions from this address";
    body = <Countdown until={until}>{(s) => (s > 0 ? `The demo limits how often one address can ask. Try again in ${s} seconds.` : "You can ask again now.")}</Countdown>;
  } else if (e.status === 503) {
    title = "Questions are paused";
    body = e.detail;
  } else if (e.status === 502 || e.status === 504) {
    title = "The model call didn't complete";
    body = `${e.detail} Governed metrics on the other pages are unaffected.`;
  } else if (e.status === 400 || e.status === 422) {
    title = "The API didn't accept this question";
    body = e.detail;
  } else if (e.status === null) {
    title = e.detail.startsWith("No answer") ? "No answer in time" : "Can't reach the ChannelPulse API";
    body = e.detail.startsWith("No answer") ? `${e.detail} Try a narrower question.` : `${e.detail} Check that the API server is running.`;
    icon = <PlugsConnected size={20} {...ICON} className="text-danger" aria-hidden />;
  } else {
    title = "The question couldn't be answered";
    body = `HTTP ${e.status}: ${e.detail}`;
  }
  return (
    <article className="flex flex-col gap-3 rounded-panel border border-line bg-surface p-4 md:p-5">
      <AnswerHeader question={entry.question} meta={`${meta}, not answered`} />
      <div className="flex items-start gap-3">
        <span className="mt-0.5 shrink-0">{icon}</span>
        <div className="max-w-[68ch]">
          <p className="text-[15px]/6 font-medium text-ink">{title}</p>
          <p className="mt-1 text-sm text-muted">{body}</p>
        </div>
      </div>
      <div className="pl-8">
        <Countdown until={e.status === 429 ? new Date(entry.askedAt).getTime() + (e.retryAfter ?? 10) * 1000 : 0}>
          {(s) => (
            <button type="button" onClick={onRetry} disabled={s > 0} className={buttonClass("secondary", "sm")}>
              <ArrowClockwise size={16} {...ICON} aria-hidden />
              Ask again
            </button>
          )}
        </Countdown>
      </div>
    </article>
  );
}

export function AskPanel({ region, pagesQuery }: { region: Region; pagesQuery: string }) {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [question, setQuestion] = useState("");
  const [announce, setAnnounce] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const [hydrated, setHydrated] = useState(false);
  const busy = entries.some((e) => e.state === "pending");
  const offline = entries.find((e) => e.state !== "pending") as Entry | undefined;
  const lastKnownOffline = !!offline && offline.state === "failed" && isUnconfigured(offline.error);

  // Q&A history lives in session storage: it survives a reload in this tab and nothing more.
  useEffect(() => {
    try {
      const saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? "[]") as Entry[];
      if (Array.isArray(saved)) setEntries(saved.filter((e) => e.state !== "pending"));
    } catch {
      // Storage blocked or corrupt: start empty.
    }
    setHydrated(true);
  }, []);
  useEffect(() => {
    if (!hydrated) return;
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(entries.filter((e) => e.state !== "pending")));
    } catch {
      // Storage full or blocked: history just won't survive a reload.
    }
  }, [entries, hydrated]);

  const settle = (id: string, next: { state: "answered"; response: AskResponse } | { state: "failed"; error: Failure }) =>
    setEntries((all) => all.map((e) => (e.id === id ? ({ ...e, ...next } as Entry) : e)));

  async function ask(text: string) {
    const q = text.trim().slice(0, MAX_QUESTION);
    if (!q || busy) return;
    const id = typeof crypto.randomUUID === "function" ? crypto.randomUUID() : String(Date.now());
    setEntries((all) => [{ id, question: q, region, askedAt: new Date().toISOString(), state: "pending" }, ...all]);
    setQuestion("");
    setAnnounce("Question sent. Waiting for the answer.");
    const controller = new AbortController();
    abortRef.current = controller;
    const timer = setTimeout(() => controller.abort("timeout"), TIMEOUT_MS);
    try {
      const res = await fetch(`${API_URL}/api/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Demo-Region": region },
        body: JSON.stringify({ question: q }),
        signal: controller.signal,
      });
      if (!res.ok) {
        const error: Failure = { status: res.status, detail: await readDetail(res), retryAfter: Number(res.headers.get("Retry-After")) || undefined };
        settle(id, { state: "failed", error });
        setAnnounce(isUnconfigured(error) ? "Not answered: the analyst isn't configured on this server." : "Not answered.");
      } else {
        const response: unknown = await res.json().catch(() => undefined);
        if (isAskResponse(response)) {
          settle(id, { state: "answered", response });
          setAnnounce(`Answer ready, labelled ${response.label.replace(/_/g, " ")}.`);
        } else {
          const detail = "The API's answer doesn't have the shape this page expects, so it isn't shown. The API and the dashboard are probably from different versions.";
          settle(id, { state: "failed", error: { status: res.status, detail } });
          setAnnounce("Not answered.");
        }
      }
    } catch {
      const reason = controller.signal.aborted ? controller.signal.reason : null;
      settle(id, {
        state: "failed",
        error:
          reason === "cancel"
            ? { status: null, detail: "Cancelled.", cancelled: true }
            : { status: null, detail: reason === "timeout" ? "No answer within two and a half minutes." : `Couldn't connect to ${API_URL}.` },
      });
      setAnnounce("Not answered.");
    } finally {
      clearTimeout(timer);
      abortRef.current = null;
    }
  }

  const [latest, ...earlier] = entries;
  const meta = (e: Entry) => `${clock(e.askedAt)}, viewing as ${regionName(e.region)}`;
  const render = (e: Entry) =>
    e.state === "pending" ? (
      <PendingAnswer
        question={e.question}
        meta={meta(e)}
        onCancel={
          <button type="button" className={cx(buttonClass("ghost", "sm"), "w-fit")} onClick={() => abortRef.current?.abort("cancel")}>
            <X size={16} {...ICON} aria-hidden />
            Cancel
          </button>
        }
      />
    ) : e.state === "answered" ? (
      <Answer response={e.response} question={e.question} meta={meta(e)} />
    ) : (
      <FailedAnswer entry={e} onRetry={() => ask(e.question)} pagesQuery={pagesQuery} />
    );

  return (
    <div className="flex flex-col gap-5">
      <form
        className="flex flex-col gap-3 rounded-panel border border-line bg-surface p-4 md:p-5"
        onSubmit={(e) => {
          e.preventDefault();
          ask(question);
        }}
      >
        <label htmlFor="question" className="text-sm font-semibold text-ink">
          Your question
        </label>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
          <textarea
            id="question"
            rows={2}
            value={question}
            maxLength={MAX_QUESTION}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                ask(question);
              }
            }}
            aria-describedby="question-help"
            placeholder="For example, which region's DSO rose most this quarter?"
            className="min-h-[76px] flex-1 resize-y rounded-control border border-control bg-surface px-3 py-2.5 text-base/6 text-ink placeholder:text-subtle"
          />
          <button type="submit" disabled={busy || !question.trim()} className={cx(buttonClass("primary", "md"), "sm:h-10")}>
            <PaperPlaneRight size={18} {...ICON} aria-hidden />
            {busy ? "Asking" : "Ask"}
          </button>
        </div>
        <p id="question-help" className="text-xs text-muted">
          Answers use governed metrics first and show the SQL behind every figure. Enter sends, Shift and Enter adds a line. Viewing as {regionName(region)}.
        </p>
        <div className="flex flex-col gap-2 border-t border-line pt-3">
          <p className="text-xs text-muted">Try one of these</p>
          <ul className="flex flex-wrap gap-2">
            {STARTERS.map((s) => (
              <li key={s}>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => ask(s)}
                  className="min-h-10 rounded-full border border-line-strong bg-surface px-3 py-1.5 text-left text-[13px] text-ink transition-colors duration-150 hover:border-control hover:bg-hover disabled:opacity-45 md:min-h-8"
                >
                  {s}
                </button>
              </li>
            ))}
          </ul>
        </div>
      </form>
      <p className="sr-only" role="status" aria-live="polite">
        {announce}
      </p>
      {lastKnownOffline && latest?.state === "pending" ? <AnalystOffline pagesQuery={pagesQuery} /> : null}
      {latest ? (
        <section aria-label="Latest answer">{render(latest)}</section>
      ) : (
        <div className="flex items-start gap-3 py-2 text-muted">
          <ChatCenteredText size={22} {...ICON} className="mt-0.5 shrink-0 text-subtle" aria-hidden />
          <p className="max-w-[68ch] text-base/7">
            Ask about sales, channel stock, collections or warranty claims. Each answer is labelled governed metric, ad-hoc SQL to verify, or refused, and carries the queries
            that produced it.
          </p>
        </div>
      )}
      {earlier.length ? (
        <section aria-labelledby="history-title" className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <h2 id="history-title" className="text-sm font-semibold text-ink">
              Earlier in this session
            </h2>
            <button type="button" className={buttonClass("ghost", "sm")} onClick={() => setEntries(latest ? [latest] : [])}>
              Clear earlier questions
            </button>
          </div>
          <ul className="flex flex-col gap-2">
            {earlier.map((e) => (
              <li key={e.id}>
                <details className="group rounded-panel border border-line bg-surface">
                  <summary className="flex min-h-11 flex-wrap items-center gap-2 px-4 py-2 text-sm text-ink">
                    {e.state === "answered" ? <LabelBadge label={e.response.label} /> : <span className="text-xs text-muted">Not answered</span>}
                    <span className="min-w-0 flex-1 font-medium">{e.question}</span>
                    <span className="text-xs text-subtle">{clock(e.askedAt)}</span>
                  </summary>
                  <div className="border-t border-line p-3">{render(e)}</div>
                </details>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
