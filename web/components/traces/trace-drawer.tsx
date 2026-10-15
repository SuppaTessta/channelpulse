"use client";

import { X } from "@phosphor-icons/react";
import * as Dialog from "@radix-ui/react-dialog";
import { useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { buttonClass, ICON, TYPE } from "../ui";

/**
 * The trace detail as a drawer over the list. It is open whenever the URL names a trace (?trace=), so a trace is
 * deep-linkable; closing it navigates back to the list with its filters. The content is server-rendered.
 */
export function TraceDrawer({ traceId, closeHref, children }: { traceId: string; closeHref: string; children: ReactNode }) {
  const router = useRouter();
  return (
    <Dialog.Root open onOpenChange={(open) => !open && router.push(closeHref, { scroll: false })}>
      <Dialog.Portal>
        <Dialog.Overlay className="cp-fade fixed inset-0 z-40 bg-[rgb(3_6_12/0.55)] backdrop-blur-[3px]" />
        <Dialog.Content className="cp-slide fixed inset-y-0 right-0 z-50 flex w-full max-w-[760px] flex-col rounded-l-[16px] border-l border-line-strong/70 bg-raised/95 shadow-raised outline-none backdrop-blur-xl">
          <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
            <div className="min-w-0">
              <Dialog.Title className={TYPE.stateTitle}>Trace</Dialog.Title>
              <Dialog.Description className="mt-0.5 font-mono text-xs break-all text-subtle">{traceId}</Dialog.Description>
            </div>
            <Dialog.Close className={buttonClass("ghost", "icon")} aria-label="Close trace">
              <X size={20} {...ICON} aria-hidden />
            </Dialog.Close>
          </header>
          <div className="flex-1 overflow-y-auto overscroll-contain">{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
