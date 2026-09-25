import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // *.dev.tsx routes (the Ask fixture story) exist only under `next dev`; production builds never include them.
  pageExtensions: process.env.NODE_ENV === "production" ? ["tsx", "ts"] : ["dev.tsx", "tsx", "ts"],
};

export default nextConfig;
