"use client";

import { ChatCenteredText, GridFour, List, ListMagnifyingGlass, Newspaper, PresentationChart, Pulse, Storefront, X, type Icon } from "@phosphor-icons/react";
import * as Dialog from "@radix-ui/react-dialog";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { ThemeToggle } from "./theme-toggle";
import { buttonClass, cx, ICON } from "./ui";

type Page = { href: string; label: string; title: string; icon: Icon };

/**
 * Every page, grouped by job (DESIGN.md, navigation). A new page is one entry in its group; a new job is a new group.
 * `label` is the short rail caption, `title` the page's own h1.
 */
const NAV: { group: string; pages: Page[] }[] = [
  {
    group: "Dashboards",
    pages: [
      { href: "/", label: "KPIs", title: "Executive KPIs", icon: PresentationChart },
      { href: "/distributors", label: "Distributors", title: "Distributor 360", icon: Storefront },
      { href: "/quality", label: "Quality", title: "Batch cohort heatmap", icon: GridFour },
    ],
  },
  {
    group: "Analyst",
    pages: [
      { href: "/ask", label: "Ask", title: "Ask ChannelPulse", icon: ChatCenteredText },
      { href: "/brief", label: "Brief", title: "Weekly Brief", icon: Newspaper },
    ],
  },
  {
    group: "Admin",
    pages: [{ href: "/traces", label: "Traces", title: "Agent traces", icon: ListMagnifyingGlass }],
  },
];

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

function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <span className="flex min-w-0 items-center gap-2.5">
      <span className="flex size-8 shrink-0 items-center justify-center rounded-control bg-accent text-on-accent shadow-highlight">
        <Pulse size={20} weight="bold" aria-hidden />
      </span>
      <span className={cx("min-w-0 flex-col leading-tight", compact ? "flex" : "hidden wide:flex")}>
        <span className="text-[14px] font-semibold tracking-[-0.01em] text-ink">ChannelPulse</span>
        <span className="truncate text-[11px] text-subtle">Gangasagar Polymers</span>
      </span>
    </span>
  );
}

function RailLinks({ query }: { query: string }) {
  const pathname = usePathname();
  return (
    <div className="flex flex-col gap-3 px-2 wide:gap-5 wide:px-3">
      {NAV.map(({ group, pages }, g) => (
        <div key={group} className="flex flex-col gap-1">
          {/* Below 1440px the group name gives way to a hairline, so the rail stays 72px wide. */}
          <p className="hidden px-2.5 pb-1 text-[11px] font-medium text-subtle wide:block">{group}</p>
          {g > 0 ? <hr aria-hidden className="mx-3 mb-2 wide:hidden" /> : null}
          <ul className="flex flex-col gap-0.5">
            {pages.map(({ href, label, title, icon: Icon }) => {
              const active = isActive(pathname, href);
              return (
                <li key={href}>
                  <Link
                    href={`${href}${query}`}
                    aria-current={active ? "page" : undefined}
                    title={title}
                    className={cx(
                      "flex h-14 flex-col items-center justify-center gap-1 rounded-control text-[11px] font-medium transition-colors duration-150 ease-out",
                      "wide:h-9 wide:flex-row wide:justify-start wide:gap-2.5 wide:px-2.5 wide:text-[13px]",
                      active ? "bg-accent-soft text-ink" : "text-muted hover:bg-hover hover:text-ink",
                    )}
                  >
                    <Icon size={20} {...ICON} weight={active ? "regular" : "light"} className={cx("shrink-0", active && "text-accent")} aria-hidden />
                    <span className="wide:hidden">{label}</span>
                    <span className="hidden truncate wide:inline">{title}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </div>
  );
}

function RailLinksWithQuery() {
  return <RailLinks query={useSharedQuery()} />;
}

/** The rail from 768px: 72px of icons and captions, opening into a labelled, grouped sidebar from 1440px. */
export function Rail() {
  return (
    <nav
      aria-label="Pages"
      className="fixed inset-y-0 left-0 z-30 hidden w-[72px] flex-col gap-5 border-r border-line bg-canvas py-3 md:flex wide:w-[232px] wide:py-4 print:hidden"
    >
      <Link href="/" className="mx-auto flex rounded-control p-1 wide:mx-3 wide:px-2" aria-label="ChannelPulse home">
        <Brand />
      </Link>
      <Suspense fallback={<RailLinks query="" />}>
        <RailLinksWithQuery />
      </Suspense>
      <div className="mt-auto flex flex-col gap-3">
        <div className="wide:hidden">
          <ThemeToggle variant="rail" />
        </div>
        <div className="hidden wide:block">
          <ThemeToggle variant="sidebar" />
        </div>
        <p className="hidden px-5 text-[11px]/4 text-subtle wide:block">Synthetic data for a fictional manufacturer. Every figure opens to its definition and the SQL behind it.</p>
      </div>
    </nav>
  );
}

function SheetLinks({ onNavigate }: { onNavigate: () => void }) {
  const pathname = usePathname();
  const query = useSharedQuery();
  return (
    <div className="flex flex-col gap-4">
      {NAV.map(({ group, pages }) => (
        <div key={group}>
          <p className="px-3 pb-1 text-xs font-medium text-subtle">{group}</p>
          <ul className="flex flex-col gap-1">
            {pages.map(({ href, title, icon: Icon }) => {
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
        </div>
      ))}
    </div>
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
          <div className="mb-4 flex items-center justify-between">
            <Dialog.Title asChild>
              <div>
                <Brand compact />
              </div>
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
