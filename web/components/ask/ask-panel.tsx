"use client";

import { ArrowClockwise, CaretRight, ChatCenteredText, Key, PaperPlaneRight, PlugsConnected, Warning, X } from "@phosphor-icons/react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import type { AskResponse, FreeAllowance } from "@/lib/ask";
import { API_URL, keySafe, regionName, type Region } from "@/lib/config";
import { isAskResponse, isFreeAllowance } from "@/lib/validate";
import { Answer, AnswerHeader, LabelBadge, PendingAnswer } from "./answer";
import { OtherPages } from "./replay-panel";
import { buttonClass, cx, ICON, TYPE } from "../ui";

type Failure = { status: number | null; code?: string; detail: string; retryAfter?: number; cancelled?: boolean };
type Entry = { id: string; question: string; region: Region; askedAt: string } & (
  | { state: "pending" }
  | { state: "answered"; response: AskResponse }
  | { state: "failed"; error: Failure }
);

const STORAGE_KEY = "channelpulse.ask.v1";
const MAX_QUESTION = 2000; // AskRequest.question max_length in api/app/main.py
const TIMEOUT_MS = 150_000; // a little over the agent's own 120 s budget

// Two governed questions both recorded models answered correctly (FG01 and FG03 in api/app/recordings), and a trap the
// analyst should refuse. A chip fills the box and doesn't ask, so no free question is spent by accident.
const STARTERS = [
  { question: "Break down FY26 primary sales value by sales region." },
  { question: "Which five distributors had the highest DSO on invoices raised in FY26?" },
  { question: "What's the owner's phone number?", trap: true },
];

// The error codes of POST /api/ask that this panel answers itself; any other code falls back to its HTTP status.
const KEY_ERRORS: Record<string, string> = {
  key_invalid: "That doesn't look like an Anthropic key. They start with sk-ant-.",
  key_rejected: "Anthropic didn't accept that key. Check it, or make a new one.",
  key_limited: "Your key hit an Anthropic rate or spend limit.",
};
const FREE_ERRORS: Record<string, { title: string; reason: NonNullable<FreeAllowance["reason"]> }> = {
  free_used: { title: "Today's free questions are used up", reason: "used" },
  free_paused: { title: "Free questions are paused right now", reason: "paused" },
  free_unavailable: { title: "Free questions aren't offered here", reason: "no_credentials" },
};
const INSECURE = "This page won't send a key over an unencrypted connection.";
const KEY_SAFE = keySafe(API_URL); // fixed at build time, like API_URL, so the panel says so as it opens
const KEY_FORMAT = /^sk-ant-[A-Za-z0-9_-]{20,200}$/; // the API's own check (key_invalid)
const KEY_IN_TEXT = /sk-ant-[A-Za-z0-9_-]{20,}/;
const KEY_IN_QUESTION = "That looks like an API key. Paste it in the key field instead.";
const STATUS_TIMEOUT_MS = 8_000;
const TEXT_LINK = "text-accent underline underline-offset-4 hover:text-ink";
const TEXT_BUTTON = cx("inline-flex min-h-11 items-center rounded-control font-medium md:min-h-8", TEXT_LINK);

/** The allowance line's source: the visitor's own status, fetched from the browser so the API sees their address. */
type Allowance = FreeAllowance | "checking" | "unavailable";

async function fetchAllowance(): Promise<Allowance> {
  try {
    const res = await fetch(`${API_URL}/api/ask/status`, { cache: "no-store", signal: AbortSignal.timeout(STATUS_TIMEOUT_MS) });
    const body = res.ok ? await res.json() : null;
    return isFreeAllowance(body?.free) ? body.free : "unavailable";
  } catch {
    return "unavailable";
  }
}

const clock = (iso: string) => new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });

/** `{"detail": {"code", "message"}}` from this API, a plain string from an older one, or FastAPI's 422 list. */
async function readError(res: Response): Promise<{ code?: string; detail: string }> {
  try {
    const body = await res.json();
    const detail = body?.detail;
    if (typeof detail?.code === "string") return { code: detail.code, detail: String(detail.message ?? detail.code) };
    if (typeof detail === "string") return { detail };
    if (Array.isArray(detail)) return { detail: detail.map((d: { msg?: string }) => d.msg ?? "").join("; ") };
    return { detail: JSON.stringify(body) };
  } catch {
    return { detail: res.statusText || `HTTP ${res.status}` };
  }
}

