"use client";

import { useId } from "react";
import { useNavigation } from "./providers";
import { cx } from "./ui";

/** A segmented control over native radio inputs (arrow keys work), bound to one URL parameter. */
export function SegmentedParam({
  param,
  label,
  value,
  options,
  resets = [],
}: {
  param: string;
  label: string;
  value: string | null;
  options: { value: string | null; label: string }[];
  resets?: string[];
}) {
  const { setParams } = useNavigation();
  const name = useId();
  return (
    <fieldset className="flex items-center gap-2">
      <legend className="float-left mr-2 text-xs text-muted">{label}</legend>
      <div className="flex items-center gap-0.5 rounded-control bg-hover p-0.5">
        {options.map((o) => {
          const checked = o.value === value;
          return (
            <label
              key={o.label}
              className={cx(
                "flex h-9 cursor-pointer items-center rounded-[5px] px-3 text-[13px] font-medium transition-colors duration-150 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-[var(--focus)] md:h-8",
                checked ? "bg-surface text-ink shadow-[0_0_0_1px_var(--border-strong)]" : "text-muted hover:text-ink",
              )}
            >
              <input
                type="radio"
                name={name}
                className="sr-only"
                checked={checked}
                onChange={() => setParams({ [param]: o.value, ...Object.fromEntries(resets.map((r) => [r, null])) })}
              />
              {o.label}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
