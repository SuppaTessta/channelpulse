import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // `next dev` builds into its own folder, so a `next build` (make lint, CI replays) can't swap files under a running
  // dev server (decisions D28).
  distDir: process.env.NODE_ENV === "production" ? ".next" : ".next-dev",
};

export default nextConfig;
