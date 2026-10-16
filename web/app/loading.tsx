import { Skeleton } from "@/components/ui";

/** Shown while a page's first queries (the as-of date) resolve. Shaped like the page: bar, filters, strip, panels. */
export default function Loading() {
  return (
    <div aria-busy="true">
      <span className="sr-only">Loading the page</span>
      {/* Built like the top bar (top-bar.tsx): the title, and the pill on its own row below 1280px. */}
      <div className="border-b border-line">
        <div className="mx-auto flex max-w-[1440px] flex-wrap items-center gap-x-5 gap-y-1 px-4 py-3 md:px-6 md:py-4 xl:min-h-[88px] xl:flex-nowrap">
          <div className="min-w-0 flex-1 py-1">
            <Skeleton className="h-[38px] w-48 md:h-[46px] md:w-72" />
          </div>
          <Skeleton className="h-[98px] w-full rounded-panel md:h-[50px] xl:w-[600px]" />
        </div>
      </div>
      <div className="mx-auto flex max-w-[1440px] flex-col gap-4 px-4 pt-4 md:gap-5 md:px-6 md:pt-5">
        <Skeleton className="h-9 w-72" />
        <Skeleton className="h-40 w-full rounded-panel" />
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          <Skeleton className="h-72 rounded-panel lg:col-span-8" />
          <Skeleton className="h-72 rounded-panel lg:col-span-4" />
        </div>
      </div>
    </div>
  );
}
