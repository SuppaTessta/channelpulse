// Shared by server and client code.

/** The API's default port is 8000 (`make api`); override with NEXT_PUBLIC_API_URL, e.g. in web/.env.local. */
export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

/** A visitor's Anthropic key is only ever sent over HTTPS, or to an API on this machine. */
export function keySafe(apiUrl: string) {
  const { protocol, hostname } = new URL(apiUrl);
  return protocol === "https:" || hostname === "localhost" || hostname === "127.0.0.1";
}
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
