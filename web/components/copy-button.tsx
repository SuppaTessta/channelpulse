"use client";

import { Check, Copy } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { buttonClass, ICON } from "./ui";

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  useEffect(() => {
    if (state === "idle") return;
    const t = setTimeout(() => setState("idle"), 1800);
    return () => clearTimeout(t);
  }, [state]);
  return (
    <button
      type="button"
      className={buttonClass("ghost", "sm")}
      onClick={() => navigator.clipboard.writeText(text).then(() => setState("copied"), () => setState("failed"))}
    >
      {state === "copied" ? <Check size={16} {...ICON} className="text-accent" aria-hidden /> : <Copy size={16} {...ICON} aria-hidden />}
      <span aria-live="polite">{state === "copied" ? "Copied" : state === "failed" ? "Copy blocked, select the text" : label}</span>
    </button>
  );
}
