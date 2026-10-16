"use client";

import { CaretDown, Check } from "@phosphor-icons/react";
import * as Select from "@radix-ui/react-select";
import { useId, type ReactNode } from "react";
import { useNavigation } from "./providers";
import { cx, ICON } from "./ui";

export type Option = { value: string; label: string };
const ALL = "__all__";

/** A select bound to one URL parameter. The "all" option removes the parameter. */
export function ParamSelect({
  param,
  label,
  value,
  options,
  allLabel,
  hint,
  resets = [],
}: {
  param: string;
  label: string;
  value: string | null;
  options: Option[];
  allLabel: string;
  hint?: ReactNode;
  /** Other parameters that stop making sense when this one changes (a drill-down, for example). */
  resets?: string[];
}) {
  const { setParams } = useNavigation();
  const labelId = useId();
  return (
    <div className="flex min-w-0 items-center gap-2">
      <span id={labelId} className="shrink-0 text-xs text-muted">
        {label}
      </span>
      {hint}
      <Select.Root
        value={value ?? ALL}
        onValueChange={(v) => setParams({ [param]: v === ALL ? null : v, ...Object.fromEntries(resets.map((r) => [r, null])) })}
      >
        <Select.Trigger
          aria-labelledby={labelId}
          className={cx(
            "inline-flex h-10 min-w-0 items-center gap-2 rounded-control border border-line-strong bg-surface pr-2 pl-3 text-sm font-medium text-ink shadow-highlight data-[state=open]:shadow-[var(--glow-accent)] md:h-9",
            "transition-colors duration-150 ease-out hover:border-control hover:bg-hover data-[state=open]:border-control",
          )}
        >
          <span className="truncate">
            {/* Explicit children: Radix only knows item text after its portal mounts, which SSR never does. */}
            <Select.Value>{options.find((o) => o.value === value)?.label ?? allLabel}</Select.Value>
          </span>
          <Select.Icon className="text-subtle">
            <CaretDown size={14} {...ICON} aria-hidden />
          </Select.Icon>
        </Select.Trigger>
        <Select.Portal>
          <Select.Content
            position="popper"
            sideOffset={4}
            className="cp-drop z-50 max-h-[min(360px,var(--radix-select-content-available-height))] min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-panel border border-line-strong/70 bg-raised/90 shadow-raised backdrop-blur-xl"
          >
            <Select.Viewport className="p-1">
              {[{ value: ALL, label: allLabel }, ...options].map((o) => (
                <Select.Item
                  key={o.value}
                  value={o.value}
                  className="relative flex h-10 cursor-pointer items-center rounded-[4px] pr-8 pl-2.5 text-sm text-ink outline-none select-none data-[highlighted]:bg-accent-soft/70 md:h-8"
                >
                  <Select.ItemText>{o.label}</Select.ItemText>
                  <Select.ItemIndicator className="absolute right-2 text-accent">
                    <Check size={16} {...ICON} aria-hidden />
                  </Select.ItemIndicator>
                </Select.Item>
              ))}
            </Select.Viewport>
          </Select.Content>
        </Select.Portal>
      </Select.Root>
    </div>
  );
}
