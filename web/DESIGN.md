# ChannelPulse dashboard: design direction

**Design read:** a data-dense B2B analytics product for technical reviewers. The visual language is calm and instrument-grade: the numbers and their provenance are the hero, not decoration.

**Dials:** variance 5, motion 3, density 7.

The approach takes the design skills' discipline, not their landing-page mechanics:
- *impeccable* and *design-taste-frontend*: anti-default rules, one accent, one radius scale, no eyebrows, no decorative dots.
- *high-end-visual-design*: the light Phosphor line, tinted shadows, the tray-and-plate frame for the one elevated thing on a page.
- *data:build-dashboard*: the layout principle only. Every dashboard page reads KPI strip, primary chart, secondary charts, detail table, with filters in the header.

Hero sections, scroll reveals and marketing copy don't apply to a dashboard and aren't used.

## Foundations
- **Stack:** Next.js 15 App Router, Tailwind v4 (`@tailwindcss/postcss`), Radix primitives for Select, Tabs, Tooltip, Popover and Dialog, Phosphor icons at one stroke weight (light; the active nav icon steps to regular), and Observable Plot for charts. No component kit.
- **Type:**
  - Geist for UI and Geist Mono for SQL, IDs and metric names, loaded via `next/font`.
  - Every figure uses `tabular-nums`.
  - Base size 14px for dense UI, 16px for prose (answers, empty states).
  - Page titles 20px semibold at -0.015em. Panel titles 14px semibold. Subtitles and captions 12px muted.
- **Figures as readouts** (`Figure` in `components/ui.tsx`): the digits carry the weight, and the currency sign and the unit step back (the rupee sign at 0.8em, units at 0.6em, both muted). "₹226.1 cr" reads as 226.1 first. KPI values are 28px on phones and 32px from 768px, at -0.03em.
- **Theme:** light and dark both, following `prefers-color-scheme`, from one set of semantic CSS tokens in `app/globals.css`. No pure black or white.
- **Surfaces** step `canvas < sunken < surface < raised`:
  - `canvas` is the page;
  - `sunken` is trays (segmented controls, table headers, the SQL block, the answer tray, skeletons);
  - `surface` is panels;
  - `raised` is popovers, drawers, the lifted segment and the answer plate.
  - `hover` is the pointer tint only.
- **Color:**
  - Neutral base: cool zinc.
  - **One accent:** a deep river teal, echoing Gangasagar, where the river meets the sea. It's used for primary actions, focus, the active page and the governed-metric state.
  - Status colours are semantic, not decorative: governed (accent), ad-hoc (amber), refused (neutral surface, rose edge), needs clarification (neutral surface, grey edge), plus good and danger for deltas and flags.
  - Chart palettes come from the dataviz skill: a validated categorical palette and a single-hue sequential scale for the heatmap. Colour is never the only carrier of meaning. Deltas carry a sign and an arrow, verdicts carry a check or a cross, and flags carry text.
- **Shape:** one radius scale. Controls 6px, panels 10px, the answer tray 14px (panel plus its 4px padding), badges full pill. Borders beat shadows. A shadow appears only where elevation carries hierarchy: the Ask answer, the batch drill-down, popovers and the definition drawer.
- **Depth details:** buttons and selects carry a 1px inner highlight (`shadow-highlight`). The chosen segment of a segmented control is lifted out of its sunken tray (`shadow-segment`).
- **Browser surfaces:** caret, `accent-color` (checkboxes, date fields), thin scrollbars and text selection all come from the palette.
- **Motion:** 150–200 ms state transitions on filter changes, disclosures, tooltips and the SQL caret. No scroll reveals and no loops. `prefers-reduced-motion` turns everything instant.

## Layout
- **Navigation** is one config, `NAV` in `components/nav.tsx`, grouped by job:
  - **Dashboards:** Executive KPIs, Distributor 360, Batch cohort heatmap.
  - **Analyst:** Ask ChannelPulse, Weekly Brief.
  - **Admin:** Agent traces.
  - A new page is one entry in its group, and a new job is a new group. Rail, sidebar and mobile sheet all render from the same list.
- **Rail and sidebar:**
  - From 768px the rail is 72px of icons with short captions, and groups are split by a hairline.
  - From 1440px (`wide:`) it opens into a 232px sidebar with the wordmark, the company name, group names, full page titles and a one-line synthetic-data note.
  - Below 768px it becomes a sheet that drops from the top.
- **Two-tier header:**
  - The upper tier, sticky from 768px, holds the page title (with a back link on detail pages), the **"Viewing as" region claim** selector (the RLS stub, sent as `X-Demo-Region`) and **data as-of** with a provisional-days note (decisions D12). The as-of opens its own definition and SQL.
  - The lower tier is the page's filter row: date range, plant, product, failure mode.
