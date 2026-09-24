import type { ReactNode } from "react";

export const cx = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(" ");

/** One stroke weight for every Phosphor icon (DESIGN.md): the precise light line (high-end-visual-design). */
export const ICON = { weight: "light" } as const;

const BUTTON_BASE =
  "inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-control font-medium " +
  "transition-[background-color,border-color,color,transform] duration-150 ease-out active:translate-y-px " +
  "disabled:cursor-not-allowed disabled:opacity-45 disabled:active:translate-y-0";

const BUTTON_VARIANT = {
  primary: "bg-accent text-on-accent hover:bg-accent-hover",
  secondary: "border border-line-strong bg-surface text-ink hover:border-control hover:bg-hover",
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

export type Tone = "governed" | "adhoc" | "refused" | "danger" | "neutral";

const TONE: Record<Tone, string> = {
  governed: "bg-accent-soft text-accent",
  adhoc: "bg-adhoc-soft text-adhoc",
  refused: "bg-refused-soft text-ink ring-1 ring-inset ring-line",
  danger: "bg-danger-soft text-danger",
  neutral: "bg-hover text-muted",
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

export function Panel({
  id,
  title,
  subtitle,
  actions,
  children,
  className,
}: {
  id: string;
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section aria-labelledby={id} className={cx("flex min-w-0 flex-col gap-3 bg-surface p-4 md:p-5", className)}>
      <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <h2 id={id} className="text-sm font-semibold text-ink">
            {title}
          </h2>
          {subtitle ? <p className="mt-0.5 text-xs text-muted">{subtitle}</p> : null}
        </div>
        {actions ? <div className="-my-1 flex flex-wrap items-center gap-1">{actions}</div> : null}
      </header>
      {children}
    </section>
  );
}

/** Static placeholder blocks shaped like the content they stand in for. No shimmer: DESIGN.md has no loops. */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cx("rounded-control bg-hover", className)} />;
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

export function VisuallyHidden({ children }: { children: ReactNode }) {
  return <span className="sr-only">{children}</span>;
}
