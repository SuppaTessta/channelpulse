"use client";

import { ArrowClockwise, WarningOctagon } from "@phosphor-icons/react";
import { buttonClass, ICON } from "@/components/ui";

/** Unexpected render failures. API failures never land here: each section shows those in place. */
export default function PageFailure({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  // A chunk that fails to load means this page is older than the build now being served: only a reload fixes it.
  const stale = error.name === "ChunkLoadError" || /loading (css )?chunk/i.test(error.message);
  return (
    <div className="mx-auto max-w-[1440px] px-4 py-10 md:px-6">
      <section role="alert" data-panel-error="" className="flex max-w-[68ch] items-start gap-3 rounded-panel border border-line bg-surface p-5">
        <WarningOctagon size={22} {...ICON} className="mt-0.5 shrink-0 text-danger" aria-hidden />
        <div>
          <h1 className="text-[15px]/6 font-semibold text-ink">{stale ? "The dashboard was updated" : "This page failed to render"}</h1>
          <p className="mt-1 text-sm text-muted">
            {stale
              ? "This page belongs to an older version than the server now has, so some of its code can't be loaded. Reload to get the current version."
              : "The dashboard hit an unexpected error while drawing this page. Try again; if it keeps happening, the reference below identifies it in the server log."}
          </p>
          {error.digest ? <p className="mt-2 font-mono text-xs text-subtle">Reference {error.digest}</p> : null}
          <button type="button" onClick={() => (stale ? window.location.reload() : reset())} className={`${buttonClass("secondary", "sm")} mt-3`}>
            <ArrowClockwise size={16} {...ICON} aria-hidden />
            {stale ? "Reload" : "Try again"}
          </button>
        </div>
      </section>
    </div>
  );
}
