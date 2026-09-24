import type { PresetOption } from "@/components/date-range";
import { isISODate, maxDate, minDate, precedingWindow, presets, type Range } from "./dates";

export type SearchParams = Record<string, string | string[] | undefined>;

export const param = (sp: SearchParams, key: string): string | undefined => {
  const v = sp[key];
  return Array.isArray(v) ? v[0] : v;
};

export type Period = {
  /** The range every query on the page uses, clamped to the data's coverage. */
  range: Range;
  /** The comparison window for KPI deltas, and whether the data covers all of it. */
  prior: Range;
  priorLabel: string;
  priorCovered: boolean;
  presetKey: string | null;
  label: string;
  options: PresetOption[];
};

/** ?from=&to= (ISO dates) against the data window; no parameters means the current fiscal year to date. */
export function resolvePeriod(sp: SearchParams, win: { asOf: string; dataStart: string }): Period {
  const clamp = (r: Range): Range => ({ from: maxDate(r.from, win.dataStart), to: minDate(r.to, win.asOf) });
  const all = presets(win.asOf).filter((p) => p.range.to >= win.dataStart);
  const options: PresetOption[] = all.map((p, i) => ({ key: p.key, label: p.label, range: clamp(p.range), isDefault: i === 0 }));

  let range = options[0].range;
  const from = param(sp, "from");
  const to = param(sp, "to");
  if (isISODate(from) && isISODate(to) && from <= to) {
    const wanted = clamp({ from, to });
    if (wanted.from <= wanted.to) range = wanted;
  }
  const i = options.findIndex((o) => o.range.from === range.from && o.range.to === range.to);
  const preset = i >= 0 ? all[i] : null;
  const prior = preset ? preset.prior : precedingWindow(range);
  return {
    range,
    prior,
    priorLabel: preset ? preset.priorLabel : "the same number of days before",
    priorCovered: prior.from >= win.dataStart,
    presetKey: preset?.key ?? null,
    label: preset?.label ?? "Custom range",
    options,
  };
}

/** The filters that follow the viewer between pages, as a query string. */
export function sharedQuery(sp: SearchParams): string {
  const out = new URLSearchParams();
  for (const key of ["region", "from", "to"]) {
    const v = param(sp, key);
    if (v) out.set(key, v);
  }
  const qs = out.toString();
  return qs ? `?${qs}` : "";
}
