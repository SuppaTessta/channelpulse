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
- The deployed copy keeps 60 days of the daily detail (`inventory_history_days`). Local builds and CI keep full history.

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
- **Model:** `claude-opus-5-5` by default (`CHANNELPULSE_MODEL`), with no separate routing model.
  - It was chosen from Anthropic's models and pricing pages on 2026-09-27. Opus 5.5 is the docs' recommended default, at $4 / $20 per million input/output tokens with cache reads at $0.20. The old default, `claude-opus-5`, is $5 / $25 / $0.50 and now legacy. Sonnet 5 is $2 / $10 / $0.20.
  - Haiku 4.5 was ruled out: its retirement can come as soon as 2026-10-15.
  - A routing model was ruled out because it adds a call and a second prompt cache to every question, and the routing is already enforced in code. Part B's two-model eval shows whether a cheaper model is enough on its own.
- **Effort:** `medium` (`CHANNELPULSE_EFFORT`). It is Opus 5.5's own API default, and Anthropic reports Opus 5.5 at `medium` beating Opus 5 at `high` on analysis work. This is a default, not a measured choice; Part B can compare levels.
- **Compatibility:** the loop already fits Opus 5.5's breaking changes. It uses adaptive thinking and never forces `tool_choice` (only `none` on the last round). Its history is append-only, with fallback turns echoed as documented.
- **Pricing fix:** trace costs, and so the daily spend cap, now use each model's own cache-read price. They had priced every cache read at 0.1x input, which is wrong for Opus 5.5 (0.05x).
- **Live mode is opt-in:** `/api/ask` calls the model only when credentials resolve *and* `ASK_LIVE=1`. With either missing it answers 503 and nothing is sent. `GET /api/ask/status` says which case applies.
- **Replay:**
  - A complete eval run over the whole question set writes `api/app/recordings/<model>.json`: each answer exactly as `/api/ask` returned it, with the run's model, date, as-of and region claim, and the eval's verdict on it.
  - `GET /api/ask/replay` serves the configured model's recording, or else the newest.
  - Answers are withheld under any region claim other than the one they were recorded with (the eval asks as ALL), because they could show rows that claim may not see.
  - The Ask page shows replay whenever it isn't live, with the verdict on every answer, including wrong ones, shown as recorded. Before any recording exists it shows an honest empty state.
  - Fixtures for the replay view live only in the dev-only story `web/app/dev/replay-fixture`, and are never written to `recordings/`.
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
- **The public demo starts in replay mode.** `render.yaml` pins `ASK_LIVE=0` and `CHANNELPULSE_MODEL`. Live mode needs a key *and* `ASK_LIVE=1`, and then the per-IP rate limit and the daily spend cap (00:00 UTC reset) apply to every question.
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

**D31. A swappable model provider; Gemini by default (Phase 2, Part B as revised by the owner on 2026-09-29).**
The owner won't pay for model usage, so the agent is evaluated on free providers: the Gemini API free tier, and Ollama serving an open-weight model on a self-hosted GPU session. The guardrails, the labelling and the semantic layer never depended on the model, and making the model swappable is how that gets proven and measured.
- **Interface** (`api/app/agent/providers.py`): the loop sends a system prompt, a provider-neutral transcript and the tool definitions. A provider returns one `Turn`: final text, tool calls, token usage, the model that served it, and a stop reason (`tool_use`, `end_turn`, `max_tokens`, `refusal`, `pause`). Failures raise `ProviderError` with a kind, so the eval never scores a dead server as a wrong answer:
  - `infrastructure`: unreachable, timed out, 5xx, or a proxy's error page;
  - `rate_limited`: 429, with its retry delay;
  - `rejected`: other 4xx.
