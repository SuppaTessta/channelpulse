import { Database, Hourglass, PlugsConnected, Warning, WarningOctagon } from "@phosphor-icons/react/dist/ssr";
import type { ReactNode } from "react";
import type { ApiError } from "@/lib/api";
import { AutoRefresh } from "./auto-refresh";
import { RetryButton } from "./retry-button";
import { cx, ICON } from "./ui";

/** What happened and what to do, for each way the governed API can fail. */
export function describeError(error: ApiError): { title: string; body: string; icon: ReactNode } {
  const icon = (I: typeof Warning) => <I size={20} {...ICON} aria-hidden />;
  if (error.kind === "unreachable") {
    return {
      title: "Can't reach the ChannelPulse API",
      body: "The dashboard couldn't connect to the API server. Check that it's running, then retry. The address it tried is under Technical detail.",
      icon: icon(PlugsConnected),
    };
  }
  if (error.kind === "waking") {
    return {
      title: "The API is waking up",
      body: "The demo's API sleeps after 15 idle minutes on its free plan and takes about a minute to start. This panel retries on its own.",
      icon: icon(Hourglass),
    };
  }
  if (error.kind === "timeout") {
    return { title: "The API didn't answer in time", body: "The query ran too long. Retry, or narrow the date range.", icon: icon(Hourglass) };
  }
  if (error.kind === "shape") {
    return {
      title: "The API sent a response this panel can't read",
      body: "Its shape doesn't match what the dashboard expects, so nothing is drawn from it. This usually means the API and the dashboard are from different versions: restart both, then retry.",
      icon: icon(WarningOctagon),
    };
  }
  if (error.kind === "empty") {
    return { title: "No data in the warehouse yet", body: "The marts exist but hold no rows for this view. Reload once the warehouse has been loaded.", icon: icon(Database) };
  }
  const detail = error.detail.toLowerCase();
  if (error.status === 502 && detail.includes("does not exist")) {
    return {
      title: "The warehouse tables aren't built yet",
      body: "The API is running, but the marts this view reads don't exist yet. They appear when the warehouse build finishes; retry then.",
      icon: icon(Database),
    };
  }
  if (error.status === 502 && detail.includes("statement timeout")) {
    return {
      title: "The warehouse query timed out",
      body: "The database stopped this query at the API's time limit. Retry, or narrow the date range to scan less.",
      icon: icon(Hourglass),
    };
  }
  if (error.status === 502 && detail.includes("database is unavailable")) {
    return { title: "The database isn't reachable", body: "The API is up but can't reach Postgres. Check that the database is running, then retry.", icon: icon(Database) };
  }
  if (error.status === 502) {
    return { title: "The warehouse couldn't run this query", body: "The database returned an error. The API's message is below.", icon: icon(Database) };
  }
  if (error.status === 422 || error.status === 404 || error.status === 400) {
    return {
      title: "The API rejected this query",
      body: "The dashboard asked for something the governed layer doesn't allow. That is a dashboard bug; the API's reason is below.",
      icon: icon(WarningOctagon),
    };
  }
  return { title: "The API couldn't answer", body: "Something went wrong on the API side. The API's message is below.", icon: icon(Warning) };
}

function ErrorDetail({ error, className }: { error: ApiError; className?: string }) {
  return (
    <details className={cx("group text-xs text-muted", className)}>
      <summary className="w-fit rounded-control underline decoration-line-strong underline-offset-4 hover:text-ink">Technical detail</summary>
      <p className="mt-2 font-mono break-words [overflow-wrap:anywhere] text-muted">
        {error.endpoint}
        {error.status ? ` returned HTTP ${error.status}` : ""}: {error.detail}
      </p>
    </details>
  );
}

/** The failure layout shared by API errors and render failures: icon, what happened, what to do, then actions. */
export function FailureMessage({
  icon,
  title,
  body,
  actions,
  compact = false,
  calm = false,
  className,
}: {
  icon: ReactNode;
  title: string;
  body: ReactNode;
  actions: ReactNode;
  compact?: boolean;
  /** An expected, self-resolving state (the API waking up): neutral, not the danger colour. */
  calm?: boolean;
  className?: string;
}) {
  return (
    <div role="status" data-panel-error="" className={cx("flex flex-col items-start gap-3 text-left", compact ? "py-2" : "py-8", className)}>
      <div className="flex items-start gap-3">
        <span className={cx("mt-0.5", calm ? "text-muted" : "text-danger")}>{icon}</span>
        <div className="max-w-[60ch]">
          <p className="text-[15px]/6 font-medium text-ink">{title}</p>
          <p className="mt-1 text-sm text-muted">{body}</p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 pl-8">{actions}</div>
    </div>
  );
}

export function ErrorState({ error, compact = false, className }: { error: ApiError; compact?: boolean; className?: string }) {
  const { title, body, icon } = describeError(error);
  return (
    <FailureMessage
      icon={icon}
      title={title}
      body={body}
      compact={compact}
      calm={error.kind === "waking"}
      className={className}
      actions={
        <>
          {error.kind === "waking" ? <AutoRefresh /> : null}
          <RetryButton />
          <ErrorDetail error={error} />
        </>
      }
    />
  );
}

export function EmptyState({ title, body, icon, action, className }: { title: string; body: ReactNode; icon?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div role="status" className={cx("flex items-start gap-3 py-8", className)}>
      {icon ? <span className="mt-0.5 text-subtle">{icon}</span> : null}
      <div className="max-w-[60ch]">
        <p className="text-[15px]/6 font-medium text-ink">{title}</p>
        <div className="mt-1 text-sm text-muted">{body}</div>
        {action ? <div className="mt-3">{action}</div> : null}
      </div>
    </div>
  );
}
