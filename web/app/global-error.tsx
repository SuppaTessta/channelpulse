"use client";

import { GeistSans } from "geist/font/sans";
import "./globals.css";

/**
 * Last line of defence: a failure in the root layout itself (the rail, the providers). It replaces the layout, so it
 * brings its own html and body. A chunk that fails to load means the page is older than the deployment serving it.
 */
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const stale = error.name === "ChunkLoadError" || /loading (css )?chunk/i.test(error.message);
  return (
    <html lang="en-IN" className={GeistSans.variable}>
      <body className="min-h-dvh bg-canvas font-sans text-ink">
        <main className="mx-auto max-w-[1440px] px-4 py-10 md:px-6">
          <section role="alert" data-panel-error="" className="max-w-[68ch] rounded-panel border border-line bg-surface p-5">
            <h1 className="text-[15px]/6 font-semibold text-ink">{stale ? "The dashboard was updated" : "ChannelPulse couldn't start"}</h1>
            <p className="mt-1 text-sm text-muted">
              {stale
                ? "This page belongs to an older version than the server now has, so some of its code can't be loaded. Reload to get the current version."
                : "Something failed while loading the dashboard itself. Try again; if it keeps happening, the reference below identifies it in the server log."}
            </p>
            {error.digest ? <p className="mt-2 font-mono text-xs text-subtle">Reference {error.digest}</p> : null}
            <button
              type="button"
              onClick={() => (stale ? window.location.reload() : reset())}
              className="mt-3 inline-flex h-10 items-center rounded-control border border-line-strong bg-surface px-2.5 text-[13px] font-medium text-ink hover:bg-hover md:h-8"
            >
              {stale ? "Reload" : "Try again"}
            </button>
          </section>
        </main>
      </body>
    </html>
  );
}
