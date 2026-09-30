# ChannelPulse

ChannelPulse is a portfolio project with four parts:
- a synthetic but realistic Indian building-products manufacturer;
- a dbt-modelled Postgres warehouse;
- a KPI dashboard;
- an "ask your data" analyst behind a swappable model provider (Gemini, a self-hosted open-weight model via Ollama, or Claude).

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
api/ (FastAPI): governed query_metric | guarded run_readonly_sql | get_anomalies | hand-rolled tool-use loop over any provider
web/ (Next.js 15): Executive KPIs · Distributor 360 · Batch cohort heatmap · Ask ChannelPulse
```

| Layer | What it is |
|---|---|
| Data | 36 months, 2023-10-01 to 2026-09-23, 1.84M raw rows. It's a simulator, not a CSV: four anomalies emerge from its rules. |
| Warehouse | dbt Core 1.12 on Postgres 17: 20 staging, 3 intermediate and 16 mart models, with 125 tests (schema plus business logic). |
| Semantic layer | dbt 1.12 inline semantic models: 13 semantic models, 50 metrics, including the 12 below, with calendar and Indian fiscal (April–March) time grains. MetricFlow compiles the SQL at query time. |
| Agent | A hand-rolled tool-use loop with five tools behind a thin provider interface (D31): Gemini by default (`gemini-3.5-flash-lite`, free tier), Ollama for a self-hosted open-weight model, or Anthropic's Claude, switched by `CHANNELPULSE_PROVIDER`. The Anthropic adapter is unit-tested but was **not evaluated live**; the scorecard below is Gemini and Qwen. Live answers are opt-in (`ASK_LIVE=1`); otherwise the Ask page replays answers recorded by the eval. |
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
make test lint         # 459 Python tests, ruff, dbt parse, eslint
make smoke             # browser smoke test of every page against the running API and dashboard (SMOKE_URL if not :3000)
make eval              # golden-set eval; with a key it prints an estimate and asks before spending (MODEL= BUDGET= YES=1)
make acceptance        # black-box check that the planted anomalies are in the data (slow: extra seeds)
make down
```

All Python runs from the repo-root `.venv`. Nothing needs a model key. Without a configured provider (or without `ASK_LIVE=1`), the Ask page shows replay mode: the answers recorded by the last full eval run, labelled with its date and model, or an honest empty state until one exists.

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
[`evals/questions.yaml`](evals/questions.yaml) holds 40 questions, 8 in each of five categories:
- simple lookup;
- filtered and grouped;
- time comparison;
- multi-hop "why", scored against a rubric of entities the golden SQL identifies;
- traps that must be refused: a forecast, data outside the marts, raw tables, a write, a prompt injection, "a number without SQL", off-topic, and personal data.

Golden answers come from hand-written SQL against the marts, never from the agent. The scorer reports:
- execution accuracy, with values matched within tolerance;
- refusal correctness;
- a confidently-wrong count;
- label correctness;
- latency and cost per query.

**Two providers, two modes.** The same 40 questions ran on two free providers, each in two modes (D31, D32):
- **Governed** is the agent as built: the semantic layer, the anomaly detectors and the SQL fallback.
- **Raw** is a plain text-to-SQL baseline on the same model. It gets only `run_readonly_sql` and the mart schema, with the same prompt rules, refusal rules, SQL validator and row-level security.

The gap between the two modes on one model is what the semantic layer is worth.

| Provider | Model | Served as |
|---|---|---|
| Gemini API, free tier | `gemini-3.5-flash-lite`, thinking at its default (minimal), temperature 0 | Google's OpenAI-compatible endpoint (D33) |
| Ollama on a Kaggle GPU session (2x T4) | `qwen3.8-27b-64k`: Qwen3.8 27B, `Q4_K_M`, 64K context, thinking off, temperature 0 | a Cloudflare quick tunnel; the server's facts are read from `/api/show` and recorded (D35) |

Every row below comes from a committed run file in [`evals/results/runs/`](evals/results/runs); `make scorecard` regenerates the block. Free tiers cost $0, so cost is shown as tokens per question. Infrastructure retries (a dead tunnel, a 503) are counted, never scored. Rows labelled with a D-entry are earlier runs kept on record: the governed layer changed between them.
- **D36** added the fiscal-year grain.
- **D37** fixed filters on two-hop dimensions.

