import { Flask, WarningDiamond, X } from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";
import type { ReactNode } from "react";
import { query, queryAll, type Anomalies, type Anomaly, type DataWindow, type Filter, type Metric, type Query, type Result } from "@/lib/api";
import type { Region } from "@/lib/config";
import { addDays, addMonths, minDate, monthEnd, toISODate } from "@/lib/dates";
import { fmtDate, fmtMonth, fmtNumber, formatValue } from "@/lib/format";
import { anomaliesDefQuery, fallbackMetric, isCurrentFlag, latestSnapshot, shortLabel, toDefMetric, toDefQuery } from "@/lib/metrics";
import { hrefWith, type SearchParams } from "@/lib/params";
import { niceThresholds } from "@/lib/series";
import { column, num, records, scalar, str } from "@/lib/table";
import { ChartPanel } from "./chart-panel";
import type { Option } from "./param-select";
import { Heatmap, type HeatRow } from "./charts/heatmap";
import { TimeChart, type Bucket } from "./charts/time-chart";
import { DataTable } from "./data-table";
import { DefinitionButton } from "./definition";
import { EmptyState, ErrorState } from "./states";
import { Badge, buttonClass, cx, ICON } from "./ui";

export type QualityCtx = {
  region: Region;
  win: DataWindow;
  catalog: Result<Record<string, Metric>>;
  filters: Filter[];
  metric: string;
  sp: SearchParams;
};

const AGE = "batch_cohort_month__months_since_ship";
/** Only cells where every unit has been out the whole month, so an incomplete cell is never painted as low. */
const OBSERVED: Filter = { dimension: "batch_cohort_month__is_fully_observed", op: "=", value: true };
const metricOf = (c: QualityCtx["catalog"], name: string) => (c.ok ? c.value[name] : undefined) ?? fallbackMetric(name);
/** To-date claim rates exist only across all failure modes; say so when the page is showing base cracks. */
const allModesNote = (ctx: QualityCtx) => (ctx.metric.includes("base_crack") ? ", all failure modes" : "");

/** Plant and product choices, from the cohorts themselves (only tanks are serialised, decisions D3). */
export async function loadOptions(region: Region): Promise<Result<{ plants: Option[]; products: Option[] }>> {
  const r = await query({ metric_name: "cohort_units_shipped", group_by: ["batch__plant_id", "batch__plant_name", "batch__product__product_name"] }, region);
  if (!r.ok) return r;
  const recs = records(r.value.result.data);
  const plants = new Map<string, string>();
  const products = new Set<string>();
  for (const rec of recs) {
    const id = str(rec.batch__plant_id);
    if (id) plants.set(id, str(rec.batch__plant_name) ?? id);
    const name = str(rec.batch__product__product_name);
    if (name) products.add(name);
  }
  const names = [...products].sort((a, b) => a.localeCompare(b, "en", { numeric: true }));
  // Every product name starts with the brand; the options drop the repeated word, the filter keeps the full name.
  const brand = names.length > 1 && names.every((n) => n.split(" ")[0] === names[0].split(" ")[0]) ? `${names[0].split(" ")[0]} ` : "";
  return {
    ok: true,
    value: {
      plants: [...plants].map(([value, label]) => ({ value, label })).sort((a, b) => a.label.localeCompare(b.label)),
      products: names.map((n) => ({ value: n, label: brand && n.startsWith(brand) ? n.slice(brand.length) : n })),
    },
  };
}

