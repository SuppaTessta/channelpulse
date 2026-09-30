// GET /api/brief/weeks and /api/brief?week= : the Weekly Channel & Quality Brief. Every stated number is a fact
// with the query behind it, and the API re-runs those queries before it serves the brief (the numbers check).

export type BriefFact = { label: string; kind: string; metric: string | null; value: unknown; display: string; sql: string | null; source: string | null };
export type BriefSentence = { text: string; facts: string[] };
export type Brief = {
  week: { start: string; end: string };
  as_of: string;
  provisional: boolean;
  status: "verified" | "blocked";
  sections: { title: string; sentences: BriefSentence[] }[];
  facts: Record<string, BriefFact>;
  check: { queries_rechecked: number; problems: unknown[] };
  narration: { by: "model" | "template"; model: string | null; blocked: unknown[] };
};
export type BriefWeeks = { weeks: string[] };

/** Footnote numbers in order of first citation, so the markers read 1, 2, 3 down the page. */
export function footnoteNumbers(brief: Brief): Map<string, number> {
  const numbers = new Map<string, number>();
  for (const s of brief.sections) for (const sentence of s.sentences) for (const id of sentence.facts) if (brief.facts[id] && !numbers.has(id)) numbers.set(id, numbers.size + 1);
  return numbers;
}

/** A problem or a blocked reason may arrive as text or as a small object; either way it reads as one line. */
export const reasonText = (v: unknown): string =>
  typeof v === "string" ? v : v && typeof v === "object" ? Object.entries(v).map(([k, x]) => `${k}: ${typeof x === "string" ? x : JSON.stringify(x)}`).join(", ") : String(v);
