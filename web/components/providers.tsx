"use client";

import * as Tooltip from "@radix-ui/react-tooltip";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useTransition, type ReactNode } from "react";

type Nav = { pending: boolean; setParams: (changes: Record<string, string | null>) => void };
const NavContext = createContext<Nav>({ pending: false, setParams: () => {} });

// Next 15.5 sometimes never applies a streamed navigation: on a cold cache about half of region switches stayed on
// the old render, dimmed, for good (decisions D53). Even a bare router.push does it, so the app can't avoid it.
// ponytail: a watchdog, not a fix; if the URL still hasn't moved after STUCK_MS the browser loads the new one in full,
// as Next itself does when an RSC fetch fails. Drop it once a Next release applies every navigation.
const STUCK_MS = 12_000;
let stuck: ReturnType<typeof setTimeout> | undefined;

/** Filter changes go through one transition, so the page keeps its current render (dimmed) while it refetches. */
function NavigationProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [pending, start] = useTransition();
  const setParams = useCallback(
    (changes: Record<string, string | null>) => {
      // Read at call time: a useSearchParams hook here would force the whole layout to render client-side.
      const next = new URLSearchParams(window.location.search);
      for (const [key, value] of Object.entries(changes)) {
        if (value === null || value === "") next.delete(key);
        else next.set(key, value);
      }
      const qs = next.toString();
      const href = qs ? `${pathname}?${qs}` : pathname;
      const from = window.location.pathname + window.location.search;
      start(() => router.push(href, { scroll: false }));
      clearTimeout(stuck);
      if (href !== from) stuck = setTimeout(() => window.location.pathname + window.location.search === from && window.location.assign(href), STUCK_MS);
    },
    [pathname, router],
  );
  return (
    <NavContext.Provider value={{ pending, setParams }}>
      <div data-pending={pending ? "true" : "false"} className="contents">
        {children}
      </div>
    </NavContext.Provider>
  );
}

export const useNavigation = () => useContext(NavContext);

export function Providers({ children }: { children: ReactNode }) {
  useEffect(() => {
    // One delegated listener feeds every .cp-spotlight panel, and every panel of a ruled sheet, the pointer position (globals.css).
    const onMove = (e: PointerEvent) => {
      const el = (e.target as Element | null)?.closest?.(".cp-spotlight, .cp-sheet > *") as HTMLElement | null;
      if (!el) return;
      const r = el.getBoundingClientRect();
      el.style.setProperty("--mx", `${e.clientX - r.left}px`);
      el.style.setProperty("--my", `${e.clientY - r.top}px`);
    };
    document.addEventListener("pointermove", onMove, { passive: true });
    return () => document.removeEventListener("pointermove", onMove);
  }, []);
  return (
    <Tooltip.Provider delayDuration={250} skipDelayDuration={150}>
      <NavigationProvider>{children}</NavigationProvider>
    </Tooltip.Provider>
  );
}

/** Announces refetches to screen readers and shows a quiet cue beside the filters. */
export function PendingStatus() {
  const { pending } = useNavigation();
  return (
    <span role="status" aria-live="polite" className="text-xs text-subtle">
      {pending ? "Updating" : ""}
    </span>
  );
}
