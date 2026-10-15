"use client";

import { CalendarBlank, CaretDown, Check } from "@phosphor-icons/react";
import * as Popover from "@radix-ui/react-popover";
import { useId, useState } from "react";
import type { Range } from "@/lib/dates";
import { fmtRange } from "@/lib/format";
import { useNavigation } from "./providers";
import { buttonClass, cx, ICON } from "./ui";

export type PresetOption = { key: string; label: string; range: Range; isDefault?: boolean };

/** Date range: presets as rows, custom range behind a hairline (dataviz interaction spec). Writes ?from=&to=. */
export function DateRangeControl({
  range,
  presetKey,
  presets,
  min,
  max,
}: {
  range: Range;
  presetKey: string | null;
  presets: PresetOption[];
  min: string;
  max: string;
}) {
  const { setParams } = useNavigation();
  const [open, setOpen] = useState(false);
  const [from, setFrom] = useState(range.from);
  const [to, setTo] = useState(range.to);
  const errorId = useId();
  const current = presets.find((p) => p.key === presetKey);
  const error =
    !from || !to ? "Enter both dates." : from > to ? "The start date is after the end date." : from < min || to > max ? `Choose dates from ${fmtRange({ from: min, to: max })}.` : null;

  const apply = (next: Range, isDefault = false) => {
    setParams(isDefault ? { from: null, to: null } : { from: next.from, to: next.to });
    setOpen(false);
  };

  return (
    <Popover.Root
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (o) {
          setFrom(range.from);
          setTo(range.to);
        }
      }}
    >
      <Popover.Trigger className={cx(buttonClass("secondary", "md"), "max-w-full justify-start")} aria-label={`Date range: ${current?.label ?? "Custom"}, ${fmtRange(range)}. Change`}>
        <CalendarBlank size={18} {...ICON} className="text-subtle" aria-hidden />
        <span className="font-medium">{current?.label ?? "Custom range"}</span>
        <span className="truncate text-muted">{fmtRange(range)}</span>
        <CaretDown size={14} {...ICON} className="text-subtle" aria-hidden />
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="start"
          sideOffset={6}
          collisionPadding={16}
          className="cp-drop z-50 w-[min(340px,calc(100vw-32px))] rounded-panel border border-line-strong/70 bg-raised/90 shadow-raised backdrop-blur-xl p-1.5 outline-none"
        >
          <div role="group" aria-label="Presets" className="flex flex-col">
            {presets.map((p) => {
              const selected = p.key === presetKey;
              return (
                <button
                  key={p.key}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => apply(p.range, p.isDefault)}
                  className="flex h-11 items-center gap-3 rounded-control px-2.5 text-left text-sm hover:bg-hover md:h-10"
                >
                  <span className="flex w-4 justify-center text-accent">{selected ? <Check size={16} {...ICON} aria-hidden /> : null}</span>
                  <span className={cx("flex-1", selected ? "font-semibold text-ink" : "text-ink")}>{p.label}</span>
                  <span className="text-xs text-muted">{fmtRange(p.range)}</span>
                </button>
              );
            })}
          </div>
          <form
            className="mt-1.5 border-t border-line px-2.5 pt-3 pb-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (!error) apply({ from, to });
            }}
          >
            <p className="mb-2 text-xs font-medium text-muted">Custom range</p>
            <div className="grid grid-cols-2 gap-2">
              <label className="flex flex-col gap-1 text-xs text-muted">
                From
                <input
                  type="date"
                  value={from}
                  min={min}
                  max={max}
                  onChange={(e) => setFrom(e.target.value)}
                  aria-describedby={error ? errorId : undefined}
                  aria-invalid={!!error}
                  className="h-10 rounded-control border border-control bg-surface px-2 text-base text-ink md:h-9 md:text-sm"
                />
              </label>
              <label className="flex flex-col gap-1 text-xs text-muted">
                To
                <input
                  type="date"
                  value={to}
                  min={min}
                  max={max}
                  onChange={(e) => setTo(e.target.value)}
                  aria-describedby={error ? errorId : undefined}
                  aria-invalid={!!error}
                  className="h-10 rounded-control border border-control bg-surface px-2 text-base text-ink md:h-9 md:text-sm"
                />
              </label>
            </div>
            <p id={errorId} className={cx("mt-2 min-h-4 text-xs", error ? "text-danger" : "text-subtle")} aria-live="polite">
              {error ?? `Data covers ${fmtRange({ from: min, to: max })}.`}
            </p>
            <button type="submit" disabled={!!error} className={cx(buttonClass("primary", "md"), "mt-2 w-full")}>
              Apply range
            </button>
          </form>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
