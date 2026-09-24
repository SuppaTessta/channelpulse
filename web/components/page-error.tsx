import type { ApiError } from "@/lib/api";
import { ErrorState } from "./states";

/** When even the as-of date can't be read, no query on the page can run: say so once, plainly. */
export function PageError({ error }: { error: ApiError }) {
  return (
    <section aria-label="Data unavailable" className="rounded-panel border border-line bg-surface px-4 md:px-6">
      <ErrorState error={error} />
    </section>
  );
}