- A 12-column grid, `max-w-[1440px]`. Below 768px every multi-column row collapses to one column.
- **Panels** sit in a sheet divided by 1px rules (the gap shows the border colour through), not as floating cards.
- **KPI strips have no card boxes:** label (with a definition tooltip), readout figure, change with arrow and comparison value, sparkline, then a footer row with the tile's note and its SQL button.
- **Long lists page themselves:** the distributor list draws 50 rows, then Show more or Show all, so no page runs to thousands of pixels.

## Page by page
- **Executive KPIs:** a KPI strip of five governed metrics, then sales (primary chart), channel stock, DSO and the region stock-out and overstock panel.
- **Distributor 360:** four headline figures from the list query (count, at risk now, primary sales, top-10 share), then the sortable, searchable, paged table.
  - At phone width, region and tier fold under the name.
  - Each distributor page has profile facts, then health, sell-in and sell-out, stock, collections (receivables as readouts), field visits and schemes.
- **Batch cohort heatmap:** the heatmap is the primary view. Beside it sit the drill-down (a tray and plate) and the resin-lot flags, each led by the scan's own measure, the ratio to the peer rate. That ratio is in the danger colour only while the lot is flagged now.
- **Ask ChannelPulse:**
  - Replay mode opens with the notice and the recording's scorecard (scored correct, traps handled, governed answers), counted from the answers shown.
  - The question list scrolls on its own beside the pinned answer from 1024px, with category names pinned and a per-category tally.
- **Weekly Brief** reads like a printed one-page report: one 800px paper column on the canvas.
  - A week picker and a Print button sit in the filter row.
  - The paper shows the title, the week, the as-of and whether the week is provisional.
  - Next comes the numbers-check line: "Numbers check passed: N queries re-executed" on the accent tint, or "Numbers check failed" on the danger tint with the problems listed and no sentences.
  - Then the narration note: the model's name, or "Written from the template" with any reasons the model's draft was set aside.
  - Then the sections, and a numbered Sources list.
  - Every cited fact is a footnote marker after its sentence. The marker opens that fact's label, value, metric, source and SQL.
  - Print drops the rail and header and forces light ink on paper.
- **Agent traces** (admin) follows the dashboard layout.
  - Filters sit in the header: label, provider, model, category and source (each with facet counts), plus a text search. All of them are kept in the URL, and a change resets paging and closes the drawer.
  - A KPI strip (traces, tokens in and out, median latency, estimated cost) comes next, with the label mix as a segmented bar whose legend carries every count and share.
  - Then a sortable table of 50 rows, paged by URL offset. Times are fixed to IST, so server and browser render the same text.
  - A question opens the trace drawer (`?trace=`, so a trace is deep-linkable). The drawer shows the label badge (all four labels), the eval verdict, the measurements, the final SQL and each tool call with its input, SQL, rows, duration, error and the first 300 characters of output.
  - Live traces need `X-Admin-Token`. The dashboard server reads it from the server-only `CHANNELPULSE_ADMIN_TOKEN` and never sends it to the browser. Without the token, the page says it lists recorded eval traces only.

## Trust patterns (the brand story)
- Every number on every page can show **where it came from**:
  - Every chart panel ends in a **provenance row**: the governed metric names in mono beside a seal, and a "Definition · SQL" button.
  - The button opens the governed metric's definition and the exact compiled SQL, straight from `/api/metrics/query`.
  - KPI tiles carry a labelled "SQL" button ("Definition and SQL: Primary sales value").
- The Ask answer has five parts: the answer, a chart built from `chart_spec`, a data table, a **label badge**, and a footer band holding the confidence note, the collapsible SQL and the trace id.
- **The four answer labels:**
  - Governed metric: accent, seal check.
  - Ad-hoc SQL, verify: amber, seal warning, plus a callout to check the query.
  - Refused: neutral surface, rose edge, hand.
  - Needs clarification: neutral surface, grey edge, chat dots. It shows the analyst's question back and "Ask again with the reading you mean.".
  - Refusals and clarifications state no figures, and are shown plainly and politely as normal outcomes.
- Provisional data (inside the reporting horizon) is visibly marked on time-series charts.

## Copy rules
Plain, specific, sentence case:
- no em-dashes;
- no filler verbs (elevate, seamless, unleash);
- no fake-precise numbers (every figure comes from the API, or is counted from what it returned);
- realistic Indian names only where data provides them;
- empty, loading and error states say what happened and what to do.

## Accessibility
- WCAG AA contrast in both themes.
- Visible focus rings, a keyboard-reachable everything, and labelled icon buttons. Short triggers get a full accessible name that includes their visible text.
- Charts have text alternatives, such as a summary sentence and a data table toggle.
- Touch targets are at least 40px on mobile.
- A failed API call or render degrades one panel (`Panel`, a Suspense boundary around `PanelBoundary`), never the page.
