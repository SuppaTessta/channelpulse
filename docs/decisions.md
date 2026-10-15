# Decisions log

Places where the build plan was silent, ambiguous, or internally inconsistent, and what was decided.
Each entry names the plan text it touches. Entries marked **extends plan** add to the plan and should get the owner's sign-off.
The owner approved the recommended resolutions on 2026-09-24. They were reached through an independent spec-gap review and adversarial critique.

Anomaly specifics (dates, multipliers, which entities) are deliberately **not** recorded here. They live only in `generator/ground_truth.yaml`, the answer key.

## Raw schema

**D1. `installations.installer_id` (nullable FK → installers). Extends plan.**
The plan relies on the join path `warranty_claims → serial_units → installations → installers`, and `installer_claim_rate` needs units installed per installer as its denominator. The plan's `installations` table has no installer column, so neither was possible.
`warranty_claims.installer_id` is kept as the technician-recorded copy, and a dbt test asserts it matches `installations.installer_id` whenever both are set.

**D2. Durgapur runs one rotomoulded tank line (Line 2) alongside its pipe/CPVC extrusion (Line 1). Extends plan.**
The plan's plant list says "Durgapur (pipes/CPVC)", but elsewhere the plan needs serialised tank production at Durgapur. The plant list is described as narrative flavour, so it gives way.
`plants.plant_type` for Durgapur is `pipes_cpvc_and_tanks`.

**D3. Unit serialisation (QR serials) applies to tanks only. Extends plan.**
At the stated scale, serialising pipes and fittings would need about 40M rows against a 1.5–2.5M budget. This extends the plan's own rule that "serial is null for bulk/weight-sold pipe" to fittings and sanitaryware.
Consequences:
- `serial_units`, serial rows in `shipments`, `installations` and `warranty_claims` are all tank rows.
- Warranty claims are tank claims. `fitting_failure` means a tank's inlet/outlet fitting.
- Simulated physical volume is sized to the row budget. The ₹480 cr revenue figure is calibration only.

**D4. `raw.geo_pincodes` (pincode, district, state, region) reference table. Extends plan.**
The plan never maps a pincode to a district or region, yet it needs a district baseline (installer decoy), `dim_geo`, region-grain metrics and a region RLS claim. The generator writes this table and draws every pincode from it.
Region is the geo region of the pincode. Each sales rep's region must match their distributors' region (dbt test).
District and state names are real public geography. Pincodes are synthetic values inside real postal prefixes.

**D5. `raw.opening_channel_stock` (distributor_id, sku, qty, as_of_date). Extends plan.**
Days-of-stock is "cumulative primary − cumulative secondary", and there is no opening balance, so every distributor would start empty. The plan's example test, "secondary sales can't exceed opening stock + primary receipts", needs an opening stock.
"Primary shipped" is defined as `primary_invoice_lines.qty` on `primary_invoices.invoice_date`. `shipments` is the serial-level custody log. For non-serialised goods it holds one bulk row per dispatch, with a null serial.

**D6. Sanitaryware is traded, not manufactured.**
None of the three plants makes it. `primary_invoice_lines.batch_id` is nullable for sanitaryware lines only (dbt test), and sanitaryware is excluded from batch and claim cohorts.

**D7. Legacy installed base.**
Tanks made in the 12 months before month 1 exist in `production_batches` and `serial_units`, so warranty claims against them during the window have a valid serial. Their shipment history predates the warehouse and isn't included. This reads as the warehouse going live at month 1 with a migrated serial master.
Without it, claim counts would ramp up from zero for the first year and fake a trend.

**D8. Latent install date.**
The simulator gives every tank a true install date and applies all failure hazards against it. It writes `install_date` only for the ~70% that register.
- An `installations` row exists for every tank shipped in the window. Unregistered tanks carry null `install_date`, `pincode`, `registered_via` and `installer_id`.
- The cohort mart's in-service clock is defined in the dbt step.
- `claim_date >= install_date` is tested only where `install_date` is set.

## Channel mechanics and metric definitions

**D9. Scheme mechanics.**
- The `min_slab_units` slab is checked per invoice, on the lines in `applies_to_category`.
- The discount is taken on-invoice: `unit_price_inr = price × (1 − discount_pct)`.
- An invoice carries at most one scheme.

**D10. Channel metrics are computed in units, not value.**
Secondary value uses the current list price, while primary value uses historical, discounted prices. A value-based primary/secondary gap would therefore move with every price revision and scheme, regardless of channel behaviour. The health-score gap and all channel-stock logic use qty.

