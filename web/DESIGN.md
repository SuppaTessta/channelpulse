# ChannelPulse dashboard: design direction ("Monsoon Editorial")

**Design read:** a data-dense B2B analytics product for technical reviewers, set like a premium financial paper read at night. The numbers and their provenance stay the hero; motion, light and type make them feel instrument-grade rather than flat (decisions D54).

**Dials:** variance 6, motion 7, density 7.

The approach takes the design skills' discipline, not their landing-page mechanics:
- *impeccable* and *design-taste-frontend*: anti-default rules, one accent plus one warm second, one radius scale, no eyebrows, no gradient text.
- *high-end-visual-design*: the light Phosphor line, light carrying depth, the tray-and-plate frame for the one elevated thing on a page.
- *data:build-dashboard*: the layout principle only. Every dashboard page reads KPI band, primary chart, secondary charts, detail table, with filters in the header.
- *dataviz*: the chart palettes are computed and validated, never eyeballed.

Hero sections, scroll reveals and marketing copy don't apply to a dashboard and aren't used.

## Foundations
- **Stack:** Next.js 15 App Router, Tailwind v4 (`@tailwindcss/postcss`), Radix primitives for Select, Tabs, Tooltip, Popover and Dialog, Phosphor icons at one stroke weight (light; the active nav icon steps to regular), and Observable Plot for charts. No component kit, and the redesign added no dependency.
- **Type** (`TYPE` in `components/ui.tsx`; every family has tabular figures and the ₹ sign, checked in the font files):
  - **Newsreader** (display, optical size axis) for page titles (40px, 32px on phones), panel titles (20px), KPI and headline figures (40px), state titles, Ask questions and answers, and the Weekly Brief's headings and prose.
  - **Plus Jakarta Sans** for everything else: navigation, labels, controls, tables (13px), body (14px).
  - **JetBrains Mono** for SQL, metric names, IDs and trace ids.
  - Labels stay sentence case. Tiny uppercase tracking is used only for navigation group names and table column heads.
- **Figures as readouts** (`Figure`): the digits carry the weight, and the currency sign (₹ or $) and the unit step back, smaller and muted. "₹226.1 cr" reads as 226.1 first. A figure with `animate` counts up from zero on first show and from the old value to the new one on a change; the server renders the final text, and the last frame restores it exactly.
- **Two editions** from one set of semantic tokens in `app/globals.css`:
  - **Dark (default), Monsoon Night:** canvas `#070b14`, panels `#0d1422`, raised `#131b2c`, ink `#e9edf5`, accent teal `#2dd4bf`, second accent marigold `#f5a524`.
  - **Light, warm paper:** canvas `#f6f3ec`, panels `#fffdf8`, ink `#15171c`, accent `#0b6e72`, marigold darkened to `#8f5b00` for text contrast.
  - The choice is a toggle at the foot of the rail, remembered in `localStorage` (`cp-theme`) and applied by a script before first paint, so the page never flashes the wrong edition. The switch is a circular reveal from the toggle (View Transitions). Print always uses the light values.
