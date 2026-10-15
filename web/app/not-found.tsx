import Link from "next/link";
import { Illustration } from "@/components/illustration";
import { buttonClass, TYPE } from "@/components/ui";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-[1440px] px-4 py-10 md:px-6">
      <section className="flex max-w-[68ch] flex-col items-start rounded-panel border border-line bg-surface p-6 shadow-highlight cp-reveal">
        <Illustration kind="lost" className="mb-3" />
        <h1 className={TYPE.stateTitle}>There&apos;s no page at this address</h1>
        <p className="mt-2 text-sm text-muted">Pick a page from the navigation, or start at the executive view.</p>
        <Link href="/" className={`${buttonClass("secondary", "sm")} mt-3`}>
          Go to Executive KPIs
        </Link>
      </section>
    </div>
  );
}
