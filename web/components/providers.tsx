"use client";

import * as Tooltip from "@radix-ui/react-tooltip";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useTransition, type ReactNode } from "react";

type Nav = { pending: boolean; setParams: (changes: Record<string, string | null>) => void };
const NavContext = createContext<Nav>({ pending: false, setParams: () => {} });

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
      start(() => router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false }));
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
