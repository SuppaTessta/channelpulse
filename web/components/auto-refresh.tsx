"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

const EVERY_MS = 15_000;
// One timer per page, however many panels are waiting on the waking API.
let timer: ReturnType<typeof setInterval> | null = null;
let waiting = 0;

/**
 * Re-runs the page's server queries every 15 s while the API wakes up, until no panel is waiting any more. A
 * repeating timer, not a one-shot re-armed by the next render: Next sometimes leaves a streamed refresh unapplied,
 * and a one-shot that waits for that render would stop retrying for good (decisions D49).
 */
export function AutoRefresh() {
  const router = useRouter();
  useEffect(() => {
    waiting += 1;
    timer ??= setInterval(() => router.refresh(), EVERY_MS);
    return () => {
      waiting -= 1;
      if (waiting === 0 && timer) {
        clearInterval(timer);
        timer = null;
      }
    };
  }, [router]);
  return <span className="text-xs text-muted">Retrying automatically</span>;
}
