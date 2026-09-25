import Link from "next/link";
import { buttonClass } from "@/components/ui";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-[1440px] px-4 py-10 md:px-6">
      <section className="max-w-[68ch] rounded-panel border border-line bg-surface p-5">
        <h1 className="text-[15px]/6 font-semibold text-ink">There&apos;s no page at this address</h1>
        <p className="mt-1 text-sm text-muted">The dashboard has four pages. Pick one from the rail, or start at the executive view.</p>
        <Link href="/" className={`${buttonClass("secondary", "sm")} mt-3`}>
          Go to Executive KPIs
        </Link>
      </section>
    </div>
  );
}
