"use client";

import { CaretDown, CaretUp, MagnifyingGlass, WarningDiamond } from "@phosphor-icons/react";
import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";
import { fmtDate, fmtNumber, formatValue } from "@/lib/format";
import { Badge, buttonClass, cx, Figure, ICON, SEGMENT, SEGMENT_ON, SEGMENTS, TYPE } from "./ui";

export type DistributorRow = { id: string; name: string; region: string; tier: string; sales: number | null };
export type RiskFlag = {
  id: string;
  region: string | null;
  firstFlag: string | null;
  snapshot: string | null;
  /** The scored week the flag belongs to. */
  week: string | null;
  score: number | null;
  trendScore: number | null;
  /** Flagged in the latest weekly snapshot, not only in an earlier one. */
  current: boolean;
};

type SortKey = "name" | "region" | "tier" | "sales";
type View = "all" | "at-risk";

/** Rows drawn at first; the rest follow on request, so a 300-row list doesn't make a 13,000px page. */
const PAGE = 50;

const tierLabel = (tier: string) => (/^\d+$/.test(tier) ? `Tier ${tier}` : tier);

/** Keeps view and search in the URL for deep links, without a server round trip (native history, synced by Next). */
function syncUrl(view: View, q: string) {
  const url = new URL(window.location.href);
  if (view === "at-risk") url.searchParams.set("view", "at-risk");
  else url.searchParams.delete("view");
  if (q) url.searchParams.set("q", q);
  else url.searchParams.delete("q");
  window.history.replaceState(null, "", url);
}

