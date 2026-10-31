import type { NextConfig } from "next";
import { API_URL } from "./lib/config";

// Production builds only: `next dev` needs eval. connect-src and img-src are what keep a visitor's Anthropic key on
// this page and the API: page code can send nothing anywhere else. The API's origin is baked in at build time, like
// NEXT_PUBLIC_API_URL itself.
// ponytail: 'unsafe-inline' scripts, because the App Router and the theme script inline theirs; a nonce CSP would need
// middleware and dynamic rendering on every page.
const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  `connect-src 'self' ${new URL(API_URL).origin}`,
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

const SECURITY_HEADERS = [
  { key: "Content-Security-Policy", value: CSP },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
];

const nextConfig: NextConfig = {
  // `next dev` builds into its own folder, so a `next build` (make lint, CI replays) can't swap files under a running
  // dev server (decisions D28).
  distDir: process.env.NODE_ENV === "production" ? ".next" : ".next-dev",
  headers: async () => (process.env.NODE_ENV === "production" ? [{ source: "/:path*", headers: SECURITY_HEADERS }] : []),
};

export default nextConfig;
