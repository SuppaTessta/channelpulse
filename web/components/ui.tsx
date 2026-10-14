import type { ReactNode } from "react";

export const cx = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(" ");

/** One stroke weight for every Phosphor icon (DESIGN.md): the precise light line (high-end-visual-design). */
export const ICON = { weight: "light" } as const;

/** The type scale (DESIGN.md): Newsreader for titles and figures, Plus Jakarta Sans for the interface. */
export const TYPE = {
  pageTitle: "font-display text-[30px]/9 font-normal tracking-[-0.02em] text-ink md:text-[40px]/[46px]",
  panelTitle: "font-display text-[19px]/7 font-medium tracking-[-0.01em] text-ink",
  stateTitle: "font-display text-[22px]/7 font-normal tracking-[-0.01em] text-ink",
  question: "font-display text-[22px]/8 font-normal tracking-[-0.01em] text-pretty text-ink",
  subhead: "text-[13px]/5 font-semibold text-ink",
  figureHero: "font-display text-[36px]/10 font-normal tracking-[-0.025em] text-ink md:text-[42px]/[46px]",
  figureLg: "font-display text-[30px]/9 font-normal tracking-[-0.02em] text-ink",
  figureMd: "font-display text-[24px]/8 font-normal tracking-[-0.015em]",
  micro: "text-[10.5px]/4 font-semibold uppercase tracking-[0.12em] text-subtle",
} as const;

const BUTTON_BASE =
  "inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-control font-medium " +
  "transition-[background-color,border-color,color,box-shadow,transform] duration-150 ease-out active:translate-y-px " +
  "disabled:cursor-not-allowed disabled:opacity-45 disabled:active:translate-y-0";

const BUTTON_VARIANT = {
  primary: "bg-accent text-on-accent shadow-highlight hover:bg-accent-hover",
  secondary: "border border-line-strong bg-surface text-ink shadow-highlight hover:border-control hover:bg-hover",
  ghost: "text-muted hover:bg-hover hover:text-ink",
} as const;

const BUTTON_SIZE = {
  md: "h-10 px-3.5 text-sm md:h-9",
  sm: "h-10 px-2.5 text-[13px] md:h-8",
  icon: "size-10 md:size-8",
} as const;

export function buttonClass(variant: keyof typeof BUTTON_VARIANT = "secondary", size: keyof typeof BUTTON_SIZE = "md") {
  return cx(BUTTON_BASE, BUTTON_VARIANT[variant], BUTTON_SIZE[size]);
}

/** Segmented controls (Chart/Table, All/At risk, failure mode): a sunken tray, the chosen segment lifted out of it. */
export const SEGMENTS = "flex w-fit items-center gap-0.5 rounded-control bg-sunken p-0.5 ring-1 ring-line ring-inset";
export const SEGMENT =
  "flex h-8 items-center rounded-[5px] px-2.5 text-[13px] font-medium text-muted transition-[color,background-color,box-shadow] duration-150 ease-out hover:text-ink max-md:h-9";
export const SEGMENT_ON = "bg-raised text-ink shadow-segment";

type Tone = "governed" | "adhoc" | "refused" | "danger" | "neutral";

const TONE: Record<Tone, string> = {
  governed: "bg-accent-soft text-accent",
  adhoc: "bg-adhoc-soft text-adhoc",
  refused: "bg-refused-soft text-ink ring-1 ring-inset ring-line",
  danger: "bg-danger-soft text-danger",
  neutral: "bg-sunken text-muted ring-1 ring-inset ring-line",
};

/** A status pill. Always carries text (and usually an icon), never colour alone. */
export function Badge({ tone, icon, children, className }: { tone: Tone; icon?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <span
      className={cx(
        "inline-flex h-6 shrink-0 items-center gap-1 rounded-full px-2 text-xs font-medium whitespace-nowrap",
        TONE[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  );
}

const FIGURE = /^(₹?)([−+-]?[\d.,]+)\s?(.*)$/;

/**
 * A formatted figure set like an instrument readout: the digits carry the weight, the currency sign and unit step
 * back ("₹226.1 cr" reads as 226.1 first). Anything that isn't a number ("No value") is shown as it is, muted.
 */
export function Figure({ text, className }: { text: string; className?: string }) {
  const m = FIGURE.exec(text);
  if (!m) return <span className={cx(className, "text-muted")}>{text}</span>;
  const [, currency, digits, unit] = m;
  return (
    <span data-figure="" className={cx("tabular-nums", className)}>
      {currency ? <span className="mr-[0.08em] align-[0.12em] text-[0.62em] font-medium text-muted">{currency}</span> : null}
      {digits}
      {unit ? <span className={cx("text-[0.5em] font-medium tracking-normal text-muted", unit === "%" || unit === "×" ? "ml-[0.04em]" : "ml-[0.22em]")}>{unit}</span> : null}
    </span>
  );
}

/** A grid of panels divided by 1px rules (the gap shows the border colour through), not floating cards. */
export function Sheet({ children, className, dim = true }: { children: ReactNode; className?: string; dim?: boolean }) {
  return (
    <div
      data-dim={dim ? "" : undefined}
      className={cx("grid grid-cols-1 gap-px overflow-clip rounded-panel border border-line bg-line", className)}
    >
      {children}
    </div>
  );
}

/** Static placeholder blocks shaped like the content they stand in for. No shimmer: DESIGN.md has no loops. */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cx("rounded-control bg-sunken", className)} />;
}

export function PanelSkeleton({ className, label, chartHeight = "h-56" }: { className?: string; label: string; chartHeight?: string }) {
  return (
    <div className={cx("flex flex-col gap-3 bg-surface p-4 md:p-5", className)} aria-busy="true">
      <span className="sr-only">Loading {label}</span>
      <Skeleton className="h-4 w-40" />
      <Skeleton className="h-3 w-56" />
      <Skeleton className={cx("mt-2 w-full", chartHeight)} />
    </div>
  );
}
