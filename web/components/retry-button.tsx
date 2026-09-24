"use client";

import { ArrowClockwise } from "@phosphor-icons/react";
import { useRouter } from "next/navigation";
import { useTransition } from "react";
import { buttonClass, ICON } from "./ui";

/** Re-runs the page's server queries without a full reload. */
export function RetryButton() {
  const router = useRouter();
  const [pending, start] = useTransition();
  return (
    <button type="button" className={buttonClass("secondary", "sm")} disabled={pending} onClick={() => start(() => router.refresh())}>
      <ArrowClockwise size={16} {...ICON} className={pending ? "opacity-50" : undefined} aria-hidden />
      {pending ? "Retrying" : "Retry"}
    </button>
  );
}
