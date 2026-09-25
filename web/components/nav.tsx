"use client";

import { ChatCenteredText, GridFour, List, PresentationChart, Pulse, Storefront, X } from "@phosphor-icons/react";
import * as Dialog from "@radix-ui/react-dialog";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { buttonClass, cx, ICON } from "./ui";

const PAGES = [
  { href: "/", label: "KPIs", title: "Executive KPIs", icon: PresentationChart },
  { href: "/distributors", label: "Distributors", title: "Distributor 360", icon: Storefront },
  { href: "/quality", label: "Quality", title: "Batch cohort heatmap", icon: GridFour },
  { href: "/ask", label: "Ask", title: "Ask ChannelPulse", icon: ChatCenteredText },
] as const;

/** Filters that follow the viewer from page to page. */
const SHARED = ["region", "from", "to"];

const isActive = (pathname: string, href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));

function useSharedQuery(): string {
  const params = useSearchParams();
  const shared = new URLSearchParams();
  for (const key of SHARED) {
    const value = params.get(key);
    if (value) shared.set(key, value);
  }
  const qs = shared.toString();
  return qs ? `?${qs}` : "";
}

function RailLinks({ query }: { query: string }) {
  const pathname = usePathname();
  return (
    <ul className="flex flex-col gap-1 px-2">
      {PAGES.map(({ href, label, title, icon: Icon }) => {
        const active = isActive(pathname, href);
        return (
          <li key={href}>
            <Link
              href={`${href}${query}`}
              aria-current={active ? "page" : undefined}
              title={title}
              className={cx(
                "group flex h-14 flex-col items-center justify-center gap-1 rounded-control text-xs font-medium transition-colors duration-150 ease-out",
                active ? "bg-accent-soft text-ink" : "text-muted hover:bg-hover hover:text-ink",
              )}
            >
              <Icon size={22} {...ICON} className={active ? "text-accent" : undefined} aria-hidden />
              {label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function RailLinksWithQuery() {
  return <RailLinks query={useSharedQuery()} />;
}

export function Rail() {
  return (
    <nav aria-label="Pages" className="fixed inset-y-0 left-0 z-30 hidden w-[88px] flex-col gap-4 border-r border-line bg-canvas py-3 md:flex">
      <Link href="/" className="mx-auto flex size-10 items-center justify-center rounded-control text-accent hover:bg-hover" aria-label="ChannelPulse home">
        <Pulse size={26} {...ICON} aria-hidden />
      </Link>
      <Suspense fallback={<RailLinks query="" />}>
        <RailLinksWithQuery />
      </Suspense>
    </nav>
  );
}

function SheetLinks({ onNavigate }: { onNavigate: () => void }) {
  const pathname = usePathname();
  const query = useSharedQuery();
  return (
    <ul className="flex flex-col gap-1">
      {PAGES.map(({ href, title, icon: Icon }) => {
        const active = isActive(pathname, href);
        return (
          <li key={href}>
            <Link
              href={`${href}${query}`}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={cx(
                "flex h-12 items-center gap-3 rounded-control px-3 text-[15px] font-medium",
                active ? "bg-accent-soft text-ink" : "text-muted hover:bg-hover hover:text-ink",
              )}
            >
              <Icon size={22} {...ICON} className={active ? "text-accent" : undefined} aria-hidden />
              {title}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

/** Below 768px the rail becomes a sheet that drops from the top. */
export function MobileNav() {
  const [open, setOpen] = useState(false);
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger className={cx(buttonClass("ghost", "icon"), "-ml-2 md:hidden")} aria-label="Open page menu">
        <List size={22} {...ICON} aria-hidden />
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="cp-fade fixed inset-0 z-40 bg-[rgb(10_12_14/0.4)] md:hidden" />
        <Dialog.Content className="cp-drop fixed inset-x-0 top-0 z-50 border-b border-line bg-raised px-4 pt-3 pb-5 shadow-raised md:hidden">
          <div className="mb-3 flex items-center justify-between">
            <Dialog.Title className="flex items-center gap-2 text-[15px] font-semibold text-ink">
              <Pulse size={22} {...ICON} className="text-accent" aria-hidden />
              ChannelPulse
            </Dialog.Title>
            <Dialog.Close className={buttonClass("ghost", "icon")} aria-label="Close page menu">
              <X size={20} {...ICON} aria-hidden />
            </Dialog.Close>
          </div>
          <Dialog.Description className="sr-only">Go to another page of the dashboard.</Dialog.Description>
          <Suspense fallback={null}>
            <SheetLinks onNavigate={() => setOpen(false)} />
          </Suspense>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
