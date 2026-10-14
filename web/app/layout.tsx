import type { Metadata, Viewport } from "next";
import { JetBrains_Mono, Newsreader, Plus_Jakarta_Sans } from "next/font/google";
import { Rail } from "@/components/nav";
import { Providers } from "@/components/providers";
import { THEME_SCRIPT } from "@/components/theme-toggle";
import "./globals.css";

// latin-ext carries the rupee sign (U+20B9); the plain latin subset doesn't.
const display = Newsreader({ subsets: ["latin", "latin-ext"], axes: ["opsz"], variable: "--font-newsreader", display: "swap" });
const sans = Plus_Jakarta_Sans({ subsets: ["latin", "latin-ext"], variable: "--font-jakarta", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jetbrains", display: "swap", preload: false });

export const metadata: Metadata = {
  title: { default: "ChannelPulse", template: "%s · ChannelPulse" },
  description: "Governed, evaluated analytics on a synthetic manufacturer's channel, quality and collections data.",
};

export const viewport: Viewport = {
  themeColor: "#070b14",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en-IN" data-theme="dark" suppressHydrationWarning className={`${display.variable} ${sans.variable} ${mono.variable}`}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="min-h-dvh bg-canvas text-ink">
        <a
          href="#main"
          className="sr-only z-50 rounded-control bg-accent px-3 py-2 text-sm font-medium text-on-accent focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
        >
          Skip to content
        </a>
        <Providers>
          <Rail />
          <main id="main" tabIndex={-1} className="min-h-dvh outline-none md:pl-[72px] wide:pl-[232px] print:pl-0">
            {children}
          </main>
        </Providers>
        <div aria-hidden className="cp-grain print:hidden" />
      </body>
    </html>
  );
}
