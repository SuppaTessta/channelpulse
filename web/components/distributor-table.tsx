"use client";

import { CaretDown, CaretUp, MagnifyingGlass, WarningDiamond } from "@phosphor-icons/react";
import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";
import { fmtDate, fmtNumber, formatValue } from "@/lib/format";
import { Badge, cx, ICON } from "./ui";

export type DistributorRow = { id: string; name: string; region: string; tier: string; sales: number | null };
export type RiskFlag = {
  id: string;
  region: string | null;
  firstFlag: string | null;
  snapshot: string | null;
  effect: number | null;
  pValue: number | null;
  details: [string, string][];
};

type SortKey = "name" | "region" | "tier" | "sales";
type View = "all" | "at-risk";

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
  const byId = useMemo(() => new Map(rows.map((r) => [r.id, r])), [rows]);
  const flagged = useMemo(() => new Map((flags ?? []).map((f) => [f.id, f])), [flags]);
  const max = Math.max(1, ...rows.map((r) => r.sales ?? 0));

  const needle = q.trim().toLowerCase();
  const visible = useMemo(() => {
    const base = view === "at-risk" ? (flags ?? []).map((f) => byId.get(f.id) ?? { id: f.id, name: f.id, region: f.region ?? "", tier: "", sales: null }) : rows;
    const matched = needle ? base.filter((r) => [r.id, r.name, r.region, tierLabel(r.tier)].some((v) => v.toLowerCase().includes(needle))) : base;
    const val = (r: DistributorRow) => (sort.key === "sales" ? (r.sales ?? -Infinity) : r[sort.key]);
    return [...matched].sort((a, b) => {
      const x = val(a), y = val(b);
      return (x < y ? -1 : x > y ? 1 : 0) * sort.dir || a.name.localeCompare(b.name);
    });
  }, [view, flags, byId, rows, needle, sort]);

  const setViewAndUrl = (v: View) => {
    setView(v);
    syncUrl(v, q);
  };
  const header = (key: SortKey, label: string, numeric = false) => {
    const active = sort.key === key;
    return (
      <th scope="col" aria-sort={active ? (sort.dir === 1 ? "ascending" : "descending") : "none"} className={cx("border-b border-line px-3 py-2 font-medium", numeric ? "text-right" : "text-left")}>
        <button
          type="button"
          onClick={() => setSort((s) => ({ key, dir: s.key === key ? (s.dir === 1 ? -1 : 1) : key === "sales" ? -1 : 1 }))}
          className={cx("inline-flex h-8 items-center gap-1 rounded-control px-1 text-xs hover:text-ink", active ? "text-ink" : "text-muted", numeric && "flex-row-reverse")}
        >
          {label}
          {active ? sort.dir === 1 ? <CaretUp size={12} {...ICON} aria-hidden /> : <CaretDown size={12} {...ICON} aria-hidden /> : null}
        </button>
      </th>
    );
  };

  return (
    <section aria-labelledby="distributors-heading" className="flex flex-col gap-3 rounded-panel border border-line bg-surface p-4 md:p-5" data-dim="">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h2 id="distributors-heading" className="text-sm font-semibold text-ink">
            Distributors
          </h2>
          <div role="group" aria-label="Distributor view" className="flex items-center gap-0.5 rounded-control bg-hover p-0.5">
            {(["all", "at-risk"] as const).map((v) => (
              <button
                key={v}
                type="button"
                aria-pressed={view === v}
                onClick={() => setViewAndUrl(v)}
                className={cx(
                  "h-8 rounded-[5px] px-2.5 text-[13px] font-medium transition-colors duration-150 max-md:h-9",
                  view === v ? "bg-surface text-ink shadow-[0_0_0_1px_var(--border-strong)]" : "text-muted hover:text-ink",
                )}
              >
                {v === "all" ? `All ${fmtNumber(rows.length)}` : `At risk ${flags ? fmtNumber(flags.length) : ""}`}
              </button>
            ))}
          </div>
        </div>
        <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
        {actions}
        <label className="flex w-full items-center gap-2 text-xs text-muted sm:w-auto">
          Search
          <span className="relative flex-1 sm:flex-none">
            <MagnifyingGlass size={16} {...ICON} className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-subtle" aria-hidden />
            <input
              type="search"
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                syncUrl(view, e.target.value);
              }}
              placeholder="Name, ID, region or tier"
              className="h-10 w-full rounded-control border border-control bg-surface pr-3 pl-8 text-base text-ink placeholder:text-subtle sm:w-64 md:h-8 md:text-sm"
            />
          </span>
        </label>
        </div>
      </div>

      {view === "at-risk" ? (
        <p className="max-w-[80ch] text-xs text-muted">
          <WarningDiamond size={14} {...ICON} className="mr-1 inline align-[-2px] text-danger" aria-hidden />
          {riskRule}
        </p>
      ) : null}

      {view === "at-risk" && flagsError ? (
        <p className="text-sm text-danger">{flagsError}</p>
      ) : visible.length === 0 ? (
        <p role="status" className="py-8 text-sm text-muted">
          {needle ? `No distributor matches "${q.trim()}". Clear the search or try an ID such as D0042.` : view === "at-risk" ? "No distributor is flagged at risk for this snapshot and region claim." : "No distributor has primary sales in this range."}
        </p>
      ) : (
        <div className="-mx-4 overflow-x-auto md:mx-0">
          <table className="w-full min-w-[560px] border-collapse text-[13px]">
            <caption className="sr-only">
              {view === "at-risk" ? "Distributors flagged at risk" : "Distributors by primary sales"}, {visible.length} rows
            </caption>
            <thead>
              <tr>
                {header("name", "Distributor")}
                {header("region", "Region")}
                {header("tier", "Tier")}
                {view === "at-risk" ? (
                  <>
                    <th scope="col" className="border-b border-line px-3 py-2 text-left text-xs font-medium text-muted">
                      Flagged since
                    </th>
                    <th scope="col" className="border-b border-line px-3 py-2 text-left text-xs font-medium text-muted">
                      Detector output
                    </th>
                  </>
                ) : null}
                {header("sales", salesLabel, true)}
              </tr>
            </thead>
            <tbody>
              {visible.map((r) => {
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
                      {view === "all" && flag ? (
                        <Badge tone="danger" className="ml-2 align-middle" icon={<WarningDiamond size={12} {...ICON} aria-hidden />}>
                          At risk
                        </Badge>
                      ) : null}
                    </td>
                    <td className="px-3 py-2 text-muted">{r.region}</td>
                    <td className="px-3 py-2 whitespace-nowrap text-muted">{r.tier ? tierLabel(r.tier) : ""}</td>
                    {view === "at-risk" ? (
                      <>
                        <td className="px-3 py-2 whitespace-nowrap text-muted">{flag?.firstFlag ? fmtDate(flag.firstFlag) : ""}</td>
                        <td className="px-3 py-2 font-mono text-xs text-muted">
                          {[
                            flag?.effect != null ? `effect ${fmtNumber(flag.effect, 2)}` : null,
                            flag?.pValue != null ? `p ${flag.pValue.toPrecision(2)}` : null,
                            ...(flag?.details ?? []).slice(0, 3).map(([k, v]) => `${k} ${v}`),
                          ]
                            .filter(Boolean)
                            .join(", ")}
                        </td>
                      </>
                    ) : null}
                    <td className="px-3 py-2 text-right whitespace-nowrap">
                      <span className="inline-flex items-center justify-end gap-2">
                        {r.sales != null ? <span aria-hidden className="h-1.5 rounded-full bg-[var(--series-1)] opacity-70" style={{ width: `${Math.max(2, (r.sales / max) * 64)}px` }} /> : null}
                        <span className="text-ink">{formatValue("inr", r.sales)}</span>
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
