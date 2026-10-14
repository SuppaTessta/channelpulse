"use client";

import { Database, SealCheck, X } from "@phosphor-icons/react";
import * as Dialog from "@radix-ui/react-dialog";
import type { ReactNode } from "react";
import { SqlBlock } from "./sql";
import { Badge, buttonClass, cx, ICON } from "./ui";

export type DefMetric = { name: string; label: string; description: string; formula: string; type: string; time_dimension: string };
/** One API call behind a figure: what was asked (label and value lines), the SQL it ran, how many rows came back. */
export type DefQuery = { caption: string; request: [string, string][]; sql: string; rowCount: number; rowCapHit: boolean };

function RequestSummary({ rows }: { rows: [string, string][] }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 font-mono text-xs">
      {rows.map(([k, v], i) => (
        <div key={i} className="contents">
          <dt className="text-subtle">{k}</dt>
          <dd className="text-ink [overflow-wrap:anywhere]">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * The "Definition · SQL" disclosure (DESIGN.md trust pattern): the governed definition from GET /api/metrics and the
 * exact SQL each figure's query compiled to, from POST /api/metrics/query.
 */
export function DefinitionButton({
  title,
  metrics,
  queries,
  note,
  trigger,
  source = false,
  label,
  className,
}: {
  title: string;
  metrics: DefMetric[];
  queries: DefQuery[];
  note?: ReactNode;
  trigger?: ReactNode;
  /** Name the governed metrics beside the button, so the source reads without opening it (a panel's provenance row). */
  source?: boolean;
  /** An accessible name for a short trigger ("SQL"), so each figure's button says which figure it opens. */
  label?: string;
  className?: string;
}) {
  const dialog = (
    <Dialog.Root>
      <Dialog.Trigger aria-label={label} className={cx(buttonClass("ghost", "sm"), className)}>
        {trigger ?? (
          <>
            <Database size={16} {...ICON} aria-hidden />
            Definition · SQL
          </>
        )}
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="cp-fade fixed inset-0 z-40 bg-[rgb(10_12_14/0.35)] backdrop-blur-[2px]" />
        <Dialog.Content className="cp-slide fixed inset-y-0 right-0 z-50 flex w-full max-w-[640px] flex-col border-l border-line bg-raised shadow-raised outline-none">
          <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
            <div className="min-w-0">
              <Dialog.Title className="text-base font-semibold text-ink">{title}</Dialog.Title>
              <Dialog.Description className="mt-1 text-sm text-muted">
                Where these figures come from: the governed definition and the SQL the API ran.
              </Dialog.Description>
            </div>
            <Dialog.Close className={buttonClass("ghost", "icon")} aria-label="Close">
              <X size={20} {...ICON} aria-hidden />
            </Dialog.Close>
          </header>
          <div className="flex-1 space-y-6 overflow-y-auto px-5 py-5">
            {note ? <div className="text-[15px]/6 text-ink">{note}</div> : null}
            {metrics.map((m) => (
              <section key={m.name} className="space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-[15px] font-semibold text-ink">{m.label}</h3>
                  <Badge tone="governed" icon={<SealCheck size={14} {...ICON} aria-hidden />}>
                    Governed metric
                  </Badge>
                </div>
                <p className="font-mono text-xs text-subtle">{m.name}</p>
                {m.description ? <p className="max-w-[65ch] text-[15px]/6 text-ink">{m.description}</p> : null}
                <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
                  <dt className="text-muted">Formula</dt>
                  <dd className="font-mono text-[13px] text-ink [overflow-wrap:anywhere]">{m.formula}</dd>
                  <dt className="text-muted">Type</dt>
                  <dd className="text-ink">{m.type}</dd>
                  <dt className="text-muted">Time dimension</dt>
                  <dd className="font-mono text-[13px] text-ink">{m.time_dimension}</dd>
                </dl>
              </section>
            ))}
            {queries.map((q, i) => (
              <section key={i} className="space-y-3 border-t border-line pt-5">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h3 className="text-sm font-semibold text-ink">{q.caption}</h3>
                  <p className="text-xs text-muted">
                    {q.rowCount} {q.rowCount === 1 ? "row" : "rows"}
                    {q.rowCapHit ? ", capped at the API's row limit" : ""}
                  </p>
                </div>
                <RequestSummary rows={q.request} />
                <SqlBlock sql={q.sql} />
              </section>
            ))}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
  if (!source || !metrics.length) return dialog;
  return (
    <>
      <p className="mr-auto flex min-w-0 items-center gap-1.5 pl-2 text-xs text-subtle">
        <SealCheck size={14} {...ICON} className="shrink-0 text-accent" aria-hidden />
        <span className="sr-only">Governed metrics:</span>
        <span className="truncate font-mono text-[11.5px]" title={metrics.map((m) => m.name).join(", ")}>
          {metrics.map((m) => m.name).join(", ")}
        </span>
      </p>
      {dialog}
    </>
  );
}
