import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import type { Metadata, Viewport } from "next";
import { Rail } from "@/components/nav";
import { Providers } from "@/components/providers";
import { THEME_SCRIPT } from "@/components/theme-toggle";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "ChannelPulse", template: "%s · ChannelPulse" },
  description: "Governed, evaluated analytics on a synthetic manufacturer's channel, quality and collections data.",
};

export const viewport: Viewport = {
  themeColor: "#070b14",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en-IN" data-theme="dark" suppressHydrationWarning className={`${GeistSans.variable} ${GeistMono.variable}`}>
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
      </body>
    </html>
  );
}
