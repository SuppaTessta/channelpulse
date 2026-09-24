import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import type { Metadata, Viewport } from "next";
import { Rail } from "@/components/nav";
import { Providers } from "@/components/providers";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "ChannelPulse", template: "%s · ChannelPulse" },
  description: "Governed, evaluated analytics on a synthetic manufacturer's channel, quality and collections data.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f4f5f7" },
    { media: "(prefers-color-scheme: dark)", color: "#0e0f11" },
  ],
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en-IN" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body className="min-h-dvh bg-canvas text-ink">
        <a
          href="#main"
          className="sr-only z-50 rounded-control bg-accent px-3 py-2 text-sm font-medium text-on-accent focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
        >
          Skip to content
        </a>
        <Providers>
          <Rail />
          <main id="main" tabIndex={-1} className="min-h-dvh outline-none md:pl-[88px]">
            {children}
          </main>
        </Providers>
      </body>
    </html>
  );
}
