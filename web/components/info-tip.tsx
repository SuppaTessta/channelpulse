"use client";

import { Info } from "@phosphor-icons/react";
import * as Tooltip from "@radix-ui/react-tooltip";
import type { ReactNode } from "react";
import { cx, ICON } from "./ui";

/** A labelled info button whose explanation shows on hover and keyboard focus. */
export function InfoTip({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <Tooltip.Root>
      <Tooltip.Trigger
        type="button"
        aria-label={label}
        className={cx("inline-flex size-6 shrink-0 items-center justify-center rounded-full text-subtle hover:text-ink", className)}
      >
        <Info size={16} {...ICON} aria-hidden />
      </Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content
          side="bottom"
          sideOffset={6}
          collisionPadding={12}
          className="cp-drop z-50 max-w-[320px] rounded-[12px] border border-line-strong/70 bg-raised/90 shadow-raised backdrop-blur-xl px-3 py-2 text-[13px]/5 text-ink"
        >
          {children}
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}
