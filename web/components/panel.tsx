import { Suspense, type ReactNode } from "react";
import { PanelBoundary } from "./panel-boundary";

type Props = { title: string; className?: string; fallback: ReactNode; children: ReactNode };

/**
 * One dashboard panel: streamed behind Suspense, with an error boundary inside it, so an exception while rendering
 * the panel (a server component's or a client chart's) replaces this panel with a failure state instead of the page.
 * API failures don't reach the boundary; each panel already shows those as an ErrorState.
 *
 * The Suspense must stay outside the client boundary (decisions D28): with the boundary outside, the still-streaming
 * server content becomes a client component's prop, and on the Executive page hydration then failed with React #419.
 */
export function Panel({ title, className, fallback, children }: Props) {
  return (
    <Suspense fallback={fallback}>
      <PanelBoundary title={title} className={className}>
        {children}
      </PanelBoundary>
    </Suspense>
  );
}
