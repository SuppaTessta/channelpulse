import { ArrowLeft, EyeSlash } from "@phosphor-icons/react/dist/ssr";
import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { DateRangeControl } from "@/components/date-range";
import { HealthPanel, loadProfile, ProfileFacts, Receivables, SchemePanel } from "@/components/distributor-sections";
import { PageError } from "@/components/page-error";
import { PendingStatus } from "@/components/providers";
import { EmptyState } from "@/components/states";
import { FilterBar, PageBody, TopBar } from "@/components/top-bar";
import { TrendPanel, TrendSkeleton } from "@/components/trend-panel";
import { buttonClass, ICON, Sheet, Skeleton } from "@/components/ui";
import { getAnomalies, getDataWindow, getMetrics, type Filter } from "@/lib/api";
import { parseRegion, regionName } from "@/lib/config";
import { isCurrentFlag, latestSnapshot } from "@/lib/metrics";
import { param, resolvePeriod, sharedQuery, type SearchParams } from "@/lib/params";

export const metadata: Metadata = { title: "Distributor 360" };

const WIDE = "md:col-span-12";
const LEFT = "md:col-span-12 lg:col-span-7";
const RIGHT = "md:col-span-12 lg:col-span-5";

export default async function DistributorPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<SearchParams> }) {
  const [{ id: rawId }, sp] = await Promise.all([params, searchParams]);
  let id = rawId;
  try {
    id = decodeURIComponent(rawId);
  } catch {
    // A malformed escape (a stray %) stays as typed; the API then simply finds no such distributor.
  }
  const region = parseRegion(param(sp, "region"));
  const [win, catalog] = await Promise.all([getDataWindow(region), getMetrics()]);
  const back = (
    <Link href={`/distributors${sharedQuery(sp)}`} className="inline-flex items-center gap-1 hover:text-ink">
      <ArrowLeft size={12} {...ICON} aria-hidden />
      Distributor 360
    </Link>
  );
  if (!win.ok) {
    return (
      <>
        <TopBar title={id} region={region} win={win} catalog={catalog}>
          {back}
        </TopBar>
        <PageBody>
          <PageError error={win.error} />
        </PageBody>
      </>
    );
  }
  const period = resolvePeriod(sp, win.value);
  const [profile, anomalies] = await Promise.all([loadProfile(id, region), getAnomalies(region, period.range.to)]);
  if (!profile.ok || !profile.value.profile) {
    return (
      <>
        <TopBar title={id} region={region} win={win} catalog={catalog}>
          {back}
        </TopBar>
        <PageBody>
          {!profile.ok ? (
            <PageError error={profile.error} />
          ) : (
            <section className="rounded-panel border border-line bg-surface px-4 md:px-6">
              <EmptyState
                icon={<EyeSlash size={20} {...ICON} aria-hidden />}
                title={`${id} isn't visible to this region claim`}
                body={
                  region === "ALL"
                    ? "No distributor with this ID has any primary sales in the warehouse. Check the ID in the distributor list."
                    : `Viewing as ${regionName(region)}, row-level security hides distributors outside that region, or the ID doesn't exist.`
                }
                action={
                  <Link href={`/distributors${sharedQuery(sp)}`} className={buttonClass("secondary", "sm")}>
                    Back to the distributor list
                  </Link>
                }
              />
            </section>
          )}
        </PageBody>
      </>
    );
  }

  const p = profile.value.profile;
  const latest = anomalies.ok ? latestSnapshot(anomalies.value.rows) : null;
  const health = anomalies.ok ? anomalies.value.rows.find((a) => a.detector === "distributor_health" && a.entity_id === p.id) : undefined;
  // Current only if flagged in the latest snapshot; an older flag is shown as history, never as "at risk".
  const flag = health && isCurrentFlag(health, latest) ? health : undefined;
  const pastFlag = health && !flag ? health : undefined;
  const filters: Filter[] = [{ dimension: "distributor", op: "=", value: p.id }];
  const ctx = { period, win: win.value, region, catalog, filters };

  return (
    <>
      <TopBar title={p.name} region={region} win={win} catalog={catalog}>
        {back}
      </TopBar>
      <FilterBar>
        <DateRangeControl range={period.range} presetKey={period.presetKey} presets={period.options} min={win.value.dataStart} max={win.value.asOf} />
        <PendingStatus />
      </FilterBar>
      <PageBody>
        <ProfileFacts profile={p} flag={flag} pastFlag={pastFlag} />
        <Sheet className="md:grid-cols-12">
          <Suspense fallback={<TrendSkeleton title="Distributor health score" className={WIDE} height="h-80" />}>
            <HealthPanel ctx={ctx} flag={flag} pastFlag={pastFlag} className={WIDE} />
          </Suspense>
          <Suspense fallback={<TrendSkeleton title="Sell-in and sell-out" className={LEFT} />}>
            <TrendPanel
              {...ctx}
              id="units"
              title="Sell-in and sell-out"
              subtitle="Units by week, invoiced to this distributor and sold on to retailers"
              metrics={[
                { name: "primary_units", slot: 1 },
                { name: "secondary_units", slot: 2 },
              ]}
              grain="week"
              mark="bar"
              className={LEFT}
            />
          </Suspense>
          <Suspense fallback={<TrendSkeleton title="Channel days of stock" className={RIGHT} />}>
            <TrendPanel
              {...ctx}
              id="stock"
              title="Channel days of stock"
              subtitle="This distributor, read on each week's last day"
              metrics={[{ name: "channel_days_of_stock", slot: 1 }]}
              grain="week"
              mark="line"
              className={RIGHT}
            />
          </Suspense>
          <Suspense fallback={<TrendSkeleton title="Collections" className={LEFT} />}>
            <TrendPanel
              {...ctx}
              id="collections"
              title="Collections"
              subtitle="Days sales outstanding by invoice month"
              metrics={[{ name: "dso", slot: 1 }]}
              grain="month"
              mark="line"
              className={LEFT}
              lead={
                <Suspense fallback={<Skeleton className="h-16 w-full" />}>
                  <Receivables ctx={ctx} />
                </Suspense>
              }
            />
          </Suspense>
          <Suspense fallback={<TrendSkeleton title="Field visits" className={RIGHT} />}>
            <TrendPanel
              {...ctx}
              id="visits"
              title="Field visits"
              subtitle="Sales rep visits by week, and how many the geofence verified"
              metrics={[
                { name: "field_visits", slot: "deemph" },
                { name: "verified_field_visits", slot: 1 },
              ]}
              grain="week"
              mark="bar"
              barMode="overlay"
              className={RIGHT}
            />
          </Suspense>
          <Suspense fallback={<TrendSkeleton title="Scheme participation" className={WIDE} height="h-40" />}>
            <SchemePanel ctx={ctx} className={WIDE} />
          </Suspense>
        </Sheet>
      </PageBody>
    </>
  );
}
