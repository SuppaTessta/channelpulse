"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

const AFTER_MS = 15_000;
// One timer per page, however many panels are waiting on the waking API.
let pending: ReturnType<typeof setTimeout> | null = null;

/** Re-runs the page's server queries once, shortly, while the API wakes up; the next render schedules another. */
export function AutoRefresh() {
  const router = useRouter();
  // No dependency list: a refresh that finds the API still waking re-renders this, which arms the next retry.
  useEffect(() => {
    if (pending) return;
    pending = setTimeout(() => {
      pending = null;
      router.refresh();
    }, AFTER_MS);
  });
  return <span className="text-xs text-muted">Retrying automatically</span>;
}
