import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ChannelPulse",
  description: "Governed, evaluated AI analytics on a synthetic manufacturer's channel data.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
