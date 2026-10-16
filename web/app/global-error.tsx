"use client";

import { Newsreader, Plus_Jakarta_Sans } from "next/font/google";
import { Illustration } from "@/components/illustration";
import { THEME_SCRIPT } from "@/components/theme-toggle";
import { TYPE } from "@/components/ui";
import "./globals.css";

const display = Newsreader({ subsets: ["latin", "latin-ext"], axes: ["opsz"], variable: "--font-newsreader", display: "swap" });
const sans = Plus_Jakarta_Sans({ subsets: ["latin", "latin-ext"], variable: "--font-jakarta", display: "swap" });

/**
 * Last line of defence: a failure in the root layout itself (the rail, the providers). It replaces the layout, so it
 * brings its own html and body. A chunk that fails to load means the page is older than the deployment serving it.
 */
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const stale = error.name === "ChunkLoadError" || /loading (css )?chunk/i.test(error.message);
  return (
    <html lang="en-IN" data-theme="dark" className={`${display.variable} ${sans.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="min-h-dvh bg-canvas font-sans text-ink">
        <main className="mx-auto max-w-[1440px] px-4 py-10 md:px-6">
          <section role="alert" data-panel-error="" className="flex max-w-[68ch] flex-col items-start rounded-panel border border-line bg-surface p-6 shadow-highlight cp-reveal">
            <Illustration kind="error" className="mb-3" />
            <h1 className={TYPE.stateTitle}>{stale ? "The dashboard was updated" : "ChannelPulse couldn't start"}</h1>
            <p className="mt-2 text-sm text-muted">
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
