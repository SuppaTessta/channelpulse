import type { ReactNode } from "react";
import { CopyButton } from "./copy-button";
import { cx } from "./ui";

const TOKENS =
  /('(?:[^']|'')*')|\b(SELECT|FROM|WHERE|GROUP BY|ORDER BY|LIMIT|AS|AND|OR|NOT|IN|ON|LEFT OUTER JOIN|FULL OUTER JOIN|INNER JOIN|CROSS JOIN|JOIN|CASE|WHEN|THEN|ELSE|END|WITH|BETWEEN|IS|NULL|DISTINCT|DESC|ASC|OVER|PARTITION BY|UNION ALL|HAVING|TRUE|FALSE)\b/gi;

/** Compiled SQL, verbatim, with keywords and string literals picked out. Text nodes only: never innerHTML. */
export function SqlBlock({ sql, label = "Copy SQL", className }: { sql: string; label?: string; className?: string }) {
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of sql.matchAll(TOKENS)) {
    if (m.index > last) out.push(sql.slice(last, m.index));
    out.push(
      <span key={m.index} className={m[1] ? "text-adhoc" : "font-medium text-accent"}>
        {m[0]}
      </span>,
    );
    last = m.index + m[0].length;
  }
  out.push(sql.slice(last));
  return (
    <div className={cx("overflow-hidden rounded-control border border-line bg-sunken", className)}>
      <div className="flex items-center justify-between border-b border-line py-1 pr-1 pl-3">
        <span className="text-xs text-subtle">SQL</span>
        <CopyButton text={sql} label={label} />
      </div>
      <pre className="max-h-[420px] overflow-auto p-3 font-mono text-[12.5px]/5 text-ink">
        <code>{out}</code>
      </pre>
    </div>
  );
}
