// Shared by server and client code.

/** On this machine the API runs on 8010 (port 8000 belongs to another project). Override with NEXT_PUBLIC_API_URL. */
export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8010").replace(/\/+$/, "");

/** The region claims the API accepts in X-Demo-Region (api/app/guardrails/region.py). No endpoint lists them. */
export const REGIONS = ["South Bengal", "North Bengal & Sikkim", "Assam", "North East", "Bihar & Jharkhand", "Odisha"] as const;
export type Region = "ALL" | (typeof REGIONS)[number];

export const regionSlug = (region: Region) =>
  region.toLowerCase().replace(/&/g, " ").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

/** A URL value (slug or name, any case) to a claim; anything unrecognised is the public ALL claim. */
export function parseRegion(value: string | null | undefined): Region {
  if (!value) return "ALL";
  const wanted = value.trim().toLowerCase();
  return REGIONS.find((r) => r.toLowerCase() === wanted || regionSlug(r) === wanted) ?? "ALL";
}

export const regionName = (region: Region) => (region === "ALL" ? "All regions" : region);