The current governed rows run after both.

<!-- scorecard:start -->
<!-- generated by `make scorecard` from evals/results/runs; don't edit by hand -->
| Provider / model | Mode | Run | Execution accuracy | Refusal correctness | Confidently wrong | Latency median / p95 | Tokens / question (in / out) | Infra retries | Date |
|---|---|---|---|---|---|---|---|---|---|
| gemini / `gemini-3.5-flash-lite` | raw | current | 71.9% | 95.0% | 11 | 7.5 s / 52.9 s | 11,865 / 481 | 0 | 2026-09-30 |
| ollama / `qwen3.8-27b-64k` | raw | current | 56.2% | 97.5% | 11 | 25.5 s / 182.8 s | 14,482 / 622 | 0 | 2026-09-30 |
| gemini / `gemini-3.5-flash-lite` | governed | after-D36-pre-D37 | 84.4% | 97.5% | 6 | 7.1 s / 36.1 s | 43,921 / 310 | 0 | 2026-09-30 |
| gemini / `gemini-3.5-flash-lite` | governed | before-D36 | 87.5% | 100.0% | 4 | 9.0 s / 44.5 s | 40,670 / 304 | 1 | 2026-09-29 |

Execution accuracy by category:

| Run | filtered_grouped | multi_hop_why | simple_lookup | time_comparison | trap |
|---|---|---|---|---|---|
| gemini raw (current) | 62.5% | 87.5% | 75.0% | 62.5% | 75.0% |
| ollama raw (current) | 62.5% | 50.0% | 62.5% | 50.0% | 87.5% |
| gemini governed (after-D36-pre-D37) | 87.5% | 75.0% | 87.5% | 87.5% | 87.5% |
| gemini governed (before-D36) | 100.0% | 87.5% | 100.0% | 62.5% | 100.0% |
<!-- scorecard:end -->

To run it yourself: `make eval PROVIDER=gemini MODE=governed` (or `raw`; `PROVIDER=ollama`, `ONLY=SL01,TC01`, `FRESH=1`). Runs are paced to 80% of the key's quota, save after every question, and resume where they stopped when a daily quota or a server runs out (exit 4). The Anthropic provider asks for confirmation before spending (`BUDGET=`, `YES=1`). CI runs the eval without any model credential (a test enforces it), so there it only validates the golden answers.

## Anomaly detection
The data contains planted anomalies, and the pre-registered detectors look for them blind. The full story, including the detectors' false positives and the one detector that fired late, is in the [case study](docs/case-study.md). It contains spoilers, so read the dashboard first if you want to find them yourself.

## Cost
- **Per Ask question:** $0 on the free tiers used for the scorecard; the table gives the measured tokens per question. On Claude, the only paid provider, `make eval` prints an estimate and asks before spending; no Claude run has been made.
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
- **Replay by default:** the public demo never calls a model unless you set both a provider key (e.g. `GEMINI_API_KEY`) and `ASK_LIVE=1` on Render. In live mode, the per-IP rate limit and the daily spend cap apply to every question (D29).
- **Not deployed yet.** The steps, in order, are in [docs/deploy-checklist.md](docs/deploy-checklist.md), starting with `make identity-check` before anything is pushed publicly.
  - The repository needs three secrets: `SUPABASE_DB_URL`, `AGENT_DB_PASSWORD` and `OPS_DB_PASSWORD`.
  - A model key never goes into GitHub: a test fails if any workflow references one.

## Known limitations
- **Phase 1 scope:** no real auth (the RLS stub only), no forecasting, and no Weekly Brief generator (PLAN §11).
- **Claim rates are higher than a real manufacturer's**, to give the anomaly tests statistical power within the row budget (D19).
- **The inventory metrics are served weekly** (D24), and the deployed copy keeps only 60 days of daily inventory detail.
- **Some detector rules underperform**, as the case study reports, because they're kept pre-registered. The three 2024 lot-scan flags are false positives from thin peer data. The stuffing rule is loose. The health rule flagged the churning account late.
- **GitHub disables scheduled workflows in public repos after 60 days without activity.** The daily refresh needs a periodic commit or a manual dispatch.
