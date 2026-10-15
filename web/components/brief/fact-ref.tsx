"use client";

import * as Popover from "@radix-ui/react-popover";
import type { ReactNode } from "react";

/**
 * A footnote marker after a sentence: the number of a cited fact, opening that fact's metric, value and SQL. The
 * content is rendered on the server and passed in; in print the endnotes carry the same facts.
 */
export function FactRef({ n, label, children }: { n: number; label: string; children: ReactNode }) {
  return (
    <Popover.Root>
      <sup className="ml-0.5 align-[0.45em] leading-none">
        <Popover.Trigger
          aria-label={`Source ${n}: ${label}`}
          className="relative inline-flex h-5 min-w-5 items-center justify-center rounded-[4px] px-0.5 font-sans text-[11px] after:absolute after:-inset-x-0.5 after:-inset-y-2.5 after:content-[''] font-semibold text-accent tabular-nums transition-colors duration-150 hover:bg-accent-soft data-[state=open]:bg-accent-soft print:text-ink"
        >
          {n}
        </Popover.Trigger>
      </sup>
      <Popover.Portal>
        <Popover.Content
          side="bottom"
          align="start"
          sideOffset={6}
          collisionPadding={16}
          className="cp-drop z-50 flex max-h-[min(520px,var(--radix-popover-content-available-height))] w-[min(560px,calc(100vw-32px))] flex-col gap-3 overflow-y-auto rounded-[12px] border border-line-strong/70 bg-raised/90 p-4 shadow-raised backdrop-blur-xl outline-none"
        >
          {children}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