**D11. Registration calibration.**
About 30% of tanks never register (the plan's 30–40%). The plan's 90-day `warranty_registration_rate` therefore lands around 60–65% (the plan's 60–70%).

**D12. Secondary reporting.**
- A secondary row becomes visible once `reported_date ≤ as-of`, so the most recent weeks are always partly reported.
- Detectors and the health score use sale dates older than a completeness horizon (the p95 reporting lag). The dashboard marks the newest days as provisional.
- "Missing" reports are mostly late: skipped weeks get back-filled as catch-up records. Truly lost reports are capped at a tiny share, so implied channel stock doesn't drift upward forever.

**D13. Metric definitions settled now (full definitions come with the semantic layer).**
- `dso` is computed per invoice and weighted by amount, as of a date. Open invoices are aged to that date, so a distributor who stops paying shows up immediately instead of only once late payments land.
- `channel_days_of_stock` is computed per distributor, SKU and day. It is null when there were no secondary sales in the trailing 30 days, and those days are excluded from the stock-out and overstock rates.
- *Amended:* the stuffing baseline is the plan's literal trailing-90-day window, `[start − 90, start − 1]`, used identically by generator and detector.
  - An earlier version excluded prior scheme-window days. That leaves a repeat stuffer with only 4–6 baseline days, which is too noisy.
  - The literal window includes the previous window plus its drain, and the designed post-window drain makes the two cancel (net 0.97–1.00×).
- `scheme_concentration_ratio` compares against a leave-one-out baseline share: the median over the distributor's other quarters, floored at 15/91.

## Time and operations

**D14. Ground truth is pinned to absolute dates from a fixed anchor.**
`generator/config.yaml` pins `anchor_date`, and month labels (month 1 to month 36) are relative to it. The simulation is a pure function of (config, ground truth, as-of date):
- Re-running it for a later as-of date reproduces every earlier day exactly and adds the new days.
- The daily job therefore reseeds to yesterday and rebuilds, so a missed or doubled run can't drift.
- Evals always use the pinned as-of date.
- The anchor moves forward in 12-month steps (every September), which keeps each anomaly's seasonal placement.

**D15. `mart_installer_claim_cohorts`. Extends plan.**
The agent can only read marts, and none of the plan's §6 marts sits at installer grain, so `installer_claim_rate` would have nothing to query. This additional mart holds one row per installer × district × install month × months since install, with units installed and claims.

**D16. `installations._loaded_at`.**
This is the date the row became what it is: the registration date if the unit is registered, otherwise the ship date. Point-in-time replays use it to tell registered units from not-yet-registered ones. Other tables' visibility is already one of their own dates (`reported_date`, `claim_date`, `payment_date`, `invoice_date`), so they get no extra column.

**D17. `generator/ground_truth.yaml` is committed.**
Reproducing the data from a clean clone requires it. "Private to the generator" is enforced by policy:
- It is never loaded into Postgres, so the agent's marts-only role can't reach it.
- It is never used to compute eval golden answers; those come from the marts via SQL.
- The README doesn't point to it before the case-study reveal.

**D18. Detectors are pre-registered in `detectors/detectors.yaml`.**
It was committed before the first data generation. Every detector is a generic scan with a multiple-comparison correction, and none names an entity. Changing a rule after seeing data is a logged deviation here, and case-study numbers are then reported under both the old and the new rule.

**D19. Claim rates are deliberately higher than a real manufacturer's.**
Year-one tank claims run at about 0.5% a month (base crack about 0.2%). This buys the statistical power the anomaly checks need inside the row budget. The trade-off is disclosed in the case study rather than hidden.

**D20. Semantic layer: real MetricFlow, run as a compile-only engine inside the API (build prompt step 4, an "ask me" item).**
The 12 glossary metrics are defined once, in dbt 1.12's inline semantic spec under `warehouse/semantic_models/`. `dbt parse` validates them and writes `semantic_manifest.json`.

At query time the API loads that manifest into MetricFlow's Python engine (`metricflow` 0.213.0, already a dbt-core dependency) with a compile-only Postgres client. MetricFlow writes the SQL, including joins, non-additive stock snapshots and ratio metrics, and the API runs it on the read-only, region-filtered role.

A probe compiled every glossary metric, with group-bys and filters, without a database, a dbt adapter or the `mf` CLI. So the hand-written fallback compiler wasn't needed.

Trade-offs:
- The API image carries MetricFlow.
- Metric semantics are MetricFlow's. For example, stock metrics read the period's last day, and grouping by an entity uses its name (`distributor`), not its key column.

**D21. Extra marts beyond PLAN §6. Extends plan.**
- `fct_invoice_collections` (invoice grain) gives `dso` and `collections_efficiency` a home at the grain D13 needs.
- `mart_scheme_quarterly` gives `scheme_concentration_ratio` and the stuffing detector a governed table.
- `dim_date` (in marts) is the MetricFlow time spine, so compiled SQL never needs a schema the agent can't read.
- `mart_anomaly_flags` holds the pre-registered detectors' output for `get_anomalies`.

**D22. The cohort clock starts at shipment.**
`mart_batch_claim_cohorts` counts months since shipment, not since install, because about 30% of units never record an install date (D8). The PLAN §9 heatmap axis is labelled "months in service (from shipment)". This matches the pre-registered lot scan's `days_since_ship` exposure clock.

**D23. Thresholds.**
- Stock-out means under 7 days of stock and overstock means over 60 (target cover is 30).
- Days with no sell-out in the trailing 30 days have no days-of-stock value and count toward neither rate.
- The trailing average uses the days available at the window start, with a minimum of 14.

**D24. Channel-inventory serving grain.**
`fct_channel_inventory_daily` (PLAN §6) keeps the daily distributor × SKU detail: 6.5M rows.
- It was slimmed from 1.16 GB to 723 MB: region and category come through joins, and the region RLS policy looks the distributor up.
- Its last-day-of-period queries still took far longer than the API's 5 s budget. The governed inventory metrics are therefore served from `mart_channel_inventory_weekly`: 938k rows and 90 MB, holding each week's last available snapshot plus exact day counts, so `stockout_rate` and `overstock_rate` are still true "% of distributor-SKU-days". Days-of-stock by region dropped to about 0.9 s.
- The deployed copy keeps 60 days of the daily detail. Local builds and CI keep full history. *Amended (D49):* the trim now happens at publish time, after the models that read the detail were built on full history.

**D25. Deployment topology (build prompt "ask me": where to host the API).**
- **API on Render**, as a Docker web service from `render.yaml`. It bundles MetricFlow, its agent turns run 10–40 s, and it builds its semantic engine once per process. That's a poor fit for serverless Python function limits.
- **Web on Vercel**, from `web/`.
- **Supabase** holds only `marts`, published nightly by `.github/workflows/daily.yml` from a throwaway CI Postgres. Raw data never leaves CI. The database stays well inside the free tier, and the nightly write keeps the project from auto-pausing.
- **Not yet deployed.** Deploying needs the owner's Render, Vercel and Supabase accounts, plus the repository secrets `SUPABASE_DB_URL`, `AGENT_DB_PASSWORD` and `OPS_DB_PASSWORD`. *Amended in Phase 2 (D30):* a model key is never a repository secret; it goes only on Render, and only for live mode.

**D26. Generator implementation deviations** (reported by the generator build; verified independently by the acceptance suite).
1. Distributors order against the 28-day mean of true demand. Trailing lumpy purchases ratcheted stock to 113 days of cover.
2. Retailers buy in tier-scaled lots, and smaller accounts stock fewer SKUs. This keeps secondary sales inside the row budget.
3. Tank lines have per-shift capacities: Durgapur Line 2 47, Howrah 90, Guwahati 55. Howrah covers shortfalls, so no tank batch reaches 100 units.
4. Ship → install is clipped at 120 days (mfg + 155). An unsold unit at the cap installs in its holding distributor's district.
5. The churn multiplier shrinks each of the account's purchases instead of dropping whole purchases, and its lateness uses evenly spread quantiles of the specified distribution. Otherwise a small account's monthly ratios were too noisy.
6. Legacy plant stock on 2023-10-01 goes into distributors' opening stock.
7. The secondary reporting-lag p95 is 19 days, against the 17 assumed by the pre-registered horizon. The horizon stays at 17, and point-in-time visibility still filters on `reported_date`.

**D27. The stuffing drain follows ground truth's outcome, not its literal formula.**
Ground truth says post-window orders are θ × trailing-30 sell-out, with θ = 1 − 15(k−1)/72, until stock is back at target. That clears the excess by QE+72 only when demand is flat.
- After June windows demand falls, and the stuffing-off run is itself destocking at about 0.74× sell-out. θ ≈ 0.69 then barely undercut normal ordering, so the excess never cleared, and repeat stuffers ratcheted to about 100 days of cover. The acceptance suite's S5 check caught this.
- **New rule:** stuffers run their normal policy while treating the not-yet-drained excess as absent, and that excess falls linearly to zero at QE+72. With flat demand this is exactly θ·s.
- Also fixed: excess is split across SKUs by true sell-out, not lumpy trailing primary; and drain orders look half a review period ahead, so the last order doesn't re-buy the tail.
- **Result:**
  - Non-June cycles end within +1 to +2.8 days of the counterfactual at the next window.
  - June cycles end about 11–12 days over. Stock sized on the March–June peak meets the monsoon trough, and distributors can't return stock. Clearing that fully would mean changing ground truth's k or θ, which were fixed before generation, so it's reported, not tuned away.

**D28. The dashboard crash was stale processes, and panels now fail one at a time (Phase 2, A1).**

*What was seen:* `/api/meta` answered 404, `localhost:3000` often showed Next.js's "Application error" page, and at other times the "Primary and secondary sales" and "Channel days of stock" charts stayed empty.

*Root cause, in plain language:* both servers were older than the code on disk.
- **The API** had been started before `/api/meta` existed and was never restarted. The dashboard doesn't call `/api/meta`, so that 404 was a symptom of age, not the crash.
- **The dashboard** was a long-running `next start`, and later verification builds (`next build`) replaced the `.next` folder underneath it. The old server kept handing out HTML that named code files the new build had deleted, and it answered those requests with HTTP 400. The browser then couldn't load the page's JavaScript (`ChunkLoadError`), which is the "Application error" page. React's streaming script also couldn't place the panels that arrive last, which are the two charts that stayed empty. Whether a visit crashed or only lost those charts depended on which files the browser still had cached.
- Reproduced on purpose: rebuilding under a running `next start` gives exactly these errors in a fresh browser, and restarting the server clears them. That this is what happened on the owner's machine is an inference: Phase 1 ran verification builds while that server stayed up, and this was the only cause found that produces both symptoms. With a server that matches its build, all four pages load cleanly in every region tested.

*What changed:*
- `next dev` now builds into `web/.next-dev`, so a production build can't swap files under a running dev server. `make web-start` always builds and then serves.
- The smoke test (`make smoke`, and in CI) checks first that the dashboard server is running the build on disk and that the API serves `/api/meta`. So a stale process fails with a message that names it, instead of as a crashed page.
- **Containment:** every panel is wrapped in `Panel`, which is `Suspense` around a client error boundary.
  - A render exception replaces only that panel with a failure state and a Retry button.
  - `app/error.tsx` and a new `app/global-error.tsx` catch what's left. A code file that fails to load gets "The dashboard was updated. Reload".
  - Responses are shape-checked where they enter the dashboard (`web/lib/validate.ts`), so a response of the wrong shape becomes that panel's error state instead of a crash further down.
- **One wrong turn, kept on record:** the first version put the boundary outside `Suspense`. That made the still-streaming server content a prop of a client component, and on the Executive page React then abandoned the server render (error #419) on every load. The smoke test caught it: 8 of 8 runs failed, against 12 of 12 passes with plain `Suspense`. With `Suspense` outside the boundary, 12 of 12 passed.
- `web/e2e/faults.spec.ts` proves the containment against the real API. A proxy breaks two metrics, one with the wrong shape and one with HTTP 500. Exactly those panels show errors, and the rest of the page draws.

**D29. The agent's model, live mode and replay (Phase 2, A3; owner-approved 2026-09-27).**
Superseded on the model by D50.
- **Model:** `claude-opus-5-5` by default (`CHANNELPULSE_MODEL`), with no separate routing model.
  - It was chosen from Anthropic's models and pricing pages on 2026-09-27. Opus 5.5 is the docs' recommended default, at $4 / $20 per million input/output tokens with cache reads at $0.20. The old default, `claude-opus-5`, is $5 / $25 / $0.50 and now legacy. Sonnet 5 is $2 / $10 / $0.20.
  - Haiku 4.5 was ruled out: its retirement can come as soon as 2026-10-15.
  - A routing model was ruled out because it adds a call and a second prompt cache to every question, and the routing is already enforced in code. A two-model eval shows whether a cheaper model is enough on its own.
- **Effort:** `medium` (`CHANNELPULSE_EFFORT`). It is Opus 5.5's own API default, and Anthropic reports Opus 5.5 at `medium` beating Opus 5 at `high` on analysis work. This is a default, not a measured choice; the eval can compare levels.
- **Compatibility:** the loop already fits Opus 5.5's breaking changes. It uses adaptive thinking and never forces `tool_choice` (only `none` on the last round). Its history is append-only, with fallback turns echoed as documented.
- **Pricing fix:** trace costs, and so the daily spend cap, now use each model's own cache-read price. They had priced every cache read at 0.1x input, which is wrong for Opus 5.5 (0.05x).
- **Live mode is opt-in:** `/api/ask` calls the model only when credentials resolve *and* `ASK_LIVE=1`. With either missing it answers 503 and nothing is sent. `GET /api/ask/status` says which case applies.
- **Replay:**
  - A complete eval run over the whole question set writes `api/app/recordings/<model>.json`: each answer exactly as `/api/ask` returned it, with the run's model, date, as-of and region claim, and the eval's verdict on it.
  - `GET /api/ask/replay` serves the configured model's recording, or else the newest.
  - Answers are withheld under any region claim other than the one they were recorded with (the eval asks as ALL), because they could show rows that claim may not see.
  - The Ask page shows replay whenever it isn't live, with the verdict on every answer, including wrong ones, shown as recorded. Before any recording exists it shows an honest empty state.
  - Replay fixtures are never written to `recordings/`. (The dev-only story page that showed them was removed in the 2026-10-14 cleanup.)
- **`make eval` spends only on a yes:** it prints an estimate before any model call and waits for a typed yes. `YES=1` (`--yes`) skips the question. A non-interactive run without it stops with exit 3.
  - The estimate is the measured mean cost of a previous run of the same model, or else a token profile (4 calls, a 14k cached prefix, 3k fresh input and 1.5k output per call) at list prices, both with a 25% margin.
  - Windows reports `NUL` as a terminal, so end-of-input also counts as no.
  - It warns when the estimate exceeds `--budget-usd`, because a run cut short by the budget isn't recorded for replay.

**D30. Deployment readiness (Phase 2, A4).** The README's deployment notes were walked as a first-time deployer. What was missing is now in `docs/deploy-checklist.md`, in order:
- **Supabase connections go through the Session pooler.** GitHub Actions and Render have no IPv6, and Supabase's free-tier direct host is IPv6-only. Pooler usernames carry the project ref (`channelpulse_agent.<ref>`).
- **The order matters:**
  1. The first nightly publish must run before the API can answer, and it is also what creates the roles.
  2. Render's `CORS_ORIGINS` can only be set once the Vercel URL exists.
  3. A replay recording should be committed before deploying.
- **The public demo starts in replay mode.** `render.yaml` pins `ASK_LIVE=0`. Live mode needs a key *and* `ASK_LIVE=1`, and then the per-IP rate limit and the daily spend cap (00:00 UTC reset) apply to every question.
- **A model key is never a repository secret.** The README had listed it as one.
- **A repeatable identifying-information check,** `make identity-check` (`scripts/identity_check.py`):
  - It searches tracked files at every commit, commit messages, and author and committer identities.
  - Its terms come from a gitignored `.identity-patterns` file, because committing them would be the leak. It never prints them.
  - It fails when there is nothing to search for, rather than passing.
  - Run on 2026-09-27 with the owner's email domain and name terms as arguments: clean.
- **The deployed site can be smoke-tested** with `SMOKE_URL=… SMOKE_API_URL=… SMOKE_REMOTE=1 make smoke`.
- **Known and documented rather than fixed:**
  - Render's free plan sleeps when idle, so the first view after a quiet spell can time out in some panels.
  - The nightly republish can interrupt queries for a few seconds.
  - Vercel's function duration may need raising.

**D34. `get_anomalies` gets filters and view-aware ordering (Part B, owner-approved 2026-09-29).**
- **The problem:**
  - `get_anomalies` returned every detector's flags, 500 rows, ordered by detector name, and the model sees only the first 50 rows of any tool result.
  - The first 50 all came from `distributor_health`, so no lot-scan flag was in view.
  - The API endpoint already had a `detector` filter, but the agent's tool didn't expose it.
- **Change:**
  - The tool takes optional `detector` and `failure_mode` filters.
  - Unfiltered rows are ranked by effect size within each detector and interleaved across detectors, so the first rows hold every detector's strongest flags.
  - The tool description says the model sees only the first 50 rows.
- **On the real marts:** all four detectors appear in the first 50 unfiltered rows, and the planted lot is row 3. Filtered to `lot_scan` and `base_crack`, it is the only row.
- **What didn't change:** no detector rule, flag, metric or ground-truth parameter. This changes which rows reach the model, not what the detectors found.

**D36. The Indian fiscal year is a time grain in the semantic layer (Part B, owner-approved 2026-09-30).**
- **Why:**
  - The semantic layer offered only calendar grains. Its year, `metric_time__year`, runs January to December, so a fiscal-year question left the model to add quarters up itself.
  - This is a gap in the governed layer, not a model quirk: a business that reports April to March needs its fiscal year to be governed.
- **Change:**
  - `dim_date`, the MetricFlow time spine, declares two custom granularities: `fiscal_quarter` (from `fiscal_quarter_label`, e.g. FY27 Q1) and `fiscal_year` (from `fiscal_year_label`, e.g. FY26 = April 2025 to March 2026). Both columns get `not_null` tests.
  - Every metric can be grouped by `metric_time__fiscal_year` or `metric_time__fiscal_quarter`.
  - `query_metric`'s description says which grain is calendar and which is fiscal.
  - The shipped `semantic_manifest.json` is regenerated.
- **Verified against the eval's independent golden SQL:**
  - primary sales by `metric_time__fiscal_year` give FY25 Rs 4,563,765,266.46 and FY26 Rs 4,890,601,104.28 (TC01);
  - base-crack claims by plant give DGP 538 / 755, GHY 592 / 709 and HWH 1,113 / 1,341 (TC05).

  Every offered dimension still compiles for all 50 metrics.
- **Not changed:** no mart data, metric formula, detector or ground-truth parameter. Fiscal grains are for grouping; filters on them aren't supported, and date ranges do that job. Raw mode never uses the semantic layer, so it is unaffected.

**D37. Filters on two-hop dimensions were broken; fixed (Part B, 2026-09-30).**
- **Root cause,** in `api/app/semantic.py`, the code that renders filters: it passed a multi-hop name straight into MetricFlow's filter syntax, `{{ Dimension('batch__product__category') }}`. MetricFlow can't parse that: the extra hop must be an entity path, as in `{{ Dimension('product__category', entity_path=['batch']) }}`.
- **It predates D36:** the same filter fails on the pre-D36 manifest.
- **Scope:** every offered two-hop dimension, 41 metric-and-dimension pairs, failed as a filter. Group-bys were never affected; they go through a different path.
- **Fix:** multi-hop names are rendered with `entity_path`. A new test compiles all 41 pairs as filters: all 41 fail with the fix disabled and pass with it.

**D39. Golden set v2: 102 questions, a clarification category, and a free tier in CI (Part C 1, 2026-09-30).**
- **The set** (`evals/questions.yaml`) grew from 40 to 102 questions: 18 simple lookups, 18 filtered or grouped, 18 time comparisons, 14 multi-hop "why" questions, 18 traps, and a sixth category, 16 **ambiguous** questions whose right answer is a question back.
  - Every golden answer is still hand-written SQL on the marts.
  - An ambiguous question carries two or three *readings* (sell-in or sell-out, calendar or fiscal Q1, which of two reps named Sharma), each with its own golden SQL. The eval fails unless the readings give different answers, so each question is ambiguous in fact, not just in wording.
- **`needs_clarification`, a fourth answer label.** The final-answer schema gains `clarifying_question`, and the prompt tells the model to ask when a question could mean two things with different answers. Code turns that into a response with no figures and the question back. It's scored correct only on ambiguous questions, and never counts as confidently wrong. It's carried through the API, `ops.agent_traces` and the web badge.
- **Model-free refusal routing** (`app/guardrails/refusal_routing.py`). Four narrow patterns are refused before any model call: SQL writes, raw/staging/system tables, prompt injection, and "don't show the SQL". The rest, forecasts, personal data and off-topic questions included, stays the model's call.
- **Two tiers:**
  - **Free and deterministic** (`evals/tests/test_free_tier.py`, `make eval-free`, run by `make test` in CI on every PR). No model is involved:
    - **Semantic layer:** each of the 47 governed scalar and keyed questions has a hand-written `governed_call`, the `query_metric` call(s) a correct answer makes. Its results must reproduce the golden under the eval's own scorer. This checks the metric definitions against independent SQL.
    - **SQL validator:** every trap's `attack_sql` is rejected.
    - **Router:** it refuses exactly the questions marked `router` (9 traps) and none of the 84 non-traps.
    - **Goldens:** every golden validates, and every ambiguous question's readings disagree.
  - **Full model suite:** manual only (`make eval`). It reports execution accuracy on the 68 answerable questions against a threshold of 85% (exit 5 below it), plus refusal and clarification correctness and the number of router refusals. CI never holds a model credential (a test enforces it).
- **Found by the free tier:**
  - **A fiscal-grain query timed out.** Since D36, `primary_sales_value` grouped by `metric_time__fiscal_year` took 10 s and hit the statement timeout. Under the RLS filter and MetricFlow's `date_trunc` predicates, the planner estimated the fact table at 2 rows and nested a loop over the time spine. `readonly_db` now sets `enable_nestloop = off` per transaction, and the query takes 0.15 s. Index scans still serve filters.
  - **`channel_stock_units` isn't total stock.** It counts only distributor-SKU rows with a days-of-stock value, so it's about 40% below all units held at the latest snapshot. It's a building block of `channel_days_of_stock`, where that filter is right, but its label ("Channel stock (units)") suggests all stock. Changing a metric definition needs the owner's approval, so it's unchanged. FG18 asks about days of stock instead, and the finding is open.
- **Scoring rules are not changed mid-evaluation.** Some are strict by design and stay strict:
  - extra keys aren't allowed where a question allows none;
  - a figure the model counted or summed from result rows itself, which rule 4 forbids, isn't in the evidence.

**D40. Agent traces view: recorded traces for anyone, live ones behind a token (Part C 2, 2026-09-30).**
- **Two sources, one shape:**
  - Recorded: each answer in the eval's replay recordings carries the trace the eval wrote: tool calls with SQL, row counts, durations and errors; tokens; latency; cost; label; and the eval's verdict.
  - Live: `ops.agent_traces`, written by `POST /api/ask`.
- **Why recorded traces:** the public demo is replay-only (D29), so `ops.agent_traces` there stays empty. The recordings are the traces reviewers can actually inspect. Like replayed answers, they're served only under the region claim they were recorded with, because their tool outputs can hold rows another claim may not see.
- **Why the token:** live rows are questions real visitors typed. `GET /api/traces` includes them only when the request carries `X-Admin-Token` equal to `ADMIN_TOKEN`, compared in constant time. With the variable unset, the default, they're never served. The dashboard sends the token server-side only.
- **API:** `GET /api/traces` filters by source, label, provider, model, category, and a text search over the question and SQL. It's paged, with facets over all rows and totals over the filtered ones. `GET /api/traces/{id}` returns the tool calls.

**D41. The Weekly Brief and its numbers check (Part C 3, 2026-09-30).**
- **A brief is facts plus sentences:**
  - **Facts.** Each is one query under the viewer's region claim: a governed metric for the chosen Monday-to-Sunday week and the week before, or, for new anomaly flags, the detector-flags query. Each fact carries its SQL.
  - **Sentences.** Each one cites the facts it states, so every figure on the page links to the query behind it.
- **Narration.** In live mode, the model narrates, told to copy each fact's display text exactly and never to compute. Otherwise, or when its narration is unusable, a deterministic template does. The demo is replay-only, so it serves the template.
- **The numbers check** runs before a brief is served. It re-executes every cited query, then reads each sentence's figures back (`response.figures`, the Ask agent's own tracer) and requires each to match one of its cited facts.
  - A model narration that fails is blocked. The template is served in its place, and the reasons come with the brief.
  - A template that fails, because the data changed underneath it, blocks the brief outright.
  - Tested both ways: an invented "up 17%" blocks the narration, and a changed value blocks the brief.
- **Known ceiling:** like the Ask tracer, it skips bare single digits and years, so a wrong "3 flags" isn't caught. Figures with a unit or a thousands separator are.
- **Found while building it:** sums over the float4 column `avg_daily_secondary_units` vary in the fifth significant digit between runs, because parallel workers add in a different order (days of stock 43.654685 vs 43.654642). Re-executed floats compare within 1e-5 relative. The column type is a warehouse choice, so it's left as is and noted here.

**D44. Cleanup audit: deletions only, refactors deferred (owner decision, 2026-10-02).**
- **Audit (2026-10-01).** Searches for defined-but-unused code, plus ruff and eslint; no new tools were installed. Baseline: build, 850 tests and lint all passing.
- **Found:**
  - one dead function, `detailPairs` in `web/lib/metrics.ts`, unused since the redesign. It was deleted, with the import it left unused (7dafa51).
  - No dead Python code, TODO/FIXME comments, bare `except:`, lint suppressions or unimported files.
- **Also applied in that pass, before this decision:** both are behaviour-neutral and verified by the type check, build, tests and smoke run.
  - `response._traced` became public `traced`, since the Brief uses it (84ef0e5).
  - 31 web names lost an unneeded `export` (f30d2a5).
- **Decision:** no larger refactors now; deployment comes next. Only deletions that are provably dead and covered by passing tests are applied. The refactor candidates are listed as future work in the README's known limitations.

**D45. `channel_stock_units` counts all stock; days of stock keeps its own numerator (owner-approved, 2026-10-02).**
- **The finding (D39):** "Channel stock (units)" summed stock only on distributor-SKU pairs with a days-of-stock value. Every excluded pair at the latest snapshot holds stock with no sell-out in the trailing 30 days: idle stock. At the week of 14 September 2026 it reported 1,555,029 units against 2,471,122 held, leaving out 37%. The share is seasonal: about 18–21% each March, about 36–37% each September.
- **Change:**
  - `channel_stock_units` now sums all stock.
  - A new building block, `channel_stock_units_selling` (stock on pairs with recent sell-out), is the numerator of `channel_days_of_stock`, because days of stock is undefined where nothing sold.
  - `channel_days_of_stock`, the stock-out rate and the overstock rate are unchanged: 43.65 days for that week before and after.
  - The manifest is regenerated (51 metrics), and a free-tier test pins all three against independent SQL.
- **What depends on it:** nothing scored.
  - No golden question's governed call uses `channel_stock_units`, and no dashboard panel or the Brief does either.
  - The stuffing flag (window rate ratio on primary units) and the health score compute their own stock in dbt.
- **Also:** `api/app/admin.py` now imports psycopg only for `roles`, so `make semantic` needs no database driver, as its docstring already said.

**D46. Detector v2: pre-registered on the seed of record, frozen before the holdout seed (owner-approved, 2026-10-02).**
- **Goals (owner):** stuffing precision well above v1's 36% without recall falling far below 96%, and the churn account flagged before 2026-01-31. Detectors make no model calls.
- **Protocol (Phase 2 spec):**
  1. Develop on the current seed, 20260924, whose data had been inspected.
  2. Freeze the v2 rules in `detectors/detectors.yaml` and commit them, together with the holdout seed, 20261002, chosen before any generation.
  3. Generate the holdout in a separate Compose project and database on port 5433.
  4. Report v1 and v2 on both seeds, whichever way they fall.
- **Ground truth:** the acceptance suite's own rule, never a detector's. A stuffer cell is a (distributor, tank or pipe, window) with window units at least 1.8x the stuffing-off run. The churn account is the generator's pick for the seed. `detectors/evaluate.py` scores both versions.
- **Re-measured v1 on the seed of record:** precision 34.0% and recall 95.8% (2,156 flags, 764 stuffer cells). That's against the case study's 36% and 96% from an earlier data window. Health v1 flags D0084 on 2026-02-15, flags 172 other distributors, and has 13.2% of stuffers at risk during their overhang. The acceptance target (C7) is under 5%, so v1 already fails it.
- **What development found:**
  - **Stuffing:**
    - v1's false positives order lumpily: an ordinary order lands in the 15-day window. Inside the window they look like stuffers in rate, order size and scheme share.
    - The concentration ratio made precision worse, and order-size and block-maximum tests failed.
    - Scheme participation (at least one scheme invoice in the window) doubled precision at almost no cost in recall.
    - What separates loading from demand comes after the quarter: the order dip over the next 30 days, and the stock excess.
  - **Health:** v1's secondary gate is a percentile among region peers, which moves in coarse steps in a small region. An absolute year-on-year sell-out gate, with sell-in holding up, is the churn signature itself.
- **v2 as frozen:**
  - **Stuffing:** provisional = v1 and at least one in-window scheme invoice. Confirmed (once QE+60 is in the data) = provisional and (orders over QE+1..QE+30 below the baseline daily rate, or a stock excess of at least 3 days).
  - **Health:** `score < 30` and sell-out under 0.8x the same 8 weeks a year earlier and sell-in/sell-out above 1.1, in 3 consecutive weeks.
  - **On the seed of record:** stuffing provisional 50.5% precision / 95.4% recall, confirmed 65.0% / 87.2%; health flags D0084 on 2026-01-11, 137 other distributors, 11.5% of stuffers in overhang.
- **Overfitting risk, stated before the holdout:**
  - The thresholds are round, but they were chosen by looking at this seed.
  - The churn gate's 0.8 sits close to D0084's signal: at 0.75 the rule misses the account entirely.
  - The holdout seed is the test of both.
- **Product:** `mart_anomaly_flags` and `get_anomalies` keep serving v1 until the owner decides. The new mart columns aren't in the semantic layer, so the agent's metric glossary is unchanged. The marts' column list in the system prompt grows.
- **Generator:** `--seed` runs a holdout seed. It never asserts against, or writes back into, `ground_truth.yaml`, which records only the seed of record.

**D47. Detector v2 results on both seeds, reported as they fell (2026-10-02).**
- **Holdout:** seed 20261002, generated after the freeze (a9354eb) in its own Compose project and database on port 5433. Its stuffing-off counterfactual came from the same generator. dbt passed 164 of 164 on it. The generator picked churn account `D0089`. `ground_truth.yaml` wasn't touched.
- **Stuffing,** precision / recall, seed of record then holdout:
  - v1: 34.0% / 95.8%, then 34.6% / 94.9%;
  - v2 provisional: 50.5% / 95.4%, then 50.5% / 94.8%;
  - v2 confirmed: 65.0% / 87.2%, then 64.3% / 86.6%.

  The confirmed stage is scored only on windows whose 60 days after quarter-end are in the data. The gains carry over to the holdout almost exactly.
- **Churn,** first at-risk week (target: by 2026-01-31):
  - v1: 2026-02-15, then 2026-03-15, both late;
  - v2: 2026-01-11, then 2026-01-25, both in time, the holdout by 6 days.
- **Health false positives:**
  - other distributors ever at risk, v1 to v2: 172 to 137, and 171 to 130;
  - stuffers at risk during their overhang: 13.2% to 11.5%, and 11.7% to 12.6%.

  On the holdout, v2 is slightly worse than v1 on the stuffer measure. Both versions fail acceptance C7's under-5% target on both seeds.
- **Status:** the product keeps serving v1 (`mart_anomaly_flags`, `get_anomalies`) until the owner decides whether to switch. The results are in `detectors/results/evaluation_20260924.json` and `evaluation_20261002.json`.

**D48. Detector v2 in production (owner decision, 2026-10-02).**
- **Switch:** the marts' unversioned flag columns now carry v2, and v1 stays on record as `*_v1`:
  - `mart_scheme_quarterly.is_stuffing_flag` (provisional) and `is_stuffing_confirmed`;
  - `mart_distributor_health_weekly.is_flag_week` and `is_at_risk`.

  So everything that reads them moved together: `mart_anomaly_flags` and `get_anomalies`, the governed metrics `at_risk_distributors` and `stuffing_flags` (descriptions updated, manifest regenerated), the Weekly Brief and the dashboard. `detectors/evaluate.py` reproduces the frozen D47 numbers exactly under the new names.
- **Point-in-time:** a stuffing flag writes a provisional row dated at the window's end and, if confirmed, a second row dated QE+60, when its post-quarter evidence exists. On the seed of record that's 1,445 provisional and 979 confirmed rows. An as-of read never sees later data.
- **Golden answers that moved** from v1 to v2:
  - SL16: at-risk distributors in the week of 14 September, 6 to 3;
  - FG16: FY26 stuffing flags by region, e.g. Bihar & Jharkhand 201 to 150;
  - MH02: the clearest channel-stress distributor, D0246 to D0080;
  - MH10: the strongest stuffing flag, D0348 to D0090;
  - MH12: the region with the most at-risk distributors, Bihar & Jharkhand to South Bengal.

  SL05, FG18 and AC09 differ only by float4 noise (D41), well inside tolerance. No golden SQL was edited.
- **Eval:** a future run grades against v2's answers.

**D49. Pre-deployment checks: size, memory, cold starts and secrets (2026-10-04).**
- **Database size against Supabase's free plan.** The plan allows 500 MB of data plus indexes, and goes read-only above it. The nightly job publishes only `marts`.
  - Measured with the deployed 60-day inventory slice: **356 MB**, roughly 140 MB of headroom before Supabase's own schemas.
  - The time series grow as the simulation advances a day each night, so the headroom shrinks over the coming months. The first lever is a shorter daily-inventory window.
- **Bug found, fixed:** the 60-day trim was a dbt variable on `fct_channel_inventory_daily`. But `mart_channel_inventory_weekly`, which serves every governed inventory metric and the dashboard's stock panels, and the stuffing follow-through in `mart_scheme_quarterly` are both built from that table. So the deployed copy would have shown only about 9 weeks of stock history, and lost the confirmation evidence for older stuffing flags. Local and CI builds never set the variable, so it was never seen.
  - Now `daily.yml` builds everything on full history, runs the detectors, then deletes the old daily rows just before `pg_dump`.
  - The variable is removed from the model.
- **Memory against Render's free plan** (512 MB RAM, 0.1 CPU, spins down after 15 idle minutes):
  - **The deploy image, unconstrained:** 97 MiB idle after startup, 102 MiB after the first governed query, and a peak of 131 MiB under a dashboard burst of 21 governed queries plus replay, traces and the brief.
  - **Throttled to 0.1 CPU and 512 MB:** a 136 MiB peak. The burst took 22 s in total, with the slowest call at 6.4 s, inside the dashboard's 20 s per-call limit. The brief took 10 s, and the container needed 44 s from start to healthy.
  - **Vercel:** the Hobby plan's function limit is 300 s, so a slow page render isn't cut off.
- **The "waking up" state.**
  - **Detection:** when the API host sleeps (an `onrender.com` host, or `CHANNELPULSE_API_COLD_STARTS=1`), the dashboard reads a timeout, a refused connection, or an HTML answer where the API always sends JSON (a loading page, or a 502–504) as the API waking.
  - **Display:** it shows a calm "The API is waking up" state in place of an error, and re-runs the page by itself every 15 s.
  - **Short-circuit:** the first such answer marks the API as waking for 20 s, so a page's other calls don't each wait out a timeout. Calls skipped in that window don't extend it.
  - **Tested:** a fault test proxies the API as an HTML 503, checks the state, then lets the API answer and checks that the page fills in without a click.
  - **Isolation:** the two fault-injection tests now share one file, so they run one after the other. Two extra dashboards at once slowed the local API into timeouts of its own.
- **Secrets and identity before going public.**
  - gitleaks (Docker image) over the full history: 72 commits, about 19 MB, **no leaks found**.
  - `make identity-check` needs the owner's `.identity-patterns` file, which doesn't exist yet. Run with explicit terms (the owner's email domain stem and local part, and the local Windows username), it found none of them. The only author identity in history is the project's pseudonymous one.
  - Nothing was rewritten.

**D50. Claude only: Gemini and Qwen removed, with everything they produced; Sonnet 5.5 by default, Haiku 5.5 to compare (owner decision, 2026-10-14).**
- The owner moved the project to Anthropic's API under a $20 spend limit and asked for everything tied to the Gemini key and the Ollama endpoint on Kaggle to be deleted, including the data and the write-ups made with them.
- Removed: the OpenAI-compatible provider (Gemini, Ollama) and its settings; the eval's quota pacing (`evals/throttle.py`); every run file in `evals/results/runs/`, both replay recordings, the agent traces they wrote, and the scorecards, results and case-study findings built on them. Decisions D31–D33, D35, D38, D42 and D43 described only those providers and their runs, so they are deleted and the numbering keeps the gaps.
- Kept from that work: the provider interface between the loop and the model, resumable runs (progress is saved after every question; rerunning the same command resumes), and the raw text-to-SQL baseline mode.
- A run now stops with its progress saved (exit 4) when the API is unreachable, overloaded, rate-limited or out of credit, instead of scoring those questions as model failures.
- Model: `claude-sonnet-5-5` at `medium` effort by default, superseding D29's Opus 5.5, which the owner ruled out on cost. `claude-haiku-5-5` is the comparison model. Haiku 5.5 has no server-side refusal fallback, so its requests don't send `fallbacks`.
- Replay serves the configured model's newest recording, else the newest one (as in D29, by model now rather than provider).
- Until the first Claude run, the scorecard is empty and the Ask page's replay says no eval has run yet.

**D51. The first Claude runs, reported as they fell (2026-10-14).**
- **Runs:** Sonnet 5.5 and Haiku 5.5, governed and raw, all 102 questions, once each, at `medium` effort. A 6-question pilot on Haiku 5.5 checked the integration first; its answers count toward the full run, which resumed from them. No run paused or errored.
- **Results:**
  - Execution accuracy, governed against raw: Sonnet 5.5 100% against 86.8%; Haiku 5.5 97.1% against 73.5%.
  - No question went from right to wrong (McNemar exact p = 0.0039 and 3.1e-05).
  - One trap was answered: TR01, by Haiku 5.5 in governed mode.
  - Ambiguous questions answered without asking, out of 16: governed Sonnet 6, raw Sonnet 3, governed Haiku 4, raw Haiku 2.
- **Cost:** $7.99 in all. Sonnet 5.5: $5.96 governed, $1.83 raw. Haiku 5.5: $0.12 governed, $0.08 raw. The harness's pre-run estimate (about $10 a Sonnet run) was high, because cache reads dominate the bill.
- **Reporting:** "tokens per question" now counts the whole prompt the model read, cache reads and writes included. It had counted only uncached input, which on Claude is a handful of tokens. No scoring rule changed.
- **Replay** serves the configured model's recording (Sonnet 5.5 by default); Haiku 5.5's is shipped too.
- **Not changed after seeing the results:** no rubric, golden answer or prompt. Governed mode's ambiguity gap is the next thing to fix, and it goes through the owner first.

**D52. Second cleanup pass: everything the review and audit found, by tier (owner decision, 2026-10-14).**
- **Inputs:** a ponytail review of the Claude-only change, a ponytail audit of the whole repo, and the codebase-cleanup method. The baseline was clean: 800 tests, ruff and eslint with no warnings, dbt parse and the web build.
- **Deleted:** the dev-only story pages under `web/app/dev/` (owner's call) and `web/lib/check.mjs`, which nothing ran and which no longer ran.
- **Removed as dead:** single-provider leftovers (the Provider Protocol, fence stripping, the status response's constant `provider`), write-only fields, the web's branches for response shapes the API never sends, eval flags and scorecard keys nothing used, and five settings read from the environment but set nowhere.
- **Consolidated:** one Postgres connection definition (`app.db.db_conninfo`), one role-password mapping, one percent formatter, one `metricOf`, one bucket-label formatter, the detector names, and the text the two system prompts repeated (byte-identical afterwards). `compile_query` returns the SQL.
- **Replaced:** the detectors' incomplete-gamma code with a short pmf sum (`math.lgamma`), within the tests' 1e-12 tolerance.
- **Fixed on the way:** the trace drawer's failed-call count never showed, and `generator/load.py` defaulted to `localhost`.
- **Kept:** `toDefMetric`, because passing a whole `Metric` to the client-side definition drawer would ship its dimensions to the browser; the two `month_add` copies, because merging them would couple the black-box acceptance suite to the detectors; `/api/meta`, which the smoke test uses to detect a stale API process (D28).
- **Verified:** after each change. At the end: 800 tests, ruff, eslint, typecheck, dbt parse and the production build, plus the Ask, traces and brief pages against the live API.

**D53. Navigation that Next never applies (a filter change or a link) falls back to a full page load (2026-10-15).**
- **Found** while clicking through the redesign: on a cold result cache, about half of region switches never applied. The page stayed on the old render, dimmed as "Updating", with no error and no end. Warm switches always applied.
- **Cause, as far as it can be traced:** Next 15.5's client navigation itself. A bare `router.push` from the console stalled the same way, outside the app's transition. In the stalled runs, the RSC response either finished streaming and was never committed, or the browser cancelled it mid-stream; nothing in the app dispatched another navigation or touched `history`. D49's waking-up refresh, which sometimes was never applied, is the same behaviour.
- **Workaround:** every in-app navigation starts a 12 s watchdog: `setParams` (every filter on every page) and every same-origin link click (a capture-phase listener, since Next's Link handler prevents the default). If the URL still hasn't moved by then, the browser loads the new URL in full, as Next does itself when an RSC fetch fails. A newer navigation, or arriving anywhere else first, cancels it.
- **Links too:** clicking through the redesigned Distributor 360 later stalled one link in four to a cold distributor page (D0004 waited 180 s), so the watchdog was extended from filters to links the same day.
- **Tests:** two fault tests stall the navigation's RSC fetch, one for a region change and one for a link, and expect each to land by a full load.
- **Revisit** on the next Next upgrade: drop the watchdog if region switches on a cold cache always apply.

**D54. The "Monsoon Editorial" redesign: dark by default, a light edition, motion with reduced motion honoured (owner decision, 2026-10-15).**
- **Direction:** the owner asked for a more animated, premium look with new colour, graphics and type. Of three directions mocked in Stitch, the owner chose a mix of two: Monsoon Night's dark luxe with Ganga Editorial's type and hairline rules. Dark is the default and a toggle switches to a warm-paper light edition; the choice is remembered and applied before first paint. Print always uses the light values. `web/DESIGN.md` is the full system.
- **Type:** Newsreader for titles, figures and the brief's prose; Plus Jakarta Sans for the interface; JetBrains Mono for SQL and IDs. Each was checked in the font files for the ₹ sign and tabular figures. `geist` was removed; no dependency was added.
- **Colour:** teal accent and a marigold second; the chart palettes were re-stepped for both editions and validated with the dataviz method (worst adjacent CVD ΔE 14.0 light, 12.4 dark). Every text token clears WCAG AA on every surface in both editions, checked by a test.
- **Motion:** staggered entrances, counting figures, charts that draw in when their data changes (not on a resize), wiping sparklines, glowing dark-mode lines, hatched provisional periods, a drifting header aurora and canvas grain. `prefers-reduced-motion` stops all of it, figures included.
- **Found and fixed on the way** (each with a test): navigation that Next never applies (D53); sparklines left with permanent gaps by a dash draw on a non-scaling stroke; a dollar figure set as if it had no value; and layout breaks at 1024px (titles, the KPI band) and at 390px (a cut title, cut chart labels).
- **Checked:** after every task, the full e2e suite (32 tests at the end: smoke, faults and 11 redesign tests); ruff and 800 Python tests; a 64-shot matrix (8 pages, 4 widths, both editions) with no horizontal overflow; a click-through of every control on every page in both editions at 1440 and 390px; and an independent design review, whose six material fixes (radii, type sizes and the aurora to the spec, the brief's footnotes, phone bar labels, panel footers) are in.

## Environment

**E1. Windows Smart App Control pins psycopg2-binary to 2.9.10.**
On the build machine, Smart App Control (enforcement mode) blocks the newest psycopg2-binary 2.9.13's bundled `libcrypto` DLL, a build with no reputation yet. That stops dbt entirely. 2.9.10's DLLs load. No security setting was changed. Linux and CI are unaffected.

**E2. Clean-clone verification (Phase 2, A2, 2026-09-27).**
A fresh `git clone` of `phase2` at `45bca02` into `D:\cpc` ran the README quickstart end to end with no code changes. It used its own Compose project and data volume (`cpc`, Postgres on 5433, API on 8020, dashboard on 3100), so the existing database was never touched.
- `make setup` took 2 min, `make seed` 56 s and `make dbt` 5 min 49 s: dbt passed 162 of 162.
- `make lint` and `make test` passed, with 459 tests including the database-backed ones; the web build passed; `make smoke` passed 13 of 13.
- The detectors' output (`detectors/results/latest.json`) came out identical to the committed file, apart from its runtime, so the data regenerates exactly.
- Machine-specific steps, all now in the README:
  - port 8000 was taken by another project, so `API_PORT` and `NEXT_PUBLIC_API_URL` were changed;
  - the psycopg2-binary pin (E1) for Smart App Control;
  - Playwright uses the installed Edge.
- Nothing broke. npm warns that one ESLint dependency's install script (`unrs-resolver`) isn't approved to run; lint passes without it.

