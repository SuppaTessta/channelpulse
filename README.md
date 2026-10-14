# ChannelPulse

ChannelPulse is a portfolio project with four parts:
- a synthetic but realistic Indian building-products manufacturer;
- a dbt-modelled Postgres warehouse;
- a KPI dashboard;
- an "ask your data" analyst running on Anthropic's Claude (Sonnet 5.5 by default, Haiku 5.5 as the comparison model).

The analyst answers through a governed semantic layer, cites the SQL behind every answer, refuses what it can't answer, and is scored by a published evaluation harness. The point is trust engineering, not a chatbot: the project is deliberately built to look nothing like a thin "LLM writes SQL against raw tables" wrapper. It holds the same standard as the rest of the portfolio: it ships in Docker, has tests, runs in CI, and has no notebooks as deliverables.

> **All data is synthetic. No employer data, schema or code was used.** No real company's data, schema, code or identifying information appears anywhere in this repo. The company, Gangasagar Polymers Pvt. Ltd. of Kolkata, is fictional. Place names are public geography, and pincodes are synthetic.

## The problem
A mid-size manufacturer that sells through distributors sees its own invoices (sell-in) immediately. Sell-out, channel stock, warranty failures and collections arrive late, partially and in different systems. The expensive problems hide in those gaps:
- a bad production lot shows up as claims months later;
- a distributor quietly losing share keeps being loaded with stock;
- quarter-end schemes pull demand forward;
- one bad installer looks like a product defect.

An analyst tool is only useful here if its numbers are right and provably so. That means governed definitions, the exact SQL shown for every figure, refusals when it can't know, and a measured error rate.

## Architecture
See [docs/architecture.md](docs/architecture.md) for the full diagram and trust boundaries.

```
generator/ (rules-based simulator) -> raw -> dbt staging -> intermediate -> marts (RLS)
                                                          semantic_models/ -> MetricFlow (compile-only, in the API)
detectors/ (pre-registered scans) -> marts.mart_anomaly_flags
api/ (FastAPI): governed query_metric | guarded run_readonly_sql | get_anomalies | hand-rolled tool-use loop on Anthropic's Messages API
web/ (Next.js 15): Executive KPIs · Distributor 360 · Batch cohort heatmap · Ask ChannelPulse · Weekly Brief · Agent traces
```

| Layer | What it is |
|---|---|
| Data | 36 months, 2023-10-01 to 2026-09-23, 1.84M raw rows. It's a simulator, not a CSV: four anomalies emerge from its rules. |
| Warehouse | dbt Core 1.12 on Postgres 17: 20 staging, 3 intermediate and 16 mart models, with 125 tests (schema plus business logic). |
| Semantic layer | dbt 1.12 inline semantic models: 13 semantic models, 51 metrics, including the 12 below, with calendar and Indian fiscal (April–March) time grains. MetricFlow compiles the SQL at query time. |
| Agent | A hand-rolled tool-use loop with five tools on Anthropic's Messages API (D50): `claude-sonnet-5-5` at `medium` effort by default (`CHANNELPULSE_MODEL`, `CHANNELPULSE_EFFORT`), and `claude-haiku-5-5` as the comparison model. Live answers are opt-in (`ASK_LIVE=1`); otherwise the Ask page replays answers recorded by the eval. |
| Guardrails | A read-only Postgres role (marts only), Postgres RLS by region, a sqlglot validator, a rate limit, a daily spend cap, and a trace of every question. |

## Quickstart
Requires Docker, Python 3.12, Node 24 and GNU make (Windows: `winget install ezwinports.make`).

```bash
cp .env.example .env   # optional: override ports/credentials
make setup             # .venv + Python deps, web deps (~2 min)
make up                # Postgres 17, waits until healthy
make seed              # synthetic data -> raw (idempotent, ~1 min)
make dbt               # build + test the warehouse, run the detectors, apply the API's DB roles (~6 min)
make api               # FastAPI on :$API_PORT (default 8000)
make web               # dashboard dev server on :3000 (set NEXT_PUBLIC_API_URL if the API isn't on :8000)
make web-start         # or: production build, then serve it (restart it after every rebuild)
make test lint         # 800 Python tests (incl. the eval's free tier), ruff, dbt parse, eslint
make smoke             # browser smoke test of every page against the running API and dashboard (SMOKE_URL if not :3000)
make eval              # golden-set eval on Claude; prints an estimated cost and asks before spending (MODE= MODEL= BUDGET= YES=1)
make acceptance        # black-box check that the planted anomalies are in the data (slow: extra seeds)
make down
```

