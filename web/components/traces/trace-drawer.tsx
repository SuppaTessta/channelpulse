"use client";

import { X } from "@phosphor-icons/react";
import * as Dialog from "@radix-ui/react-dialog";
import { useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { buttonClass, ICON } from "../ui";

/**
 * The trace detail as a drawer over the list. It is open whenever the URL names a trace (?trace=), so a trace is
 * deep-linkable; closing it navigates back to the list with its filters. The content is server-rendered.
 */
export function TraceDrawer({ traceId, closeHref, children }: { traceId: string; closeHref: string; children: ReactNode }) {
  const router = useRouter();
  return (
    <Dialog.Root open onOpenChange={(open) => !open && router.push(closeHref, { scroll: false })}>
      <Dialog.Portal>
        <Dialog.Overlay className="cp-fade fixed inset-0 z-40 bg-[rgb(10_12_14/0.35)] backdrop-blur-[2px]" />
        <Dialog.Content className="cp-slide fixed inset-y-0 right-0 z-50 flex w-full max-w-[760px] flex-col border-l border-line bg-raised shadow-raised outline-none">
          <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
            <div className="min-w-0">
              <Dialog.Title className="text-base font-semibold text-ink">Trace</Dialog.Title>
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