- **Surfaces** step `canvas < sunken < surface < raised`: `canvas` is the page; `sunken` is trays (segmented controls, table headers, the SQL block, the answer and drill-down trays, skeletons); `surface` is panels; `raised` is popovers, drawers, the lifted segment and the plates. `hover` is the pointer tint only.
- **Colour roles:** teal is the accent (primary actions, focus, the active page, the governed state); marigold is the warm second (the second chart series, the hatch, the aurora). Status colours are semantic: governed (accent), ad-hoc (amber), refused (neutral surface, rose edge), needs clarification (neutral surface, grey edge), plus good and danger for deltas and flags. Colour never carries meaning alone: deltas carry a sign and an arrow, verdicts a check or a cross, flags text.
- **Chart palettes** (dataviz method): one hue order in both editions (teal, marigold, pink, blue, green, violet, rose, cyan), each edition stepped into its lightness band and validated against its chart surface. Worst adjacent pair: CVD ΔE 14.0 and normal vision 22.5 in light, 12.4 and 21.0 in dark. The heatmap uses a single-hue sequential teal scale.
- **Shape:** one radius scale. Controls 8px, panels and the sheet 12px, drawers 16px on the leading edge, badges full pill. Trays are concentric with what they hold (a 12px plate in a 4px tray is 16px); chart marks keep 2–4px.
- **Depth and light:** borders and light carry depth; shadows appear only on raised layers. Panels carry a faint inner top highlight. Floating layers (tooltips, selects, the date popover, chart tooltips) and drawers are glass: translucent raised surface, a stronger hairline, background blur. Dark mode adds glow: the active nav marker, the open select, the selected heatmap cell, the governed answer plate (teal) and the ad-hoc plate (amber), and every chart line, which glows in its own series colour.
- **Graphics:**
  - **Aurora:** a slow-drifting field of blurred radial gradients (teal, deep blue, a touch of marigold) behind the page header only; a faint watercolour wash in light.
  - **Grain:** a fixed SVG-noise layer over the canvas (3.5% dark, 5% light), `pointer-events: none`.
  - **Ruled sheet:** panels sit in a grid divided by 1px hairlines, like a newspaper page, not floating cards. The hovered panel catches a soft teal spotlight that follows the pointer.
  - **Brand mark:** a pulse line riding a river curve (Gangasagar, where the river meets the sea), which draws itself on first load.
  - **Illustrated states:** small line drawings for empty, error, waking-up and 404, in the accent colour, never carrying meaning alone.
- **Browser surfaces:** caret, `accent-color` (checkboxes, date fields), thin scrollbars and text selection all come from the palette.

## Motion
One easing for entrances, `--ease-out-expo` (`cubic-bezier(0.16, 1, 0.3, 1)`); state changes use `--ease-out`.

| Moment | What moves |
|---|---|
| Page load | Header, KPI band and panels rise 8px and fade in, staggered 60ms apart. The brand mark draws. |
| KPI band | Figures count up (900ms). Sparklines wipe in left to right, 80ms apart per tile, over a fading fill; the latest point lands, pings once, then breathes. |
| Charts, on a data change | Lines trace in (900ms); bars grow from the baseline, 45ms apart; areas, dots, labels and the hatched provisional band fade in. A redraw for a new width doesn't animate. |
| Bar lists and heatmap | Bars grow from their zero edge, row by row; heatmap cells fade in by column, 30ms apart. |
| Filters | The page keeps its current render, dimmed, while it refetches ("Updating"); figures then count from old values to new. |
| Floating layers | Popovers and selects drop in (200ms); drawers slide from the right (420ms); overlays fade. |
| Hover | Panels catch the pointer's spotlight; the primary button's sheen sweeps across it. |
| Loading | Skeletons shimmer slowly. |
| Live states | The "data as of" dot and the brief's numbers-check dot breathe. |
| Theme switch | A circular reveal from the toggle. |

`prefers-reduced-motion` zeroes every duration and delay and stops every loop: figures show their final value at once and nothing moves (tested in `e2e/redesign.spec.ts`).

## Layout
- **Navigation** is one config, `NAV` in `components/nav.tsx`, grouped by job:
  - **Dashboards:** Executive KPIs, Distributor 360, Batch cohort heatmap.
  - **Analyst:** Ask ChannelPulse, Weekly Brief.
  - **Admin:** Agent traces.
  - A new page is one entry in its group, and a new job is a new group. Rail, sidebar and mobile sheet all render from the same list, and the current page wears the same active treatment (`NAV_ACTIVE`) as the current Ask question.
- **Rail and sidebar:**
  - From 768px the rail is 72px of icons with short captions, and groups are split by a hairline. The theme toggle sits at its foot.
  - From 1440px (`wide:`) it opens into a 232px sidebar with the brand mark, the wordmark, micro-caps group names, full page titles, the toggle and a one-line synthetic-data note.
  - Below 768px it becomes a sheet that drops from the top, with the toggle under the pages.
- **Two-tier header:**
  - The upper tier, sticky from 768px, holds the page title (with a back link on detail pages; long titles wrap to two balanced lines) and a glass pill with the **"Viewing as" region claim** (the RLS stub, sent as `X-Demo-Region`) and **data as-of** with a provisional-days note (decisions D12). The as-of opens its own definition and SQL. From 1280px the pill sits beside the title; below that it takes its own row.
  - The lower tier is the page's filter row: date range, plant, product, failure mode.
