"use client";

import * as Tabs from "@radix-ui/react-tabs";
import type { ReactNode } from "react";
import { cx, SEGMENT, SEGMENTS, TYPE } from "./ui";

const TRIGGER = cx(SEGMENT, "data-[state=active]:bg-raised data-[state=active]:text-ink data-[state=active]:shadow-segment");

/**
 * A chart panel with its accessible twin: every chart has a Chart and a Table view (DESIGN.md accessibility).
 * Provenance sits on the panel's baseline: notes on the left, the governed source and its SQL on the right.
 */
export function ChartPanel({
  id,
  title,
  subtitle,
  actions,
  chart,
  table,
  footer,
  className,
}: {
  id: string;
  title: string;
  subtitle?: ReactNode;
  /** The panel's DefinitionButton, shown in the provenance row. */
  actions?: ReactNode;
  chart: ReactNode;
  table?: ReactNode;
  footer?: ReactNode;
  className?: string;
}) {
  return (
    <section aria-labelledby={id} className={cx("cp-reveal min-w-0 bg-surface", className)}>
      <Tabs.Root defaultValue="chart" className="flex h-full flex-col gap-4 p-4 md:p-5">
        <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
          <div className="min-w-0">
            <h2 id={id} className={TYPE.panelTitle}>
              {title}
            </h2>
            {subtitle ? <p className="mt-1 max-w-[72ch] text-[12.5px] text-muted">{subtitle}</p> : null}
          </div>
          {table ? (
            <Tabs.List aria-label={`${title}: view`} className={cx(SEGMENTS, "-my-0.5")}>
              <Tabs.Trigger value="chart" className={TRIGGER}>
                Chart
              </Tabs.Trigger>
              <Tabs.Trigger value="table" className={TRIGGER}>
                Table
              </Tabs.Trigger>
            </Tabs.List>
          ) : null}
        </header>
        {/* Not a tab stop: the chart itself (or the error state inside) is focusable where needed. */}
        <Tabs.Content value="chart" tabIndex={-1} className="min-w-0 outline-none">
          {chart}
        </Tabs.Content>
        {table ? (
          <Tabs.Content value="table" className="min-w-0 rounded-control outline-offset-2">
            {table}
          </Tabs.Content>
        ) : null}
        {footer || actions ? (
          <footer className="mt-auto flex flex-col gap-2">
            {footer}
            {actions ? <div className="-mx-4 -mb-4 flex flex-wrap items-center justify-end gap-x-3 border-t border-line bg-[color-mix(in_oklab,var(--surface),var(--surface-sunken)_50%)] px-2 py-1.5 md:-mx-5 md:-mb-5 md:px-3">{actions}</div> : null}
          </footer>
        ) : null}
      </Tabs.Root>
    </section>
  );
}