- **Adapters, all hand-rolled; no agent framework, LangChain or LiteLLM:**
  - `AnthropicProvider` sends exactly the requests the loop sent before, and all its request-shape tests pass unchanged. It is unit-tested but was **not evaluated live**, because there is no Anthropic key.
  - `OpenAICompatProvider` speaks `/chat/completions` over `httpx2` (already installed) for both Gemini (Google's OpenAI-compatible endpoint) and Ollama (`/v1`).
    - The final answer arrives as a call to a `final_answer` tool whose parameters are the final-answer schema, because tool calling is the one capability both share. On the last round it's the only tool offered, and it's required.
    - Each assistant message is echoed back exactly as received, so Gemini's thought signatures survive, whatever field the compatibility layer puts them in.
    - `<think>` blocks are stripped.
    - Malformed tool arguments go back to the model as a tool error rather than crashing the loop.
    - Missing tool-call ids are filled in, on the echoed message too.
    - A final answer sent alongside other calls is refused back to the model.
- **Provider-neutral loop changes:**
  - A turn that ends without a readable final answer gets one nudge before it becomes an error. Weaker models often reply in prose.
  - A final answer inside a code fence is accepted.
  - A partial `chart_hint` is normalised.
- **Configuration:**
  - `CHANNELPULSE_PROVIDER` is `gemini` (default), `ollama` or `anthropic`.
  - Gemini reads `GEMINI_API_KEY` and `GEMINI_MODEL`. Ollama reads `OLLAMA_BASE_URL` and `OLLAMA_MODEL`, plus an optional `OLLAMA_API_TOKEN` sent as a bearer header.
  - `CHANNELPULSE_TEMPERATURE` defaults to 0.
  - An optional `*_REASONING_EFFORT` is sent as `reasoning_effort`.
  - The Ollama URL is treated as a secret: error messages never include it.
- **Cost:** traces and the spend cap price only Anthropic turns. Free-tier turns cost $0 and are reported in tokens. Traces gain a `provider` column.
- **Automation:** the CI guard now fails if any workflow references an Anthropic, Gemini, Google, Ollama or OpenAI variable. CI makes no model calls of any kind.
- **The public demo stays replay-only** (`render.yaml`: `ASK_LIVE=0`, provider `gemini`, key empty). Gemini's free tier may use prompts to improve Google's products; that's acceptable only because every row here is synthetic.
- **Adapter tests** (`api/tests/test_providers.py`, 33 tests) run on response fixtures through `httpx2.MockTransport`, and nothing reaches a model. The fixtures were hand-written in each provider's wire format before any live call; responses captured in the smoke run are added alongside them. Two deliberate breaks, dropping the thought signature and leaking the URL into an error, each made a test fail.

**D32. The eval runs on free tiers: pacing, resumable runs, and a raw text-to-SQL baseline (Part B).**
- **Modes:**
  - `--mode governed` is the agent as built.
  - `--mode raw` is the baseline a plain text-to-SQL agent gets: only `run_readonly_sql` and the mart schema. There is no metric glossary, semantic layer or anomaly detectors, but the same company prompt, the same refusal rules, the same final-answer format, the same SQL validator and the same row-level security.
  - The difference between the two modes, on the same model, is the measured lift from the semantic layer.
- **Raw-mode scoring:**
  - A multi-hop rubric's `evidence_tools` requirement is dropped: raw mode can't call `query_metric` or `get_anomalies`, so it's judged on what its answer says.
  - Every answer is expected to be `ad_hoc_sql_verify`, and traps refused.
  - Both rules make the comparison conservative: any measured lift is, if anything, understated.
- **Pacing** (`evals/throttle.py`):
  - Calls stay under 80% of the key's per-minute requests and tokens, and per-day requests.
  - A 429 is backed off using the server's `retryDelay`. A 429 on a per-day quota pauses the run at once.
  - Infrastructure failures are retried up to five times with growing waits, then the run pauses: unreachable, timed out, 5xx, or a tunnel's error page. A 5xx that says the prompt exceeds the served context is the question's own failure instead, since it would recur.
- **Resumable runs:**
  - Each (provider, mode, model) run saves its progress after every question in `evals/results/runs/<provider>__<mode>__<model>.json`. A paused run exits with code 4, and rerunning the same command picks up at the first unanswered question. `--fresh` starts over.
  - Nothing infrastructural is ever scored. Retries and rate-limit waits are counted per question and shown separately on the scorecard.
- **Recorded per question:** provider, mode, served model, input and output tokens (Gemini's thinking tokens counted as output), latency, `asked_at`, and the number of requests including retries.
- **Recorded per run:** the provider's settings. For Ollama that includes the server's `/api/show` facts (D35).
- **Cost:** free tiers cost $0, so the scorecard reports tokens per question rather than a made-up price. Only Anthropic turns are priced.
- **The spend gate stays:** only the paid provider asks for confirmation before spending. CI still makes no model calls of any kind.

**D33. The Gemini model is `gemini-3.5-flash-lite`, not 3.8 Flash (Part B, owner's decision 2026-09-29).**
- **Why:**
  - `gemini-3.8-flash` was approved first, but the owner's free tier gives it 5 RPM, 250K TPM and only **20 requests per day**. Google's 429 says so in its QuotaFailure: `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, limit 20. The owner reports that every Gemini Flash model on the key has the same daily cap.
  - A governed question takes several model calls, so 40 questions in two modes would need weeks at 20 a day.
  - `gemini-3.5-flash-lite` (version `3.5-flash-lite-07-2026`, from the models-list endpoint) gets 15 RPM, 250K TPM and **500 RPD** on the owner's key.
  - The eval throttles to 80% of those limits (12 RPM, 200K TPM, 400 RPD). They are the runner's defaults, and `GEMINI_RPM` / `GEMINI_TPM` / `GEMINI_RPD` override them.
- **Thinking:** left at the model's default, which Google's thinking docs give as "On (minimal)". It supports minimal, low, medium and high, and can't be turned off. Every run records it.
- **Tool calling verified:** a single tool-calling request through the OpenAI-compatible endpoint returned a proper `query_metric` call with valid arguments and a thought signature.
- **Discarded, not mixed:**
  - Two smoke questions had run on 3.8 Flash (SL01 and FG01, both scored correct) before the daily quota ran out. Their run file was deleted and is kept only in git history. No scorecard, case-study figure or recording uses them.
  - The 3.8 Flash reply captured as a test fixture stays: it tests the adapter's wire format, not the eval.
- **The API key was replaced** by the owner. It lives only in `.env`.
- **Two runner fixes came out of this:**
  - A 429 on a per-day quota now pauses the run at once. Before, it retried against the 23-second `retryDelay` that Google attaches even to daily limits.
  - Every model request, retries included, is counted per question. That count is what the day-budget estimate uses.

**D34. `get_anomalies` gets filters and view-aware ordering (Part B, owner-approved 2026-09-29, before the scored run).**
- **Found in the Gemini smoke run:** MH01 ("why did base-crack claims rise at Durgapur?") failed because the model never named the planted resin lot.
  - `get_anomalies` returned every detector's flags, 500 rows, ordered by detector name, and the model sees only the first 50 rows of any tool result.
  - The first 50 all came from `distributor_health`, so the lot-scan flag it needed was out of view.
  - The API endpoint already had a `detector` filter, but the agent's tool didn't expose it.
- **Change:**
  - The tool takes optional `detector` and `failure_mode` filters.
  - Unfiltered rows are ranked by effect size within each detector and interleaved across detectors, so the first rows hold every detector's strongest flags.
  - The tool description says the model sees only the first 50 rows.
- **On the real marts:** all four detectors appear in the first 50 unfiltered rows, and the planted lot is row 3. Filtered to `lot_scan` and `base_crack`, it is the only row.
- **What didn't change:** no detector rule, flag, metric or ground-truth parameter. This changes which rows reach the model, not what the detectors found. The smoke results were produced before the change and are reported as such; the scored runs come after it.

**D35. Qwen on Kaggle: what the server reports, and how thinking is really switched off (Part B, 2026-09-30).**
- **The model is served** by Ollama on a Kaggle GPU session (2x T4), behind a Cloudflare quick tunnel. The tunnel has no authentication, so there is no API key. Its URL changes every session and lives only in `.env`: it is never committed, logged or printed.
- **From the server's own `/api/show`, recorded with every run:**
  - tag `qwen3.8-27b-64k`, family `qwen35`, 27.3B parameters;
  - `Q4_K_M` quantization;
  - `num_ctx 65536`, where the model was trained for 262,144;
  - server-side temperature 0;
  - speculative decoding (MTP) with `draft_num_predict 2`;
  - thinking levels `false` / `low` / `medium` / `xhigh`, default `medium`.
- **Thinking off, as the owner decided.** Verified live: Ollama's OpenAI-compatible `/v1` **ignores `think: false`**, since the reply still carried a `reasoning` field, but honours `reasoning_effort: "none"`. With that, the `reasoning` field is gone and completion tokens drop from 180 to 99. So `OLLAMA_THINKING=off` sends `reasoning_effort: "none"`, and the run records `thinking: off (reasoning_effort=none)`. The eval uses temperature 0.
- **Tool calling verified** through `/v1`: a proper `query_metric` call with valid JSON arguments and a `call_...` id.
- **Smoke run** (5 questions, governed, before D36): 5 of 5 correct, including the trap refusal and correct labels. Median latency 43 s, p95 83 s, 34.8k input tokens per question, 0 infrastructure retries.
- **An earlier failure was infrastructure, not the model.** `.env` held a previous session's tunnel URL. First its hostname didn't resolve, then Cloudflare answered 530 (origin unreachable). Neither was scored.

**D36. The Indian fiscal year is a time grain in the semantic layer (Part B, owner-approved 2026-09-30).**
- **Why:**
  - Three of the four governed failures in Gemini's first scored run (TC01, TC05, TC07) asked about fiscal years.
  - The semantic layer offered only calendar grains, so the model grouped by `metric_time__year` (January to December) and either called calendar years fiscal ones or added quarters up itself.
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
- **Not changed:** no mart data, metric formula, detector or ground-truth parameter. Fiscal grains are for grouping; filters on them aren't supported, and date ranges do that job.
- **Reporting:** Gemini's governed run from before this change stays on record as the "before D36" result. A governed re-run after it is reported separately, and so are Qwen's governed runs, which use the fiscal grain from the start. Raw mode never uses the semantic layer, so it is unaffected.

**D37. Filters on two-hop dimensions were broken; fixed (Part B, 2026-09-30).**
- **Found in Gemini's governed re-run.** SL06 and FG04 filtered `claims_per_1000_units` by `batch__product__category` ("tanks"). Both calls errored, and the model fell back to its own SQL, with a different definition, and got the numbers wrong.
- **Root cause,** in `api/app/semantic.py`, the code that renders filters: it passed a multi-hop name straight into MetricFlow's filter syntax, `{{ Dimension('batch__product__category') }}`. MetricFlow can't parse that: the extra hop must be an entity path, as in `{{ Dimension('product__category', entity_path=['batch']) }}`.
- **It predates D36:** the same filter fails on the pre-D36 manifest. It had simply not been triggered in the earlier run.
- **Scope:** every offered two-hop dimension, 41 metric-and-dimension pairs, failed as a filter. Group-bys were never affected; they go through a different path.
- **Fix:** multi-hop names are rendered with `entity_path`. A new test compiles all 41 pairs as filters: all 41 fail with the fix disabled and pass with it.
- **Effect on results:** Gemini's two governed runs (before and after D36) and Qwen's governed run all ran with this bug, and are reported as run. A governed re-run after D37 would be a separate, labelled result.

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