- A 12-column grid, `max-w-[1440px]`. Below 768px every multi-column row collapses to one column.
- **The KPI band** is one ruled row of five from 1280px, three and two below that, one column on phones: label (with a definition tooltip), readout figure, change chip with arrow and comparison value, sparkline, then a footer row with the tile's note and its SQL button.
- **Long lists page themselves:** the distributor list draws 50 rows, then Show more or Show all, so no page runs to thousands of pixels.
- **Navigation that Next never applies** (a Next 15.5 stall) falls back to a full page load after 12 seconds (decisions D53).

## Page by page
- **Executive KPIs:** the KPI band of five governed metrics, then sales (primary chart), channel stock, DSO and the region stock-out and overstock panel.
- **Distributor 360:** four headline figures from the list query (count, at risk now, primary sales, top-10 share), then the sortable, searchable, paged table.
  - At phone width, region and tier fold under the name.
  - Each distributor page has profile facts (an at-risk badge with a dot when flagged now), then the health score as a counting serif figure with its five components, sell-in and sell-out, stock, collections (receivables as readouts), field visits and schemes.
- **Batch cohort heatmap:** the heatmap is the primary view. Beside it sit the drill-down (a tray and a glass plate) and the resin-lot flags, each led by the scan's own measure, the ratio to the peer rate. That ratio is in the danger colour only while the lot is flagged now.
- **Ask ChannelPulse:**
  - Replay mode opens with the notice and the recording's scorecard (scored correct, traps handled, governed answers) as counting figures, counted from the answers shown.
  - The question list scrolls on its own beside the pinned answer from 1024px, with category names pinned and a per-category tally.
  - The answer is a glass plate lit by its label: teal for governed, amber for ad hoc. The question and the answer are set in Newsreader.
- **Weekly Brief** reads like a printed one-page report: night paper in dark, real paper in light, one 800px column.
  - A week picker and a Print button sit in the filter row.
  - The paper shows the title, the week, the as-of and whether the week is provisional.
  - Next comes the numbers-check line: "Numbers check passed: N queries re-executed" on the accent tint with a breathing dot, or "Numbers check failed" on the danger tint with the problems listed and no sentences.
  - Then the narration note: the model's name, or "Written from the template" with any reasons the model's draft was set aside.
  - Then the sections in serif prose, and a numbered Sources list.
  - Every cited fact is a footnote marker after its sentence, kept with it. The marker opens that fact's label, value, metric, source and SQL.
  - Print drops the rail, header, aurora, grain, shadows and motion, and puts the paper on white with light ink.
- **Agent traces** (admin) follows the dashboard layout.
  - Filters sit in the header: label, provider, model, category and source (each with facet counts), plus a text search. All of them are kept in the URL, and a change resets paging and closes the drawer.
  - A totals band (traces, tokens in and out, median latency, estimated cost) comes next, with the label mix as a segmented bar that grows in, whose legend carries every count and share.
  - Then a sortable table of 50 rows, paged by URL offset. Times are fixed to IST, so server and browser render the same text.
  - A question opens the glass trace drawer (`?trace=`, so a trace is deep-linkable). The drawer shows the label badge (all four labels), the eval verdict, the measurements, the final SQL and each tool call with its input, SQL, rows, duration, error and the first 300 characters of output.
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
- Provisional data (inside the reporting horizon) is hatched on time-series charts and dashed on lines.

## Copy rules
Plain, specific, sentence case:
- no em-dashes;
- no filler verbs (elevate, seamless, unleash);
- no fake-precise numbers (every figure comes from the API, or is counted from what it returned);
- realistic Indian names only where data provides them;
- empty, loading and error states say what happened and what to do.

## Accessibility
- WCAG AA contrast in both editions: every text token clears 4.5:1 on every surface, checked by `e2e/redesign.spec.ts`.
- `prefers-reduced-motion` turns every animation off, figures included.
- Visible focus rings, a keyboard-reachable everything, and labelled icon buttons. Short triggers get a full accessible name that includes their visible text.
- Charts have text alternatives, such as a summary sentence and a data table toggle, and read point by point with the arrow keys.
- Touch targets are at least 40px on mobile; the brief's footnote markers widen theirs with an invisible hit area.
- A failed API call or render degrades one panel (`Panel`, a Suspense boundary around `PanelBoundary`), never the page.
