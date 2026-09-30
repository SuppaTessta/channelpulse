"use client";

import { Printer } from "@phosphor-icons/react";
import { buttonClass, ICON } from "./ui";

export function PrintButton({ label = "Print" }: { label?: string }) {
  return (
    <button type="button" onClick={() => window.print()} className={buttonClass("secondary", "md")}>
      <Printer size={16} {...ICON} aria-hidden />
      {label}
    </button>
  );
}