export async function CohortHeatmap({ ctx, activeMonth, className }: { ctx: QualityCtx; activeMonth: string | null; className?: string }) {
  const metric = metricOf(ctx.catalog, ctx.metric);
  const valueLabel = shortLabel(metric.label);
  const title = "Claims by manufacture month and months since shipment";
  const subtitle = `${valueLabel}. A cell shows once every unit in it has been out that long.`;
  const months = await query({ metric_name: "cohort_units_shipped", group_by: ["metric_time__month"], filters: ctx.filters }, ctx.region);
  if (!months.ok) return <ChartPanel id="cohorts" title={title} subtitle={subtitle} className={className} chart={<ErrorState compact error={months.error} />} />;

  const monthRows = records(months.value.result.data)
    .map((r) => ({ key: toISODate(r.metric_time__month), units: num(r.cohort_units_shipped) }))
    .filter((r): r is { key: string; units: number | null } => !!r.key)
    .sort((a, b) => a.key.localeCompare(b.key));
  if (!monthRows.length) {
    return (
      <ChartPanel
        id="cohorts"
        title={title}
        subtitle={subtitle}
        className={className}
        chart={<EmptyState title="No shipped cohorts for this filter" body="No serialised units shipped from batches matching this plant and product. Clear a filter." />}
      />
    );
  }
  // At most 12 manufacture months per query, so no result reaches the API's 500-row cap.
  const first = monthRows[0].key;
  const last = monthRows.at(-1)!.key;
  const chunks: { start: string; end: string }[] = [];
  for (let s = first; s <= last; s = addMonths(s, 12)) chunks.push({ start: s, end: minDate(addDays(addMonths(s, 12), -1), monthEnd(last)) });
  const r = await queryAll(
    chunks.map((c) => ({ metric_name: ctx.metric, group_by: ["metric_time__month", AGE], filters: [...ctx.filters, OBSERVED], date_range: c })),
    ctx.region,
  );
  if (!r.ok) return <ChartPanel id="cohorts" title={title} subtitle={subtitle} className={className} chart={<ErrorState compact error={r.error} />} />;

  const values = new Map<string, number | null>();
  let maxAge = 0;
  let maxValue = 0;
  for (const q of r.value) {
    for (const rec of records(q.result.data)) {
      const m = toISODate(rec.metric_time__month);
      const age = num(rec[AGE]);
      if (!m || age == null) continue;
      const v = num(rec[ctx.metric]);
      values.set(`${m}|${age}`, v);
      maxAge = Math.max(maxAge, age);
      if (v != null) maxValue = Math.max(maxValue, v);
    }
  }
  const cols = Array.from({ length: maxAge + 1 }, (_, i) => i);
  const rows: HeatRow[] = monthRows.map((m) => ({ key: m.key, label: fmtMonth(m.key), units: m.units }));
  const cells = rows.map((row) => cols.map((c) => values.get(`${row.key}|${c}`) ?? null));
  const capped = r.value.some((q) => q.result.row_cap_hit);
  const definition = (
    <DefinitionButton
      title={title}
      metrics={[toDefMetric(metric), toDefMetric(metricOf(ctx.catalog, "cohort_units_shipped"))]}
      queries={[toDefQuery(months.value, "Manufacture months with shipped units"), ...r.value.map((q, i) => toDefQuery(q, `Cells made ${fmtMonth(chunks[i].start)} to ${fmtMonth(monthEnd(chunks[i].end))}`))]}
    />
  );
  return (
    <ChartPanel
      id="cohorts"
      title={title}
      subtitle={subtitle}
      actions={definition}
      className={className}
      chart={
        <Heatmap
          rows={rows}
          cols={cols}
          cells={cells}
          thresholds={niceThresholds(maxValue)}
          title={title}
          valueLabel={valueLabel}
          activeRow={activeMonth}
        />
      }
      table={
        <DataTable
          caption={`${valueLabel} by manufacture month (rows) and months since shipment (columns)`}
          columns={[{ label: "Made" }, ...cols.map((c) => ({ label: String(c), numeric: true }))]}
          rows={rows.map((row, i) => [row.label, ...cells[i].map((v) => (v == null ? "" : formatValue("per1000", v)))])}
          maxHeight="max-h-[520px]"
        />
      }
      footer={
        <>
          <p className="text-xs text-subtle">Select a row to list the resin lots made that month. Empty cells are not yet fully observed, not zero.</p>
          {capped ? <p className="text-xs text-adhoc">A query reached the API&apos;s row cap, so some cells may be missing.</p> : null}
        </>
      }
    />
  );
}

const detail = (a: Anomaly, key: string) => num(a.details?.[key]);

/** What the lot scan measured, in its own terms: the rate ratio and the claims it expected from peers. */
export function lotFlagText(a: Anomaly): string {
  const claims = detail(a, "claims");
  const expected = detail(a, "expected");
  return [
    a.effect_size != null ? `${fmtNumber(a.effect_size, 2)}× the peer rate` : null,
    claims != null && expected != null ? `${fmtNumber(claims)} claims against ${fmtNumber(expected, 1)} expected` : null,
    a.first_flag_date ? `first flagged ${fmtDate(String(a.first_flag_date).slice(0, 10))}` : null,
  ]
    .filter(Boolean)
    .join(", ");
}

