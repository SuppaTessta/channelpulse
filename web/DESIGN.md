# ChannelPulse dashboard: design direction

**Design read:** a data-dense B2B analytics product for technical reviewers. The visual language is calm and instrument-grade: the numbers and their provenance are the hero, not decoration.

**Dials:** variance 5, motion 3, density 7.

The approach follows the design skills: *ui-ux-pro-max* for the data-dense dashboard pattern, and *design-taste-frontend* for its anti-default rules. *design-taste-frontend* itself says dashboards are out of its scope, so its landing-page mechanics don't apply here.

## Foundations
- **Stack:** Next.js 15 App Router, Tailwind v4 (`@tailwindcss/postcss`), Radix primitives for Select, Tabs, Tooltip, Popover and Dialog, Phosphor icons at one stroke weight, and Observable Plot for charts. No component kit in its default state.
- **Type:**
  - Geist for UI and Geist Mono for SQL and IDs, loaded via `next/font`.
  - Every figure uses `tabular-nums`.
  - Base size 14px for dense UI, 16px for prose (answers, empty states).
- **Theme:** light and dark both, following `prefers-color-scheme`, from one set of semantic CSS tokens (`--surface`, `--surface-raised`, `--text`, `--text-muted`, `--border`, `--accent`, …). No pure black or white.
- **Color:**
  - Neutral base: cool zinc.
  - **One accent:** a deep river teal, echoing Gangasagar, where the river meets the sea. It's used for primary actions, focus and the governed-metric state.
  - Status colours are semantic, not decorative: governed (accent), ad-hoc (amber), refused (neutral with a rose edge), needs clarification (neutral with a grey edge), plus warning and danger.
  - Chart palettes come from the dataviz skill: a validated categorical palette and a single-hue sequential scale for the heatmap. Colour is never the only carrier of meaning.
- **Shape:** one radius scale. Controls 6px, panels 10px, badges full pill, applied everywhere. Borders beat shadows. Cards appear only where elevation carries hierarchy, such as the Ask answer and the batch drill-down.
- **Motion:** 150–200 ms state transitions on filter changes, disclosures and tooltips. No scroll reveals and no loops. `prefers-reduced-motion` turns everything instant.

## Layout
- **Shell:** a slim left rail with the 4 pages and a top bar holding the page title, the **"Viewing as" region claim** selector (the RLS stub, sent as `X-Demo-Region`), and **data as-of** with a provisional-days note (decisions D12).
- A 12-column grid, `max-w-[1440px]`. Below 768px every multi-column row collapses to one column, and the rail becomes a top sheet.
- **KPI strips have no card boxes:** value, delta, and a sparkline separated by 1px dividers. Each tile shows its metric's label and definition in a tooltip.

## Trust patterns (the brand story)
- Every number on every page can show **where it came from**: a "Definition · SQL" disclosure opens the governed metric's definition and the exact compiled SQL, straight from `/api/metrics/query`.
- The Ask panel's answer has five parts: the answer, a chart built from `chart_spec`, a data table, a **label badge** (Governed metric / Ad-hoc SQL, verify / Refused / Needs clarification), the confidence note, and a collapsible SQL block. Refusals are shown plainly and politely, not hidden; a clarifying question is shown the same way, as the analyst's question back to the user, with no figures.
- Provisional data (inside the reporting horizon) is visibly marked on time-series charts.

## Copy rules
Plain, specific, sentence case:
- no em-dashes;
- no filler verbs (elevate, seamless, unleash);
- no fake-precise numbers (every figure comes from the API);
- realistic Indian names only where data provides them;
- empty, loading and error states say what happened and what to do.

## Accessibility
- WCAG AA contrast in both themes.
- Visible focus rings, a keyboard-reachable everything, and labelled icon buttons.
- Charts have text alternatives, such as a summary sentence and a data table toggle.
- Touch targets are at least 40px on mobile.
