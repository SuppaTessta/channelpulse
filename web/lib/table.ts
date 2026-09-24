// Helpers for the API's {columns, rows} tables. No React or server imports: client components use these too.

export type Table = { columns: string[]; rows: unknown[][] };

export const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
export const str = (v: unknown): string | null => (v == null ? null : String(v));

export function records(table: Table): Record<string, unknown>[] {
  return table.rows.map((row) => Object.fromEntries(table.columns.map((c, i) => [c, row[i]])));
}

/** One column's values, or null when the table has no such column. */
export function column(table: Table, name: string): unknown[] | null {
  const i = table.columns.indexOf(name);
  return i < 0 ? null : table.rows.map((row) => row[i]);
}

/** The single value of an ungrouped query (one row, one column). */
export function scalar(table: Table, name: string): number | null {
  const values = column(table, name);
  return values && values.length ? num(values[0]) : null;
}