export function LotFlags({ anomalies, sp, activeLot, className }: { anomalies: Result<Anomalies>; sp: SearchParams; activeLot: string | null; className?: string }) {
  const title = "Resin lots flagged by the lot scan";
  if (!anomalies.ok) {
    return (
      <section aria-labelledby="flags" className={className}>
        <h2 id="flags" className="text-sm font-semibold text-ink">
          {title}
        </h2>
        <ErrorState compact error={anomalies.error} />
      </section>
    );
  }
  const latest = latestSnapshot(anomalies.value.rows);
  const byCurrentThenSize = (a: Anomaly, b: Anomaly) =>
    Number(isCurrentFlag(b, latest)) - Number(isCurrentFlag(a, latest)) || (num(b.effect_size) ?? 0) - (num(a.effect_size) ?? 0);
  const lots = anomalies.value.rows.filter((a) => a.detector === "lot_scan").sort(byCurrentThenSize);
  const installers = anomalies.value.rows.filter((a) => a.detector === "installer_scan").sort(byCurrentThenSize);
  return (
    <section aria-labelledby="flags" className={cx("flex flex-col gap-4", className)}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id="flags" className="text-sm font-semibold text-ink">
            {title}
          </h2>
          <p className="mt-0.5 max-w-[60ch] text-xs text-muted">
            The pre-registered scan compares each lot&apos;s claims with plant-line peers at equal time since shipment.
            {latest ? ` Latest weekly snapshot ${fmtDate(latest)}.` : ""}
          </p>
        </div>
        <DefinitionButton title="Detector flags" metrics={[]} queries={[anomaliesDefQuery(anomalies.value, "Detector flags")]} />
      </div>
      {lots.length === 0 ? (
        <p className="text-sm text-muted">No resin lot has been flagged.</p>
      ) : (
        <ul className="flex flex-col divide-y divide-line">
          {lots.map((f) => {
            const current = isCurrentFlag(f, latest);
            return (
              <li key={`${f.entity_id}|${f.failure_mode}`}>
                <Link
                  href={hrefWith("/quality", sp, { lot: f.entity_id, batch: null, month: null })}
                  scroll={false}
                  aria-current={activeLot === f.entity_id ? "true" : undefined}
                  className="-mx-2 flex flex-col gap-1 rounded-control px-2 py-2.5 hover:bg-hover aria-[current]:bg-accent-soft"
                >
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-[13px] text-ink">{f.entity_id}</span>
                    {f.failure_mode ? <Badge tone={current ? "danger" : "neutral"}>{f.failure_mode.replace(/_/g, " ")}</Badge> : null}
                    {current ? null : <span className="text-xs text-subtle">not flagged in the latest snapshot</span>}
                  </span>
                  <span className="text-xs text-muted">{lotFlagText(f)}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
      {installers.length ? (
        <div className="flex flex-col gap-2 border-t border-line pt-4">
          <h3 className="text-xs font-semibold text-ink">Installers flagged by the installer scan</h3>
          <p className="text-xs text-muted">Claims on units an installer fitted, against the rest of their district. A flag spread across many plants and lots doesn&apos;t come from a single batch.</p>
          <ul className="flex flex-col gap-2">
            {installers.map((f) => (
              <li key={f.entity_id} className="text-xs text-ink">
                <span className="font-mono text-[13px]">{f.entity_id}</span>
                <span className="text-muted">
                  {": "}
                  {[
                    f.effect_size != null ? `${fmtNumber(f.effect_size, 2)}× the district rate` : null,
                    detail(f, "claims") != null && detail(f, "expected") != null ? `${fmtNumber(detail(f, "claims")!)} claims against ${fmtNumber(detail(f, "expected")!, 1)} expected` : null,
                    detail(f, "plants_spanned") != null ? `units from ${fmtNumber(detail(f, "plants_spanned")!)} plants and ${fmtNumber(detail(f, "resin_lots_spanned") ?? 0)} resin lots` : null,
                  ]
                    .filter(Boolean)
                    .join(", ")}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

/** Elevated because it is a focused layer over the heatmap: an outer tray and an inner plate (radius 10 + 4). */
function DrillShell({ title, eyebrow, closeHref, children, actions }: { title: string; eyebrow: string; closeHref: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section aria-labelledby="drill-title" className="rounded-[14px] bg-hover p-1 ring-1 ring-line">
      <div className="flex flex-col gap-4 rounded-panel bg-raised p-4 shadow-raised md:p-5">
        <header className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs text-muted">{eyebrow}</p>
            <h2 id="drill-title" className="font-mono text-[15px] font-semibold break-all text-ink">
              {title}
            </h2>
          </div>
          <div className="flex items-center gap-1">
            {actions}
            <Link href={closeHref} scroll={false} className={buttonClass("ghost", "icon")} aria-label="Close drill-down">
              <X size={18} {...ICON} aria-hidden />
            </Link>
          </div>
        </header>
        {children}
      </div>
    </section>
  );
}

export async function MonthDrill({ ctx, month }: { ctx: QualityCtx; month: string }) {
  const range = { start: month, end: monthEnd(month) };
  const group = ["batch__resin_lot_id", "batch__plant_id", "batch__line_no"];
  const r = await queryAll(
    [
      { metric_name: "claims_per_1000_units", group_by: group, filters: ctx.filters, date_range: range },
      { metric_name: "cohort_units_shipped", group_by: group, filters: ctx.filters, date_range: range },
    ],
    ctx.region,
  );
  const close = hrefWith("/quality", ctx.sp, { month: null });
  if (!r.ok) {
    return (
      <DrillShell title={fmtMonth(month)} eyebrow="Made in" closeHref={close}>
        <ErrorState compact error={r.error} />
      </DrillShell>
    );
  }
  const key = (rec: Record<string, unknown>) => `${str(rec.batch__resin_lot_id)}|${str(rec.batch__plant_id)}|${str(rec.batch__line_no)}`;
  const units = new Map(records(r.value[1].result.data).map((rec) => [key(rec), num(rec.cohort_units_shipped)]));
  const lots = records(r.value[0].result.data)
    .map((rec) => ({ lot: str(rec.batch__resin_lot_id) ?? "", plant: str(rec.batch__plant_id) ?? "", line: str(rec.batch__line_no) ?? "", rate: num(rec.claims_per_1000_units), units: units.get(key(rec)) ?? null }))
    .sort((a, b) => (b.rate ?? -1) - (a.rate ?? -1));
  const metric = metricOf(ctx.catalog, "claims_per_1000_units");
  return (
    <DrillShell
      title={fmtMonth(month)}
      eyebrow="Resin lots made in"
      closeHref={close}
      actions={
        <DefinitionButton
          title={`Lots made in ${fmtMonth(month)}`}
          metrics={[toDefMetric(metric), toDefMetric(metricOf(ctx.catalog, "cohort_units_shipped"))]}
          queries={r.value.map((q, i) => toDefQuery(q, i === 0 ? "Claims per 1,000 units by lot" : "Units shipped by lot"))}
          trigger={<span className="text-xs">SQL</span>}
        />
      }
    >
      <p className="text-xs text-muted">Claims to date. Lots made in the same month have had about the same time in the field, so they compare fairly.</p>
      {lots.length === 0 ? (
        <p className="text-sm text-muted">No lot shipped units from this month under the current filter.</p>
      ) : (
        <DataTable
          caption={`Resin lots made in ${fmtMonth(month)}`}
          columns={[{ label: "Resin lot" }, { label: "Plant, line" }, { label: "Units", numeric: true }, { label: `${shortLabel(metric.label)}${allModesNote(ctx)}`, numeric: true }]}
          rows={lots.map((l) => [
            <Link key="l" href={hrefWith("/quality", ctx.sp, { lot: l.lot, month: null, batch: null })} scroll={false} className="font-mono text-accent underline-offset-4 hover:underline">
              {l.lot}
            </Link>,
            `${l.plant}, line ${l.line}`,
            formatValue("count", l.units),
            formatValue("per1000", l.rate),
          ])}
        />
      )}
    </DrillShell>
  );
}

const ageBuckets = (maxAge: number): Bucket[] =>
  Array.from({ length: maxAge + 1 }, (_, age) => ({
    start: String(age),
    end: String(age),
    label: `${age} month${age === 1 ? "" : "s"} since shipment`,
    tick: String(age),
    tickYear: String(age),
    year: "",
    partial: null,
    provisional: false,
  }));

function curve(q: Query, metric: string, maxAge: number): (number | null)[] {
  const ages = column(q.result.data, AGE) ?? [];
  const vals = column(q.result.data, metric) ?? [];
  const byAge = new Map(ages.map((a, i) => [num(a), num(vals[i])]));
  return Array.from({ length: maxAge + 1 }, (_, age) => byAge.get(age) ?? null);
}

/** A resin lot's (or one batch's) claim curve against plant-line peers made in the 12 months before it. */
export async function EntityDrill({ ctx, kind, id, anomalies }: { ctx: QualityCtx; kind: "lot" | "batch"; id: string; anomalies: Result<Anomalies> }) {
  const idDimension = kind === "lot" ? "batch__resin_lot_id" : "batch";
  const own: Filter = { dimension: idDimension, op: "=", value: id };
  const close = hrefWith("/quality", ctx.sp, { lot: null, batch: null });
  const eyebrow = kind === "lot" ? "Resin lot" : "Batch";
  const factGroup = ["batch__plant_id", "batch__plant_name", "batch__line_no", ...(kind === "batch" ? ["batch__resin_lot_id"] : [])];
  const facts = await queryAll(
    [
      { metric_name: "cohort_units_shipped", group_by: factGroup, filters: [own] },
      { metric_name: "cohort_units_shipped", group_by: ["metric_time__month"], filters: [own] },
      { metric_name: "claims_per_1000_units", filters: [own] },
      { metric_name: ctx.metric, group_by: [AGE], filters: [own, OBSERVED] },
      ...(kind === "lot" ? [{ metric_name: "cohort_units_shipped", group_by: ["batch", "metric_time__day"], filters: [own] }] : []),
    ],
    ctx.region,
  );
  if (!facts.ok) {
    return (
      <DrillShell title={id} eyebrow={eyebrow} closeHref={close}>
        <ErrorState compact error={facts.error} />
      </DrillShell>
    );
  }
  const [placeQ, monthsQ, rateQ, curveQ, batchesQ] = facts.value;
  const place = records(placeQ.result.data)[0];
  if (!place) {
    return (
      <DrillShell title={id} eyebrow={eyebrow} closeHref={close}>
        <EmptyState icon={<Flask size={20} {...ICON} aria-hidden />} title="No shipped cohort for this ID" body="The warehouse has no shipped, serialised units from it. Check the ID, or pick a lot from the heatmap." />
      </DrillShell>
    );
  }
  const plant = str(place.batch__plant_id)!;
  const line = place.batch__line_no as string | number;
  const made = (column(monthsQ.result.data, "metric_time__month") ?? []).map(toISODate).filter((d): d is string => !!d).sort();
  const firstMonth = made[0];
  const peerFilter: Filter = { dimension: idDimension, op: "!=", value: id };
  const peersR = firstMonth
    ? await query(
        {
          metric_name: ctx.metric,
          group_by: [AGE],
          filters: [
            { dimension: "batch__plant_id", op: "=", value: plant },
            { dimension: "batch__line_no", op: "=", value: line },
            peerFilter,
            OBSERVED,
          ],
          date_range: { start: addMonths(firstMonth, -12), end: addDays(firstMonth, -1) },
        },
        ctx.region,
      )
    : null;
  const metric = metricOf(ctx.catalog, ctx.metric);
  const ownAges = (column(curveQ.result.data, AGE) ?? []).map(num).filter((a): a is number => a != null);
  const peerAges = peersR?.ok ? (column(peersR.value.result.data, AGE) ?? []).map(num).filter((a): a is number => a != null) : [];
  const maxAge = Math.max(0, ...ownAges, ...peerAges);
  const buckets = ageBuckets(maxAge);
  const lotId = kind === "lot" ? id : str(place.batch__resin_lot_id);
  const flags = anomalies.ok ? anomalies.value.rows.filter((a) => a.detector === "lot_scan" && a.entity_id === lotId) : [];
  const series = [
    { key: "own", label: kind === "lot" ? "This lot" : "This batch", slot: 1 as const, values: curve(curveQ, ctx.metric, maxAge), horizonBound: false },
    ...(peersR?.ok && peersR.value.result.row_count
      ? [{ key: "peers", label: `${plant} line ${line} peers`, slot: "deemph" as const, values: curve(peersR.value, ctx.metric, maxAge), horizonBound: false }]
      : []),
  ];
  const batches = batchesQ ? records(batchesQ.result.data).map((b) => ({ id: str(b.batch) ?? "", day: toISODate(b.metric_time__day) })) : [];
  const queries = [
    toDefQuery(placeQ, "Plant and line, units shipped"),
    toDefQuery(monthsQ, "Manufacture months"),
    toDefQuery(rateQ, "Claims per 1,000 units to date"),
    toDefQuery(curveQ, `${series[0].label}: curve by months since shipment`),
    ...(peersR?.ok ? [toDefQuery(peersR.value, "Plant-line peers made in the 12 months before")] : []),
    ...(batchesQ ? [toDefQuery(batchesQ, "Batches in the lot")] : []),
  ];

  return (
    <DrillShell
      title={id}
      eyebrow={eyebrow}
      closeHref={close}
      actions={<DefinitionButton title={`${eyebrow} ${id}`} metrics={[toDefMetric(metric), toDefMetric(metricOf(ctx.catalog, "claims_per_1000_units"))]} queries={queries} trigger={<span className="text-xs">SQL</span>} />}
    >
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <div>
          <dt className="text-xs text-muted">Plant, line</dt>
          <dd className="text-ink">
            {str(place.batch__plant_name) ?? plant}, line {String(line)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Made</dt>
          <dd className="text-ink">{made.length ? (made.length === 1 ? fmtMonth(made[0]) : `${fmtMonth(made[0])} to ${fmtMonth(made.at(-1)!)}`) : "Unknown"}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Units shipped</dt>
          <dd className="text-ink">{formatValue("count", scalar(placeQ.result.data, "cohort_units_shipped"))}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Claims per 1,000 to date{allModesNote(ctx)}</dt>
          <dd className="text-ink">{formatValue("per1000", scalar(rateQ.result.data, "claims_per_1000_units"))}</dd>
        </div>
        {kind === "batch" && lotId ? (
          <div className="col-span-2">
            <dt className="text-xs text-muted">Resin lot</dt>
            <dd>
              <Link href={hrefWith("/quality", ctx.sp, { lot: lotId, batch: null })} scroll={false} className="font-mono text-accent underline-offset-4 hover:underline">
                {lotId}
              </Link>
            </dd>
          </div>
        ) : null}
      </dl>
      {flags.length ? (
        <div className="flex flex-col gap-1.5">
          {flags.map((f) => {
            const current = anomalies.ok && isCurrentFlag(f, latestSnapshot(anomalies.value.rows));
            return (
              <p key={String(f.failure_mode)} className="flex flex-wrap items-center gap-2 text-xs text-ink">
                <Badge tone={current ? "danger" : "neutral"} icon={<WarningDiamond size={12} {...ICON} aria-hidden />}>
                  Lot scan: {String(f.failure_mode ?? "flag").replace(/_/g, " ")}
                </Badge>
                <span className="text-muted">
                  {lotFlagText(f)}
                  {current ? "" : ", not flagged in the latest snapshot"}
                </span>
              </p>
            );
          })}
        </div>
      ) : (
        <p className="text-xs text-subtle">{lotId ? "The lot scan hasn't flagged this lot." : ""}</p>
      )}
      <div className="flex flex-col gap-1">
        <h3 className="text-xs font-medium text-ink">{shortLabel(metric.label)}, by months since shipment</h3>
        {series[0].values.every((v) => v == null) ? (
          <p className="text-sm text-muted">No month is fully observed yet: every unit must have been out at least a month.</p>
        ) : (
          <TimeChart buckets={buckets} series={series} mark="line" kind="per1000" height={200} title={`${eyebrow} ${id} against its peers`} grain="month since shipment" />
        )}
        <p className="text-xs text-subtle">
          Each age pools the batches fully observed at that age, so the oldest ages cover fewer batches and a curve can dip.
          {series.length === 1 ? " No plant-line peers were made in the 12 months before it." : ` Peers: other ${kind === "lot" ? "lots" : "batches"} on the same line made in the 12 months before.`}
        </p>
        {!peersR?.ok && peersR ? <ErrorState compact error={peersR.error} /> : null}
      </div>
      {batches.length ? (
        <details className="text-sm">
          <summary className="w-fit text-xs text-muted underline decoration-line-strong underline-offset-4 hover:text-ink">{batches.length} batches in this lot</summary>
          <ul className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1">
            {batches.map((b) => (
              <li key={b.id}>
                <Link href={hrefWith("/quality", ctx.sp, { batch: b.id, lot: null })} scroll={false} className="font-mono text-xs text-accent underline-offset-4 hover:underline">
                  {b.id}
                </Link>
                {b.day ? <span className="ml-2 text-xs text-subtle">{fmtDate(b.day)}</span> : null}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </DrillShell>
  );
}
