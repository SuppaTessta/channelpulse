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
web/ (Next.js 15): Executive KPIs · Distributor 360 · Batch cohort heatmap · Ask ChannelPulse · Weekly Brief · Agent traces
```

| Layer | What it is |
|---|---|
| Data | 36 months, 2023-10-01 to 2026-09-23, 1.84M raw rows. It's a simulator, not a CSV: four anomalies emerge from its rules. |
| Warehouse | dbt Core 1.12 on Postgres 17: 20 staging, 3 intermediate and 16 mart models, with 125 tests (schema plus business logic). |
| Semantic layer | dbt 1.12 inline semantic models: 13 semantic models, 51 metrics, including the 12 below, with calendar and Indian fiscal (April–March) time grains. MetricFlow compiles the SQL at query time. |
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
make test lint         # 850 Python tests (incl. the eval's free tier), ruff, dbt parse, eslint
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

**Two providers, two modes.** The same 102 questions ran on two free providers, each in two modes (D31, D32):
- **Governed** is the agent as built: the semantic layer, the anomaly detectors and the SQL fallback.
- **Raw** is a plain text-to-SQL baseline on the same model. It gets only `run_readonly_sql` and the mart schema, with the same prompt rules, refusal rules, SQL validator and row-level security.

The gap between the two modes on one model is what the semantic layer is worth.

| Provider | Model | Served as |
|---|---|---|
| Gemini API, free tier | `gemini-3.5-flash-lite`, thinking at its default (minimal), temperature 0 | Google's OpenAI-compatible endpoint (D33) |
| Ollama on a Kaggle GPU session (2x T4) | `qwen3.8-27b-64k`: Qwen3.8 27B, `Q4_K_M`, 64K context, thinking off, temperature 0 | a Cloudflare quick tunnel; the server's facts are read from `/api/show` and recorded (D35) |

Every row below comes from a committed run file in [`evals/results/runs/`](evals/results/runs); `make scorecard` regenerates the block. Free tiers cost $0, so cost is shown as tokens per question. Infrastructure retries (a dead tunnel, a 503) are counted, never scored. **Each result is a single run at temperature 0**, which doesn't make a model deterministic, so read small differences with care.

The current rows are golden set v2. Labelled rows are earlier runs kept on record:
- **`v1-40q`** is the first 40-question set;
- **before D36** and **after-D36-pre-D37** are governed runs from before the layer gained the fiscal-year grain (D36) and before filters on two-hop dimensions were fixed (D37).

<!-- scorecard:start -->
<!-- generated by `make scorecard` from evals/results/runs; don't edit by hand -->
| Provider / model | Mode | Run | Questions | Execution accuracy | Wrong answers | Ambiguous answered without asking | Traps answered | Traps refused: router + model | Latency median / p95 | Tokens / question (in / out) | Infra retries | Date |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gemini / `gemini-3.5-flash-lite` | governed | current | 102 | 88.2% | 8 | 12 of 16 | 0 | 9 + 9 of 9 | 12.4 s / 50.3 s | 46,326 / 302 | 0 | 2026-09-30 |
| gemini / `gemini-3.5-flash-lite` | raw | current | 102 | 72.1% | 19 | 14 of 16 | 1 | 9 + 8 of 9 | 8.1 s / 44.7 s | 10,899 / 393 | 1 | 2026-10-01 |
| ollama / `qwen3.8-27b-64k` | governed | current | 102 | 97.1% | 2 | 8 of 16 | 2 | 9 + 7 of 9 | 62.9 s / 220.4 s | 32,172 / 985 | 0 | 2026-09-30 |
| ollama / `qwen3.8-27b-64k` | raw | current | 102 | 69.1% | 20 | 6 of 16 | 0 | 9 + 9 of 9 | 59.1 s / 212.0 s | 7,970 / 973 | 0 | 2026-09-30 |
| gemini / `gemini-3.5-flash-lite` | governed | after-D36-pre-D37 | 40 | 84.4% | 5 | n/a | 1 | 0 + 7 of 8 | 7.1 s / 36.1 s | 43,921 / 310 | 0 | 2026-09-30 |
| gemini / `gemini-3.5-flash-lite` | governed | before-D36 | 40 | 87.5% | 4 | n/a | 0 | 0 + 8 of 8 | 9.0 s / 44.5 s | 40,670 / 304 | 1 | 2026-09-29 |
| gemini / `gemini-3.5-flash-lite` | governed | v1-40q | 40 | 93.8% | 2 | n/a | 1 | 0 + 7 of 8 | 5.8 s / 52.3 s | 52,079 / 356 | 0 | 2026-09-30 |
| gemini / `gemini-3.5-flash-lite` | raw | v1-40q | 40 | 71.9% | 9 | n/a | 2 | 0 + 6 of 8 | 7.5 s / 52.9 s | 11,865 / 481 | 0 | 2026-09-30 |
| ollama / `qwen3.8-27b-64k` | governed | v1-40q | 40 | 93.8% | 1 | n/a | 1 | 0 + 7 of 8 | 25.9 s / 146.0 s | 39,926 / 453 | 0 | 2026-09-30 |
| ollama / `qwen3.8-27b-64k` | raw | v1-40q | 40 | 56.2% | 10 | n/a | 1 | 0 + 7 of 8 | 25.5 s / 182.8 s | 14,482 / 622 | 0 | 2026-09-30 |

Execution accuracy by category:

| Run | ambiguous_clarify | filtered_grouped | multi_hop_why | simple_lookup | time_comparison | trap |
|---|---|---|---|---|---|---|
| gemini governed (current) | 25.0% | 94.4% | 71.4% | 88.9% | 94.4% | 100.0% |
| gemini raw (current) | 12.5% | 66.7% | 71.4% | 83.3% | 66.7% | 94.4% |
| ollama governed (current) | 50.0% | 100.0% | 92.9% | 94.4% | 100.0% | 88.9% |
| ollama raw (current) | 62.5% | 72.2% | 71.4% | 77.8% | 55.6% | 100.0% |
| gemini governed (after-D36-pre-D37) | n/a | 87.5% | 75.0% | 87.5% | 87.5% | 87.5% |
| gemini governed (before-D36) | n/a | 100.0% | 87.5% | 100.0% | 62.5% | 100.0% |
| gemini governed (v1-40q) | n/a | 100.0% | 75.0% | 100.0% | 100.0% | 87.5% |
| gemini raw (v1-40q) | n/a | 62.5% | 87.5% | 75.0% | 62.5% | 75.0% |
| ollama governed (v1-40q) | n/a | 100.0% | 87.5% | 100.0% | 87.5% | 87.5% |
| ollama raw (v1-40q) | n/a | 62.5% | 50.0% | 62.5% | 50.0% | 87.5% |

Governed against raw on the same model, question by question (answerable questions; each result is a single run at temperature 0):

| Model | Answerable questions | Wrong to right | Right to wrong | Both right | Both wrong | McNemar exact p |
|---|---|---|---|---|---|---|
| gemini / `gemini-3.5-flash-lite` | 68 | 15 | 4 (MH04, SL11, SL16, TC14) | 45 | 4 | 0.019 |
| ollama / `qwen3.8-27b-64k` | 68 | 20 | 1 (SL10) | 46 | 1 | 2.1e-05 |
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
- **Scope:** no real auth (the RLS stub only), and no forecasting. The Weekly Brief and the Agent traces page arrived in Phase 2 (D40, D41).
- **Claim rates are higher than a real manufacturer's**, to give the anomaly tests statistical power within the row budget (D19).
- **The inventory metrics are served weekly** (D24), and the deployed copy keeps only 60 days of daily inventory detail.
- **Some detector rules underperform**, as the case study reports, because they're kept pre-registered. The three 2024 lot-scan flags are false positives from thin peer data. The v1 stuffing rule is loose, and the v1 health rule flagged the churning account late. Detector v2 (D46, D47) improves both on the seed of record and on a holdout seed nobody had inspected. The product still serves v1, pending the owner's decision.
- **Refactors deferred, deliberately (D44).** The scored eval runs and their replay recordings must stay reproducible from the code that made them, and deployment comes first. These are future work:
  - `evals/run_eval.py`'s `main()`, 131 lines, could split into setup, run and report;
  - `generator/acceptance.py`, about 1,000 lines, and a few long generator functions (`tables.build_tables`, `fates.serial_fates`);
  - `web/components/quality-sections.tsx`, about 540 lines, could split by section;
  - `detectors/run.py`'s `lot_scan` and `installer_scan`, about 60 lines each.
- **GitHub disables scheduled workflows in public repos after 60 days without activity.** The daily refresh needs a periodic commit or a manual dispatch.
