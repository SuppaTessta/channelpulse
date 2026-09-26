import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // *.dev.tsx routes (the Ask fixture story) exist only under `next dev`; production builds never include them.
  // `next dev` builds into its own folder, so a `next build` (make lint, CI replays) can't swap files under a running
  // dev server (decisions D28).
  distDir: process.env.NODE_ENV === "production" ? ".next" : ".next-dev",
  pageExtensions: process.env.NODE_ENV === "production" ? ["tsx", "ts"] : ["dev.tsx", "tsx", "ts"],
};

export default nextConfig;