All Python runs from the repo-root `.venv`. Nothing needs a model key except `make eval` and live mode. Without both `ANTHROPIC_API_KEY` and `ASK_LIVE=1`, the Ask page shows replay mode: the answers recorded by the last full eval run, labelled with its date and model, or an honest empty state until one exists. No Claude run has been recorded yet, so for now it's the empty state.

Timings are from a clean clone on the Windows build machine (decisions E2); the sequence above was run end to end there, finishing with `make smoke`.

**A second copy alongside the first:** Docker Compose names its project, container and data volume after the folder, so a clone in another folder gets its own Postgres volume. Give it a free `POSTGRES_PORT` and `API_PORT` in its `.env`, point `web/.env.local` at that API, and serve the dashboard on another port (`npm --prefix web run start -- -p 3100`, then `SMOKE_URL=http://127.0.0.1:3100 make smoke`).

**Ports:** if something else already holds port 8000, set `API_PORT` in `.env` and `NEXT_PUBLIC_API_URL=http://127.0.0.1:<port>` in `web/.env.local`. `NEXT_PUBLIC_API_URL` is compiled into the browser code, so rebuild after changing it. `make smoke` reads `API_PORT` too, and fails with a clear message if the API or the dashboard server is older than the code (decisions D28).

**Windows:**
- Clone to a short path (e.g. `C:\src\channelpulse`), because dbt's dependencies exceed MAX_PATH beyond about 85 characters of repo path.
- Smart App Control can block brand-new native wheels (decisions E1).
- `make smoke` drives the installed Microsoft Edge locally, so Playwright needs no browser download (CI uses Playwright's Chromium).

## Metric glossary
Each metric is defined once in [`warehouse/semantic_models/`](warehouse/semantic_models). The dashboard and the agent's `query_metric` both compile from those definitions.

| Metric | Definition | Grain |
|---|---|---|
| `primary_sales_value` | Σ invoice-line qty × unit price (sell-in, net of scheme discounts) | day / distributor / sku / region |
| `secondary_sales_value` | Σ secondary qty × current list price (sell-out) | day / distributor / sku / region |
| `channel_days_of_stock` | (cumulative primary − cumulative secondary) ÷ trailing-30-day average daily secondary, in units, read on the last day of the period | distributor / sku / week |
| `claims_per_1000_units` | claims ÷ (serials shipped in the cohort ÷ 1000) | batch / plant / sku / manufacture period |
| `dso` | Amount-weighted days from invoice to full payment; open invoices age to the as-of date | distributor / period |
| `distributor_health_score` | 0–100 weighted region-peer percentiles: sell-out trend 35%, sell-in vs sell-out gap 20%, days-of-stock deviation 15%, DSO trend 20%, visit recency 10% | distributor / week |
| `stockout_rate` | Share of distributor-SKU-days with under 7 days of stock | region / period |
| `overstock_rate` | Share of distributor-SKU-days with over 60 days of stock | region / period |
| `scheme_concentration_ratio` | Share of quarterly sell-in booked in the 15-day scheme window ÷ the distributor's own baseline share (median of its other quarters) | distributor / quarter |
| `warranty_registration_rate` | Share of serials shipped ≥ 90 days ago with an install date within 90 days of shipment | plant / period |
| `collections_efficiency` | Collected within terms ÷ invoiced, over invoices already due | distributor / period |
| `installer_claim_rate` | `claims_per_1000_units` by installer instead of batch | installer / district / period |

Thresholds are documented and defensible, not tuned:
- 7 and 60 days of stock, against a 30-day target cover;
- the health-score weights and flag rule, pre-registered in [`detectors/detectors.yaml`](detectors/detectors.yaml) before any data existed.

## Data dictionary
- **raw** (the generator's landing tables, [`generator/schema.sql`](generator/schema.sql)): plants, products, production batches and resin lots, serialised units, distributors, retailers, sales reps, schemes, primary invoices and lines, secondary sales (with reporting lag and re-sent duplicates), shipments, installations, installers, warranty claims, collections, field visits, geography, opening channel stock.
- **marts** (the only schema the agent and dashboard may read):

| Mart | Grain |
|---|---|
| `dim_distributor`, `dim_product`, `dim_batch`, `dim_geo`, `dim_date` | one row per entity; `dim_date` is the time spine |
| `fct_primary_sales` / `fct_secondary_sales` | invoice line / reported sell-out record |
| `fct_channel_inventory_daily` | distributor × sku × day (detail) |
| `mart_channel_inventory_weekly` | distributor × sku × week (serves the inventory metrics) |
| `fct_invoice_collections` | invoice, with payment status as of the as-of date |
| `fct_warranty_claims` | claim, with full unit lineage |
| `fct_field_visits` | rep visit |
| `mart_batch_claim_cohorts` | batch × months since shipment (the heatmap) |
| `mart_installer_claim_cohorts` | installer × district × install month × months since install |
| `mart_distributor_health_weekly` | distributor × week, point-in-time |
| `mart_scheme_quarterly` | distributor × scheme window × category |
| `mart_anomaly_flags` | detector output for `get_anomalies` |

Every column and test is in the dbt YAML: `dbt docs generate --project-dir warehouse --profiles-dir warehouse`.

## Design decisions and trade-offs
All of them, with the plan text each one touches, are in [docs/decisions.md](docs/decisions.md). The load-bearing ones:

- **A semantic layer plus a guarded fallback, rather than either alone.**
  - A semantic layer alone refuses every question a metric doesn't cover, which is most real questions.
  - Raw text-to-SQL alone is fluent and unverifiable.
  - So the agent must use `query_metric`, which compiles from the governed definitions, whenever a metric fits. It falls back to `run_readonly_sql` only when none does, and that answer is labelled `ad_hoc_sql_verify` so the reader knows to check it. The label is chosen by code from the tool calls that actually ran, not by the model.
- **Real MetricFlow, compile-only** (D20). The definitions use dbt's own semantic spec, and MetricFlow's engine compiles them inside the API from the shipped manifest, with no dbt adapter at runtime. SQL is executed by our read-only role, so row-level security still applies.
- **A hand-rolled agent, not a framework.** The loop, prompt, response assembly and tracing are about 450 lines of explicit code around the Messages API. That's where the guarantees live:
  - strict tool schemas;
  - a structured final turn;
  - the numbers check that traces every figure to returned data;
  - response assembly from executed calls;
  - per-call traces.

  Frameworks hide exactly these seams, and each one here is unit-tested.
- **Guardrails at the database, not just in code.** The agent's role can only read marts, in read-only transactions with a statement timeout. Region claims are Postgres RLS policies. The validator is defence in depth: it rejects writes before they reach Postgres at all.
- **Pre-registered detectors** (D18). Every anomaly rule was committed before any data was generated, with Bonferroni-controlled scans that don't name entities. Results are reported as they fell, false positives included.
- **A simulator, not a dataset.** Anomalies emerge from rules (hazard multipliers, ordering behaviour), are verified by a black-box acceptance suite against a same-seed counterfactual run, and leave no tells in the data.
- **Point-in-time.** The weekly health score only uses what was visible that week, including reporting lag, so "flagged N weeks early" is an honest claim.

## Evaluation
[`evals/questions.yaml`](evals/questions.yaml) holds 102 questions in six categories (golden set v2, D39):
- 18 simple lookups;
- 18 filtered and grouped;
- 18 time comparisons;
- 14 multi-hop "why", scored against a rubric of entities the golden SQL identifies;
- 18 traps that must be refused: forecasts, data outside the marts, raw and system tables, writes, prompt injection, "a number without SQL", off-topic questions, and personal data;
- 16 ambiguous questions whose right answer is a clarifying question. Each has two or three readings with their own golden SQL, and the readings must give different answers.

Golden answers come from hand-written SQL against the marts, never from the agent. There are two tiers:
- **Free tier** (`make eval-free`, in CI on every PR, no model). Every governed question's hand-written `query_metric` call must reproduce its golden. Every trap's attack SQL must be rejected by the validator. The model-free refusal router must refuse exactly the marked traps.
- **Model suite** (`make eval`, manual only). It reports execution accuracy on the 68 answerable questions against an 85% threshold. "Confidently wrong" is split into its three failures: wrong answers, ambiguous questions answered without asking, and traps answered. Trap refusals are split into those the router makes before any model call and those the model makes itself. Label correctness, latency and tokens are reported too.

The model suite runs in two modes on the same model. **Governed** is the agent as built: the semantic layer, the anomaly detectors and the SQL fallback. **Raw** is a plain text-to-SQL baseline that gets only `run_readonly_sql` and the mart schema, with the same prompt rules, refusal rules, SQL validator and row-level security. The gap between the two modes is what the semantic layer is worth.

**No scored run yet.** The Claude runs come next, Sonnet 5.5 and Haiku 5.5, governed and raw, on the same 102 questions, and their results will appear in the block below.

<!-- scorecard:start -->
<!-- generated by `make scorecard` from evals/results/runs; don't edit by hand -->
No complete eval run yet.
<!-- scorecard:end -->

To run it yourself: `make eval MODE=governed` (or `MODE=raw`; `MODEL=claude-haiku-5-5` for the comparison model; `ONLY=SL01,TC01`, `FRESH=1`, `THRESHOLD=`). `make eval` prints an estimated cost and asks before spending; `BUDGET=` (USD) stops a run once it's spent, and `YES=1` skips the question. Runs save after every question and resume when the same command is rerun. A run stops with its progress saved (exit 4) when the API is unreachable, overloaded, rate-limited or out of credit. CI runs the eval without any model credential (a test enforces it), so there it only validates the golden answers.

## Anomaly detection
The data contains planted anomalies, and the pre-registered detectors look for them blind. The full story, including the detectors' false positives and the one detector that fired late, is in the [case study](docs/case-study.md). It contains spoilers, so read the dashboard first if you want to find them yourself.

## Cost
- **Per eval run:** the harness estimates one full run of 102 questions in one mode at about $10 on Sonnet 5.5 and about $0.50 on Haiku 5.5, before its 1.25x safety margin. These are the harness's estimates, not measurements: no Claude run has been made.
- **Guardrails on spend:** a per-IP rate limit (6/minute) and a daily spend cap ($5 default, $2 in `render.yaml`), computed from the traced cost.
- **Infrastructure:** free tiers. Render (API), Vercel (web), Supabase (marts only, about 400 MB), and GitHub Actions (CI plus the daily refresh).

## Security model
- **Least-privilege roles** ([`api/sql/roles.sql`](api/sql/roles.sql)):
  - `channelpulse_agent` has read-only access to marts, a 5 s default statement timeout (10 s inside API transactions), and `search_path = marts`;
  - `channelpulse_ops` can only insert and select traces;
  - PUBLIC defaults are revoked.
- **Region RLS on every distributor-level mart.** The claim comes from `X-Demo-Region`. This is a stub with no real authentication, suited to a public synthetic demo.
- **SQL fallback:** a sqlglot AST validator (one SELECT on allow-listed marts; no write verbs, catalogs, dangerous functions or data-modifying CTEs; capped rows), then execution on the read-only role.
- **Governed filters are injection-hardened:** values are validated literals, and Jinja braces are rejected, because MetricFlow renders filters as Jinja. The compiled SQL also passes the validator.
- **Answers:** an answer with no data evidence behind it is withheld and labelled refused.
- **Secrets:** none are committed; `.env` is gitignored. The deployment uses per-role passwords from secrets.

## Deployment
- **Topology** (decisions D25): the web app on Vercel from `web/`; the API on Render from [`render.yaml`](render.yaml); Supabase holding only the `marts` schema, reached through its Session pooler.
- **The daily job** ([`daily.yml`](.github/workflows/daily.yml)) regenerates the simulation through yesterday in a throwaway CI Postgres, rebuilds and tests it, runs the detectors, and publishes `marts`. This keeps the demo current and the Supabase project awake.
- **Replay by default:** the public demo never calls a model unless you set both `ANTHROPIC_API_KEY` and `ASK_LIVE=1` on Render. In live mode, the per-IP rate limit and the daily spend cap apply to every question (D29).
- **Not deployed yet.** The steps, in order, are in [docs/deploy-checklist.md](docs/deploy-checklist.md), starting with `make identity-check` before anything is pushed publicly.
  - The repository needs three secrets: `SUPABASE_DB_URL`, `AGENT_DB_PASSWORD` and `OPS_DB_PASSWORD`.
  - A model key never goes into GitHub: a test fails if any workflow references one.

## Known limitations
- **Scope:** no real auth (the RLS stub only), and no forecasting. The Weekly Brief and the Agent traces page arrived in Phase 2 (D40, D41).
- **Claim rates are higher than a real manufacturer's**, to give the anomaly tests statistical power within the row budget (D19).
- **The inventory metrics are served weekly** (D24), and the deployed copy keeps only 60 days of daily inventory detail.
- **Some detector rules underperform**, as the case study reports, because they're kept pre-registered. The three 2024 lot-scan flags are false positives from thin peer data. The v1 stuffing rule is loose, and the v1 health rule flagged the churning account late. Detector v2 (D46, D47) improves both on the seed of record and on a holdout seed nobody had inspected, and it's in production since D48. The holdout churn flag lands only 6 days before its target, and stuffers in their overhang still cross the health flag more often than the acceptance target allows.
- **Refactors deferred, deliberately (D44).** Deployment comes first. These are future work:
  - `evals/run_eval.py`'s `main()`, 131 lines, could split into setup, run and report;
  - `generator/acceptance.py`, about 1,000 lines, and a few long generator functions (`tables.build_tables`, `fates.serial_fates`);
  - `web/components/quality-sections.tsx`, about 540 lines, could split by section;
  - `detectors/run.py`'s `lot_scan` and `installer_scan`, about 60 lines each.
- **GitHub disables scheduled workflows in public repos after 60 days without activity.** The daily refresh needs a periodic commit or a manual dispatch.
