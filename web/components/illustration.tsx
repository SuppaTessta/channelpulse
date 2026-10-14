import { cx } from "./ui";

type Kind = "empty" | "error" | "waking" | "lost";

/** Small line drawings for states (DESIGN.md graphics): accent strokes on a soft disc, never carrying meaning alone. */
export function Illustration({ kind, className }: { kind: Kind; className?: string }) {
  return (
    <svg viewBox="0 0 96 64" aria-hidden className={cx("h-16 w-24 shrink-0", className)}>
      <ellipse cx="48" cy="34" rx="40" ry="26" fill="var(--accent-soft)" />
      <path
        d="M10 46c10 0 12-6 20-6s10 6 18 6 10-6 18-6 12 6 20 6"
        fill="none"
        stroke="color-mix(in oklab, var(--accent) 45%, transparent)"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
      {kind === "empty" ? (
        <path d="M22 32h12l4-8 6 16 4-10 3 2h23" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" strokeDasharray="3 4" />
      ) : null}
      {kind === "error" ? (
        <path d="M22 32h12l4-8 5 10m6 4 3-9 3 3h19" fill="none" stroke="var(--danger)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      ) : null}
      {kind === "waking" ? (
        <g fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round">
          <path d="M26 33h40" />
          <path d="M60 18h6l-6 6h6M70 10h4l-4 4h4" strokeWidth="1.5" />
        </g>
      ) : null}
      {kind === "lost" ? (
        <g fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M22 34h10l4-8 5 14 4-10 3 4" />
          <path d="M60 22a6 6 0 1 1 6 6v4M66 38v1" />
        </g>
      ) : null}
    </svg>
  );
}
