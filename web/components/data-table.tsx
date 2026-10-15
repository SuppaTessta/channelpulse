import type { ReactNode } from "react";
import { cx } from "./ui";

type TableColumn = { label: string; numeric?: boolean };

/** The table twin of a chart (and the plain table views): semantic, captioned, numbers right-aligned. */
export function DataTable({
  caption,
  columns,
  rows,
  maxHeight = "max-h-[360px]",
  className,
}: {
  caption: string;
  columns: TableColumn[];
  rows: ReactNode[][];
  maxHeight?: string;
  className?: string;
}) {
  return (
    <div className={cx("overflow-auto rounded-control border border-line", maxHeight, className)}>
      <table className="w-full border-collapse text-[13px]">
        <caption className="sr-only">{caption}</caption>
        <thead className="sticky top-0 bg-sunken">
          <tr>
            {columns.map((c) => (
              <th
                key={c.label}
                scope="col"
                className={cx("border-b border-line px-3 py-2 text-[11px] font-semibold tracking-[0.08em] whitespace-nowrap text-subtle uppercase", c.numeric ? "text-right" : "text-left")}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-line transition-colors duration-150 last:border-0 hover:bg-hover hover:shadow-[inset_3px_0_0_var(--accent)]">
              {row.map((cell, j) => (
                <td key={j} className={cx("px-3 py-1.5 text-ink", columns[j]?.numeric ? "text-right whitespace-nowrap" : "text-left")}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
