"use client";

import * as Tabs from "@radix-ui/react-tabs";
import type { ReactNode } from "react";
import { cx } from "./ui";

const TRIGGER =
  "h-8 rounded-[5px] px-2.5 text-[13px] font-medium text-muted transition-colors duration-150 ease-out hover:text-ink " +
  "data-[state=active]:bg-surface data-[state=active]:text-ink data-[state=active]:shadow-[0_0_0_1px_var(--border-strong)] max-md:h-9";

/** A chart panel with its accessible twin: every chart has a Chart and a Table view (DESIGN.md accessibility). */
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
  actions?: ReactNode;
  chart: ReactNode;
  table?: ReactNode;
  footer?: ReactNode;
  className?: string;
}) {
  return (
    <section aria-labelledby={id} className={cx("min-w-0 bg-surface", className)}>
      <Tabs.Root defaultValue="chart" className="flex h-full flex-col gap-3 p-4 md:p-5">
        <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
          <div className="min-w-0">
            <h2 id={id} className="text-sm font-semibold text-ink">
              {title}
            </h2>
            {subtitle ? <p className="mt-0.5 text-xs text-muted">{subtitle}</p> : null}
          </div>
          <div className="-my-1 flex flex-wrap items-center gap-1">
            {table ? (
              <Tabs.List aria-label={`${title}: view`} className="flex items-center gap-0.5 rounded-control bg-hover p-0.5">
                <Tabs.Trigger value="chart" className={TRIGGER}>
                  Chart
                </Tabs.Trigger>
                <Tabs.Trigger value="table" className={TRIGGER}>
                  Table
                </Tabs.Trigger>
              </Tabs.List>
            ) : null}
            {actions}
          </div>
        </header>
        <Tabs.Content value="chart" className="min-w-0 outline-none">
          {chart}
        </Tabs.Content>
        {table ? (
          <Tabs.Content value="table" className="min-w-0 outline-none">
            {table}
          </Tabs.Content>
        ) : null}
        {footer}
      </Tabs.Root>
    </section>
  );
}
