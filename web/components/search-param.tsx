"use client";

import { MagnifyingGlass } from "@phosphor-icons/react";
import { useId, useState } from "react";
import { useNavigation } from "./providers";
import { ICON } from "./ui";

/** A text search bound to one URL parameter; Enter applies it, and clearing the field removes it. */
export function SearchParam({ param, label, value, placeholder, resets = [] }: { param: string; label: string; value: string | null; placeholder: string; resets?: string[] }) {
  const { setParams } = useNavigation();
  const [text, setText] = useState(value ?? "");
  const hint = useId();
  const apply = (next: string) => setParams({ [param]: next.trim() || null, ...Object.fromEntries(resets.map((r) => [r, null])) });
  return (
    <form
      role="search"
      className="flex min-w-0 items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        apply(text);
      }}
    >
      <label className="flex min-w-0 items-center gap-2 text-xs text-muted">
        {label}
        <span className="relative min-w-0">
          <MagnifyingGlass size={16} {...ICON} className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-subtle" aria-hidden />
          <input
            type="search"
            value={text}
            aria-describedby={hint}
            onChange={(e) => {
              setText(e.target.value);
              if (!e.target.value && value) apply("");
            }}
            placeholder={placeholder}
            className="h-10 w-full rounded-control border border-control bg-surface pr-3 pl-8 text-base text-ink placeholder:text-subtle sm:w-64 md:h-9 md:text-sm"
          />
        </span>
      </label>
      <span id={hint} className="sr-only">
        Press Enter to search.
      </span>
    </form>
  );
}
