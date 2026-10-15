import { Skeleton } from "@/components/ui";

/** Shown while a page's first queries (the as-of date) resolve. Shaped like the page: bar, filters, strip, panels. */
export default function Loading() {
  return (
    <div aria-busy="true">
      <span className="sr-only">Loading the page</span>
      <div className="border-b border-line">
        <div className="mx-auto flex h-14 max-w-[1440px] items-center justify-between px-4 md:h-[72px] md:px-6 xl:h-[88px]">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="hidden h-8 w-72 md:block" />
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