/** The list's headline figures, all read from the same governed query as the rows below them. */
function Summary({ rows, atRisk, salesLabel }: { rows: DistributorRow[]; atRisk: number | null; salesLabel: string }) {
  const sales = rows.map((r) => r.sales ?? 0).sort((a, b) => b - a);
  const total = sales.reduce((a, b) => a + b, 0);
  const top10 = sales.slice(0, 10).reduce((a, b) => a + b, 0);
  const figures: [string, string, string?][] = [
    ["Distributors with sales", fmtNumber(rows.length)],
    ["At risk now", atRisk == null ? "No value" : fmtNumber(atRisk), "Flagged in the latest detector snapshot"],
    [salesLabel, formatValue("inr", total)],
    ["Top 10 share", total > 0 ? formatValue("pct", top10 / total) : "No value", "Of primary sales in the range"],
  ];
  return (
    <dl className="cp-sheet grid grid-cols-2 gap-px overflow-clip rounded-[14px] border border-line bg-line lg:grid-cols-4">
      {figures.map(([label, value, hint]) => (
        <div key={label} className="flex min-w-0 flex-col gap-1 bg-surface px-3.5 py-3">
          <dt className="truncate text-xs text-muted" title={label}>
            {label}
          </dt>
          <dd>
            <Figure text={value} className={TYPE.figureLg} animate />
            {hint ? <span className="block text-[11.5px]/4 text-subtle">{hint}</span> : null}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function DistributorTable({
  rows,
  flags,
  flagsError,
  initialView,
  initialQuery,
  linkQuery,
  salesLabel,
  riskRule,
  actions,
}: {
  rows: DistributorRow[];
  flags: RiskFlag[] | null;
  flagsError: string | null;
  initialView: View;
  initialQuery: string;
  linkQuery: string;
  salesLabel: string;
  riskRule: string;
  actions?: ReactNode;
}) {
  const [view, setView] = useState<View>(initialView);
  const [q, setQ] = useState(initialQuery);
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "sales", dir: -1 });
  const [includeEarlier, setIncludeEarlier] = useState(false);
  const [limit, setLimit] = useState(PAGE);
  const currentFlags = useMemo(() => (flags ?? []).filter((f) => f.current), [flags]);
  const earlierCount = (flags?.length ?? 0) - currentFlags.length;
  const byId = useMemo(() => new Map(rows.map((r) => [r.id, r])), [rows]);
  const flagged = useMemo(() => new Map((flags ?? []).map((f) => [f.id, f])), [flags]);
  const shownFlags = useMemo(() => (includeEarlier ? (flags ?? []) : currentFlags), [includeEarlier, flags, currentFlags]);
  const max = Math.max(1, ...rows.map((r) => r.sales ?? 0));

  const needle = q.trim().toLowerCase();
  const visible = useMemo(() => {
    const base = view === "at-risk" ? shownFlags.map((f) => byId.get(f.id) ?? { id: f.id, name: f.id, region: f.region ?? "", tier: "", sales: null }) : rows;
    const matched = needle ? base.filter((r) => [r.id, r.name, r.region, tierLabel(r.tier)].some((v) => v.toLowerCase().includes(needle))) : base;
    const val = (r: DistributorRow) => (sort.key === "sales" ? (r.sales ?? -Infinity) : r[sort.key]);
    return [...matched].sort((a, b) => {
      const x = val(a), y = val(b);
      return (x < y ? -1 : x > y ? 1 : 0) * sort.dir || a.name.localeCompare(b.name);
    });
  }, [view, shownFlags, byId, rows, needle, sort]);
  const shown = visible.slice(0, limit);

  const setViewAndUrl = (v: View) => {
    setView(v);
    setLimit(PAGE);
    syncUrl(v, q);
  };
  const header = (key: SortKey, label: string, numeric = false, className?: string) => {
    const active = sort.key === key;
    return (
      <th scope="col" aria-sort={active ? (sort.dir === 1 ? "ascending" : "descending") : "none"} className={cx("px-3 py-1.5 font-medium", numeric ? "text-right" : "text-left", view === "all" && className)}>
        <button
          type="button"
          onClick={() => {
            setSort((s) => ({ key, dir: s.key === key ? (s.dir === 1 ? -1 : 1) : key === "sales" ? -1 : 1 }));
            setLimit(PAGE);
          }}
          className={cx("-mx-1 inline-flex h-8 items-center gap-1 rounded-control px-1 text-[11px] font-semibold tracking-[0.08em] uppercase hover:text-ink", active ? "text-ink" : "text-subtle", numeric && "flex-row-reverse")}
        >
          {label}
          {active ? sort.dir === 1 ? <CaretUp size={12} {...ICON} aria-hidden /> : <CaretDown size={12} {...ICON} aria-hidden /> : null}
        </button>
      </th>
    );
  };
  const plainHeader = (label: string, numeric = false) => (
    <th scope="col" className={cx("px-3 py-1.5 text-[11px] font-semibold tracking-[0.08em] whitespace-nowrap text-subtle uppercase", numeric ? "text-right" : "text-left")}>
      {label}
    </th>
  );

  return (
    <section aria-labelledby="distributors-heading" className="flex flex-col gap-4 rounded-panel border border-line bg-surface p-4 md:p-5" data-dim="">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h2 id="distributors-heading" className={TYPE.panelTitle}>
            Distributors
          </h2>
          <div role="group" aria-label="Distributor view" className={SEGMENTS}>
            {(["all", "at-risk"] as const).map((v) => (
              <button key={v} type="button" aria-pressed={view === v} onClick={() => setViewAndUrl(v)} className={cx(SEGMENT, "gap-1.5", view === v && SEGMENT_ON)}>
                {v === "all" ? "All" : "At risk"}
                <span className={cx("tabular-nums", view === v ? "text-muted" : "text-subtle")}>
                  {v === "all" ? fmtNumber(rows.length) : flags ? fmtNumber(currentFlags.length) : ""}
                </span>
              </button>
            ))}
          </div>
        </div>
        <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
          {actions}
          <label className="flex w-full items-center gap-2 text-xs text-muted sm:w-auto">
            <span className="sr-only sm:not-sr-only">Search</span>
            <span className="relative flex-1 sm:flex-none">
              <MagnifyingGlass size={16} {...ICON} className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-subtle" aria-hidden />
              <input
                type="search"
                value={q}
                aria-label="Search distributors"
                onChange={(e) => {
                  setQ(e.target.value);
                  setLimit(PAGE);
                  syncUrl(view, e.target.value);
                }}
                placeholder="Name, ID, region or tier"
                className="h-10 w-full rounded-control border border-control bg-surface pr-3 pl-8 text-base text-ink placeholder:text-subtle sm:w-64 md:h-9 md:text-sm"
              />
            </span>
          </label>
        </div>
      </div>

      <Summary rows={rows} atRisk={flags ? currentFlags.length : null} salesLabel={salesLabel} />

      {view === "at-risk" ? (
        <div className="flex flex-col gap-2">
          <p className="max-w-[80ch] text-xs text-muted">
            <WarningDiamond size={14} {...ICON} className="mr-1 inline align-[-2px] text-danger" aria-hidden />
            {riskRule}
          </p>
          {earlierCount > 0 ? (
            <label className="flex w-fit items-center gap-2 text-xs text-ink">
              <input type="checkbox" checked={includeEarlier} onChange={(e) => setIncludeEarlier(e.target.checked)} className="size-4" />
              Also show {fmtNumber(earlierCount)} distributors flagged only in earlier snapshots
            </label>
          ) : null}
        </div>
      ) : null}

      {view === "at-risk" && flagsError ? (
        <p className="text-sm text-danger">{flagsError}</p>
      ) : visible.length === 0 ? (
        <p role="status" className="py-8 text-sm text-muted">
          {needle ? `No distributor matches "${q.trim()}". Clear the search or try an ID such as D0042.` : view === "at-risk" ? "No distributor is flagged at risk in the latest snapshot under this region claim." : "No distributor has primary sales in this range."}
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          <div className="-mx-4 overflow-x-auto md:mx-0 md:rounded-control md:border md:border-line">
            <table className={cx("w-full border-collapse text-[13px]", view === "at-risk" ? "min-w-[860px]" : "sm:min-w-[560px]")}>
              <caption className="sr-only">
                {view === "at-risk" ? "Distributors flagged at risk" : "Distributors by primary sales"}, {visible.length} rows
              </caption>
              <thead className="border-b border-line bg-sunken">
                <tr>
                  {header("name", "Distributor")}
                  {header("region", "Region", false, "max-sm:hidden")}
                  {header("tier", "Tier", false, "max-sm:hidden")}
                  {view === "at-risk" ? (
                    <>
                      {plainHeader("Flagged week")}
                      {plainHeader("Score then", true)}
                      {plainHeader("Sell-out trend score", true)}
                      {plainHeader("First flagged")}
                    </>
                  ) : null}
                  {header("sales", salesLabel, true)}
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => {
                  const flag = flagged.get(r.id);
                  return (
                    <tr key={r.id} className="relative border-b border-line transition-colors duration-150 last:border-0 hover:bg-hover">
                      <td className="px-3 py-2">
                        <Link
                          href={`/distributors/${encodeURIComponent(r.id)}${linkQuery}`}
                          className="font-medium text-ink after:absolute after:inset-0 after:content-[''] hover:underline hover:underline-offset-4"
                        >
                          {r.name}
                        </Link>
                        <span className="ml-2 font-mono text-xs text-subtle">{r.id}</span>
                        {view === "all" ? (
                          <span className="block text-xs text-muted sm:hidden">
                            {[r.region, r.tier ? tierLabel(r.tier) : ""].filter(Boolean).join(", ")}
                          </span>
                        ) : null}
                        {view === "all" && flag?.current ? (
                          <Badge tone="danger" className="ml-2 h-5 align-middle" icon={<WarningDiamond size={12} {...ICON} aria-hidden />}>
                            At risk
                          </Badge>
                        ) : null}
                      </td>
                      <td className={cx("px-3 py-2 text-muted", view === "all" && "max-sm:hidden")}>{r.region}</td>
                      <td className={cx("px-3 py-2 whitespace-nowrap text-muted", view === "all" && "max-sm:hidden")}>{r.tier ? tierLabel(r.tier) : ""}</td>
                      {view === "at-risk" ? (
                        <>
                          <td className="px-3 py-2 whitespace-nowrap text-muted">
                            {flag?.week ? fmtDate(flag.week) : flag?.snapshot ? fmtDate(flag.snapshot) : ""}
                            {flag && !flag.current ? <span className="block text-xs text-subtle">Not flagged since</span> : null}
                          </td>
                          <td className="px-3 py-2 text-right text-ink">{flag?.score != null ? fmtNumber(flag.score, 1) : ""}</td>
                          <td className="px-3 py-2 text-right text-ink">{flag?.trendScore != null ? fmtNumber(flag.trendScore, 1) : ""}</td>
                          <td className="px-3 py-2 whitespace-nowrap text-muted">{flag?.firstFlag ? fmtDate(flag.firstFlag) : ""}</td>
                        </>
                      ) : null}
                      <td className="px-3 py-2 text-right whitespace-nowrap">
                        <span className="inline-flex items-center justify-end gap-2.5">
                          {r.sales != null ? (
                            <span aria-hidden className="h-1.5 rounded-full bg-[var(--series-1)] opacity-75" style={{ width: `${Math.max(2, (r.sales / max) * 72)}px` }} />
                          ) : null}
                          <span className="min-w-[72px] text-ink">{formatValue("inr", r.sales)}</span>
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-muted" aria-live="polite">
              Showing {fmtNumber(shown.length)} of {fmtNumber(visible.length)}
            </p>
            {shown.length < visible.length ? (
              <div className="flex items-center gap-1">
                <button type="button" className={buttonClass("secondary", "sm")} onClick={() => setLimit((n) => n + PAGE)}>
                  Show {fmtNumber(Math.min(PAGE, visible.length - shown.length))} more
                </button>
                <button type="button" className={buttonClass("ghost", "sm")} onClick={() => setLimit(visible.length)}>
                  Show all
                </button>
              </div>
            ) : null}
          </div>
        </div>
      )}
    </section>
  );
}
