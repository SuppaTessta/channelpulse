"use client";

import { ArrowClockwise, WarningOctagon } from "@phosphor-icons/react";
import { buttonClass, ICON } from "@/components/ui";

/** Unexpected render failures. API failures never land here: each section shows those in place. */
export default function PageFailure({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="mx-auto max-w-[1440px] px-4 py-10 md:px-6">
      <section role="alert" className="flex max-w-[68ch] items-start gap-3 rounded-panel border border-line bg-surface p-5">
        <WarningOctagon size={22} {...ICON} className="mt-0.5 shrink-0 text-danger" aria-hidden />
        <div>
          <h1 className="text-[15px]/6 font-semibold text-ink">This page failed to render</h1>
          <p className="mt-1 text-sm text-muted">
            The dashboard hit an unexpected error while drawing this page. Try again; if it keeps happening, the reference below identifies it in the server log.
          </p>
          {error.digest ? <p className="mt-2 font-mono text-xs text-subtle">Reference {error.digest}</p> : null}
          <button type="button" onClick={reset} className={`${buttonClass("secondary", "sm")} mt-3`}>
            <ArrowClockwise size={16} {...ICON} aria-hidden />
            Try again
          </button>
        </div>
      </section>
    </div>
  );
}