const isUnconfigured = (e: Failure) =>
  e.code ? e.code === "live_off" : e.status === 503 && /llm not configured|live mode is off/i.test(e.detail);
const isRateLimited = (e: Failure) => (e.code ? e.code === "rate_limited" : e.status === 429);
// Turned away before the agent ran, so the API recorded nothing to count against the allowance.
const uncounted = (e: Failure) => isRateLimited(e) || isUnconfigured(e) || e.code === "free_unavailable" || e.status === 422;

/** Live mode was on when the page loaded, but the API now says it isn't configured: explained, with the pages that still work. */
function AnalystOffline({ pagesQuery }: { pagesQuery: string }) {
  return (
    <section aria-labelledby="offline-title" className="flex flex-col gap-3 rounded-panel border border-line bg-surface p-4 md:p-5">
      <div className="flex items-start gap-3">
        <Key size={22} {...ICON} className="mt-0.5 shrink-0 text-adhoc" aria-hidden />
        <div className="max-w-[68ch]">
          <h2 id="offline-title" className={TYPE.stateTitle}>
            The analyst isn&apos;t configured on this server
          </h2>
          <p className="mt-1 text-base/7 text-muted">
            The API answered that live questions are off, so nothing was sent to a model. Reload the page to see the recorded answers from the last evaluation run, if
            there is one.
          </p>
          <p className="mt-2 text-base/7 text-muted">
            Governed metrics still work everywhere else. Every figure on the other pages comes from the same semantic layer the analyst would query, with its SQL one click
            away.
          </p>
        </div>
      </div>
      <OtherPages query={pagesQuery} className="pl-0 md:pl-9" />
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

function FailedAnswer({
  entry,
  onRetry,
  onUseKey,
  keySet,
  pagesQuery,
}: {
  entry: Entry & { state: "failed" };
  onRetry: () => void;
  onUseKey: () => void;
  keySet: boolean;
  pagesQuery: string;
}) {
  const e = entry.error;
  // Asking again without a key would only meet the same answer: the way on is a key.
  const offerKey = !keySet && !!e.code && !!FREE_ERRORS[e.code];
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
  } else if (e.code && KEY_ERRORS[e.code]) {
    title = "Your key didn't work";
    body = KEY_ERRORS[e.code];
    icon = <Key size={20} {...ICON} className="text-danger" aria-hidden />;
  } else if (e.code && FREE_ERRORS[e.code]) {
    title = FREE_ERRORS[e.code].title;
    body = e.detail;
    icon = <Key size={20} {...ICON} className="text-adhoc" aria-hidden />;
  } else if (isRateLimited(e)) {
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
        {offerKey ? (
          <button type="button" onClick={onUseKey} className={buttonClass("secondary", "sm")}>
            <Key size={16} {...ICON} aria-hidden />
            Use your own key
          </button>
        ) : (
          <Countdown until={isRateLimited(e) ? new Date(entry.askedAt).getTime() + (e.retryAfter ?? 10) * 1000 : 0}>
            {(s) => (
              <button type="button" onClick={onRetry} disabled={s > 0} className={buttonClass("secondary", "sm")}>
                <ArrowClockwise size={16} {...ICON} aria-hidden />
                Ask again
              </button>
            )}
          </Countdown>
        )}
      </div>
    </article>
  );
}

export function AskPanel({ region, pagesQuery }: { region: Region; pagesQuery: string }) {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [question, setQuestion] = useState("");
  const [announce, setAnnounce] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const questionRef = useRef<HTMLTextAreaElement>(null);
  const [hydrated, setHydrated] = useState(false);
  const [free, setFree] = useState<Allowance>("checking");
  // The visitor's Anthropic key lives here and nowhere else: not in storage, a cookie or the URL, so a reload drops it.
  const [key, setKey] = useState("");
  const [draft, setDraft] = useState("");
  const [keyError, setKeyError] = useState("");
  const [keyOpen, setKeyOpen] = useState(false);
  const keyRef = useRef<HTMLInputElement>(null);
  const [questionError, setQuestionError] = useState("");
  const router = useRouter();
  const busy = entries.some((e) => e.state === "pending");
  const offline = entries.find((e) => e.state !== "pending") as Entry | undefined;
  const lastKnownOffline = !!offline && offline.state === "failed" && isUnconfigured(offline.error);

  // Status fetches can land out of order (a slow one from mount, a quick one after an answer): only the newest wins.
  const freeSeq = useRef(0);
  const showFree = useCallback((next: Allowance | Promise<Allowance>) => {
    const n = ++freeSeq.current;
    if (!(next instanceof Promise)) setFree(next);
    else
      next.then((a) => {
        if (n === freeSeq.current) setFree(a);
      });
  }, []);

  // Q&A history lives in session storage: it survives a reload in this tab and nothing more.
  useEffect(() => {
    try {
      const saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? "[]") as Entry[];
      if (Array.isArray(saved)) setEntries(saved.filter((e) => e.state !== "pending"));
    } catch {
      // Storage blocked or corrupt: start empty.
    }
    setHydrated(true);
    showFree(fetchAllowance());
    // Back on this tab, the count may be stale: another tab asked, or a new UTC day began.
    const onVisible = () => {
      if (document.visibilityState === "visible") showFree(fetchAllowance());
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [showFree]);
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

  function openKeyPanel() {
    setKeyOpen(true);
    keyRef.current?.focus(); // already open; a newly opened field focuses itself as it mounts
  }

  /** An unapplied draft goes with the panel. */
  function closeKeyPanel() {
    setKeyOpen(false);
    setDraft("");
    setKeyError("");
  }

  function applyKey() {
    const next = draft.trim();
    if (!next || !KEY_SAFE) return;
    // Checked here as the API checks it: a zero-width space or a typographic dash from a pasted document would
    // otherwise make the request itself fail, and read as the API being unreachable.
    if (!KEY_FORMAT.test(next)) {
      setKeyError(KEY_ERRORS.key_invalid);
      keyRef.current?.focus();
      return;
    }
    setKey(next);
    closeKeyPanel();
    setAnnounce("Your key is set. Questions now use it, not the free allowance.");
    questionRef.current?.focus();
  }

  function forgetKey() {
    setKey("");
    setDraft("");
    setKeyError("");
    setAnnounce("Your key is forgotten.");
    questionRef.current?.focus();
  }

  /** A key belongs in the key field: one in the question is never sent, kept in the history, or shown in an answer. */
  function refuseKeyInQuestion() {
    setQuestionError(KEY_IN_QUESTION);
    openKeyPanel();
  }

  async function ask(text: string) {
    const q = text.trim().slice(0, MAX_QUESTION);
    if (!q || busy) return;
    if (KEY_IN_TEXT.test(q)) return refuseKeyInQuestion();
    setQuestionError("");
    const id = typeof crypto.randomUUID === "function" ? crypto.randomUUID() : String(Date.now());
    setEntries((all) => [{ id, question: q, region, askedAt: new Date().toISOString(), state: "pending" }, ...all]);
    setQuestion("");
    setAnnounce("Question sent. Waiting for the answer.");
    const controller = new AbortController();
    abortRef.current = controller;
    const timer = setTimeout(() => controller.abort("timeout"), TIMEOUT_MS);
    const withKey = key;
    // The API counts every owner-paid question it runs, whatever the outcome (an answer, a model error, a timeout,
    // a cancel), so the line re-reads the count once each settles instead of doing arithmetic of its own.
    let recount = !withKey;
    try {
      const res = await fetch(`${API_URL}/api/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Demo-Region": region, ...(withKey ? { "X-Anthropic-Key": withKey } : {}) },
        body: JSON.stringify({ question: q }),
        signal: controller.signal,
      });
      if (!res.ok) {
        const error: Failure = { status: res.status, ...(await readError(res)), retryAfter: Number(res.headers.get("Retry-After")) || undefined };
        if (error.code === "key_in_question") {
          recount = false;
          setEntries((all) => all.filter((e) => e.id !== id));
          setQuestion((current) => current || q); // back in the box to edit
          setAnnounce("");
          refuseKeyInQuestion();
          return;
        }
        if (uncounted(error)) recount = false;
        settle(id, { state: "failed", error });
        const freeError = error.code ? FREE_ERRORS[error.code] : undefined;
        if (error.code && KEY_ERRORS[error.code]) {
          setKeyError(KEY_ERRORS[error.code]);
          openKeyPanel();
        } else if (freeError) {
          showFree({ limit: 0, remaining: 0, available: false, reason: freeError.reason }); // until the re-read lands
          openKeyPanel();
        } else if (isUnconfigured(error)) {
          router.refresh(); // the page asks for status again and shows the replay view
        }
        setAnnounce(
          isUnconfigured(error)
            ? "Not answered: the analyst isn't configured on this server."
            : freeError
              ? `Not answered: ${freeError.title}. You can use your own key.`
              : "Not answered.",
        );
      } else {
        const response: unknown = await res.json().catch(() => undefined);
        if (isAskResponse(response)) {
          settle(id, { state: "answered", response });
          setAnnounce(`Answer ready, labelled ${response.label.replace(/_/g, " ")}.`);
          if (withKey) setKeyError("");
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
      if (recount) showFree(fetchAllowance());
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
      <FailedAnswer entry={e} onRetry={() => ask(e.question)} onUseKey={openKeyPanel} keySet={!!key} pagesQuery={pagesQuery} />
    );

  const ownKey = (label: string) => (
    <button type="button" aria-expanded={keyOpen} aria-controls="key-panel" onClick={keyOpen ? closeKeyPanel : openKeyPanel} className={TEXT_BUTTON}>
      {label}
    </button>
  );
  const keyNote = KEY_SAFE ? keyError : INSECURE;
  const allowance = key ? (
    <>
      Asking with your key · free questions untouched ·{" "}
      <button type="button" onClick={forgetKey} className={TEXT_BUTTON}>
        Forget key
      </button>
    </>
  ) : free === "checking" ? (
    <>Checking free questions… · {ownKey("Use your own key")}</>
  ) : free === "unavailable" ? (
    <>Free questions are unavailable right now · {ownKey("Use your own key")}</>
  ) : free.available ? (
    <>
      {free.remaining} of {free.limit} free questions left today · {ownKey("Use your own key")}
    </>
  ) : free.reason === "used" ? (
    <>Today&apos;s free questions are used up · {ownKey("Use your own key to keep asking")}</>
  ) : free.reason === "paused" ? (
    <>Free questions are paused right now · {ownKey("Use your own key")}</>
  ) : (
    <>Free questions aren&apos;t offered here · {ownKey("Use your own key")}</>
  );

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-3 rounded-panel border border-line bg-surface p-4 md:p-5">
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            ask(question);
          }}
        >
          <label htmlFor="question" className={TYPE.panelTitle}>
            Your question
          </label>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
            <textarea
              id="question"
              ref={questionRef}
              rows={3}
              value={question}
              maxLength={MAX_QUESTION}
              onChange={(e) => {
                setQuestion(e.target.value);
                setQuestionError("");
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  ask(question);
                }
              }}
              aria-invalid={questionError ? true : undefined}
              aria-describedby={questionError ? "question-error question-help" : "question-help"}
              placeholder="For example, which region's DSO rose most this quarter?"
              className="min-h-[112px] flex-1 resize-y rounded-control border border-control bg-surface px-3.5 py-3 font-display text-[18px]/7 text-ink placeholder:text-subtle"
            />
            <button type="submit" disabled={busy || !question.trim()} className={cx(buttonClass("primary", "md"), "sm:h-10")}>
              <PaperPlaneRight size={18} {...ICON} aria-hidden />
              {busy ? "Asking" : "Ask"}
            </button>
          </div>
          {questionError ? (
            <p id="question-error" role="alert" className="text-sm text-danger">
              {questionError}
            </p>
          ) : null}
          <p id="question-help" className="text-xs text-muted">
            Answers use governed metrics first and show the SQL behind every figure. Enter sends, Shift and Enter adds a line. Viewing as {regionName(region)}.
          </p>
        </form>
        <div className="flex flex-col gap-2 border-t border-line pt-3">
          <p id="starters-title" className="text-xs text-muted">
            Try one of these
          </p>
          <ul aria-labelledby="starters-title" className="flex flex-wrap gap-2">
            {STARTERS.map(({ question: q, trap }) => (
              <li key={q}>
                <button
                  type="button"
                  onClick={() => {
                    setQuestion(q);
                    questionRef.current?.focus();
                  }}
                  className="min-h-11 rounded-full border border-line-strong bg-surface px-3 py-1.5 text-left text-[13px] text-ink transition-colors duration-150 hover:border-control hover:bg-hover md:min-h-8"
                >
                  {trap ? <span className="text-muted">Try to trip it: </span> : null}
                  {q}
                </button>
              </li>
            ))}
          </ul>
        </div>
        <p role="status" aria-live="polite" data-testid="allowance" className="border-t border-line pt-3 text-sm/6 text-muted">
          {allowance}
        </p>
        {keyOpen ? (
          // Not a <form>: Chrome offers to save a submitted password field whatever autoComplete says. The data-
          // attributes ask 1Password, LastPass, Bitwarden and Dashlane to leave the field alone.
          <div id="key-panel" role="group" aria-label="Use your own Anthropic key" className="flex flex-col gap-2 rounded-control bg-sunken p-3 ring-1 ring-line ring-inset md:p-4">
            <div className="flex items-center justify-between gap-2">
              <label htmlFor="anthropic-key" className={TYPE.subhead}>
                Your Anthropic API key
              </label>
              <button
                type="button"
                aria-label="Close key panel"
                onClick={() => {
                  closeKeyPanel();
                  questionRef.current?.focus();
                }}
                className={buttonClass("ghost", "icon")}
              >
                <X size={16} {...ICON} aria-hidden />
              </button>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row">
              <input
                id="anthropic-key"
                ref={keyRef}
                type="password"
                autoComplete="off"
                spellCheck={false}
                autoCapitalize="off"
                autoFocus
                data-1p-ignore=""
                data-lpignore="true"
                data-bwignore=""
                data-form-type="other"
                disabled={!KEY_SAFE}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    applyKey();
                  }
                }}
                aria-invalid={keyNote ? true : undefined}
                aria-describedby={keyNote ? "key-error key-help" : "key-help"}
                placeholder="sk-ant-…"
                className="h-11 min-w-0 rounded-control sm:flex-1 border border-control bg-surface px-3 font-mono text-sm text-ink placeholder:text-subtle disabled:cursor-not-allowed disabled:opacity-45 md:h-9"
              />
              <button type="button" onClick={applyKey} disabled={!draft.trim() || !KEY_SAFE} className={cx(buttonClass("primary", "md"), "max-md:h-11")}>
                Use key
              </button>
              {key ? (
                <button type="button" onClick={forgetKey} className={cx(buttonClass("secondary", "md"), "max-md:h-11")}>
                  Forget key
                </button>
              ) : null}
            </div>
            {keyNote ? (
              <p id="key-error" role="alert" className="text-sm text-danger">
                {keyNote}
              </p>
            ) : null}
            <p id="key-help" className="max-w-[72ch] text-xs/5 text-muted">
              Your key stays in this tab&apos;s memory. It goes only to the ChannelPulse API over HTTPS, one question at a time, and is never stored or logged.
              If your browser offers to save it, choose Never. Safest: make a key in its own Anthropic workspace with a $1 spend limit, and revoke it when
              you&apos;re done. Keys are made and revoked in the{" "}
              <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noreferrer" className={TEXT_LINK}>
                Anthropic Console
              </a>
              , and the{" "}
              <a href="https://github.com/SuppaTessta/channelpulse" target="_blank" rel="noreferrer" className={TEXT_LINK}>
                GitHub repo
              </a>{" "}
              gives this demo&apos;s official address. What&apos;s left is trust: this server holds the key while it answers each question, and an extension in
              your own browser can read any page, this one included.
            </p>
          </div>
        ) : null}
      </div>
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
            <h2 id="history-title" className={TYPE.subhead}>
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

/**
 * The scored examples under the ask box: closed unless one is chosen (?q=). They mount on first open, so the
 * scorecard's figures count up where they're seen, not unseen inside the closed details.
 */
export function ScoredExamples({ open, children }: { open: boolean; children: ReactNode }) {
  const [shown, setShown] = useState(open);
  return (
    <details
      open={open}
      onToggle={(e) => {
        if (e.currentTarget.open) setShown(true);
      }}
      className="group/examples"
    >
      <summary className="flex min-h-11 w-fit list-none items-center gap-1.5 rounded-control text-sm font-medium text-ink hover:text-accent [&::-webkit-details-marker]:hidden">
        <CaretRight size={14} {...ICON} className="transition-transform duration-150 ease-out group-open/examples:rotate-90" aria-hidden />
        Scored examples · browse
      </summary>
      {shown ? <div className="mt-3">{children}</div> : null}
    </details>
  );
}
