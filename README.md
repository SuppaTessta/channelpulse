# ChannelPulse

ChannelPulse is a portfolio project with four parts:
- a synthetic but realistic Indian building-products manufacturer;
- a dbt-modelled Postgres warehouse;
- a KPI dashboard;
- a Claude-powered "ask your data" analyst.

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
api/ (FastAPI): governed query_metric | guarded run_readonly_sql | get_anomalies | hand-rolled Claude loop
web/ (Next.js 15): Executive KPIs · Distributor 360 · Batch cohort heatmap · Ask ChannelPulse
```

| Layer | What it is |
|---|---|
| Data | 36 months, 2023-10-01 to 2026-09-23, 1.84M raw rows. It's a simulator, not a CSV: four anomalies emerge from its rules. |
| Warehouse | dbt Core 1.12 on Postgres 17: 20 staging, 3 intermediate and 16 mart models, with 123 tests (schema plus business logic). |
| Semantic layer | dbt 1.12 inline semantic models: 13 semantic models, 50 metrics, including the 12 below. MetricFlow compiles the SQL at query time. |
| Agent | Claude (`claude-opus-5`, adaptive thinking, server-side refusal fallback) in a hand-rolled tool-use loop with five tools. |
| Guardrails | A read-only Postgres role (marts only), Postgres RLS by region, a sqlglot validator, a rate limit, a daily spend cap, and a trace of every question. |

## Quickstart
Requires Docker, Python 3.12, Node 24 and GNU make (Windows: `winget install ezwinports.make`).

```bash
cp .env.example .env   # optional: override ports/credentials
make setup             # .venv + Python deps, web deps
make up                # Postgres 17, waits until healthy
make seed              # synthetic data -> raw (idempotent, ~4 min)
make dbt               # build + test the warehouse, run the detectors, apply the API's DB roles (~5-8 min)
make api               # FastAPI on :$API_PORT (default 8000)
make web               # dashboard on :3000 (set NEXT_PUBLIC_API_URL if the API isn't on :8000)
make test lint         # 456 Python tests, ruff, dbt parse, eslint
make eval              # golden-set eval; scores the agent when ANTHROPIC_API_KEY is set
make acceptance        # black-box check that the planted anomalies are in the data (slow: extra seeds)
make down
```

All Python runs from the repo-root `.venv`. The Ask panel needs `ANTHROPIC_API_KEY`; everything else runs without it.

**Windows:**
- Clone to a short path (e.g. `C:\src\channelpulse`), because dbt's dependencies exceed MAX_PATH beyond about 85 characters of repo path.
- Smart App Control can block brand-new native wheels (decisions E1).

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

**Scorecard: not yet run.** This build machine has no Anthropic credentials. All 32 golden answers validate against the live marts, and the 21 governed goldens also match the semantic layer's own answers (`evals/results/latest.json`, `status: not_run`). No agent numbers are shown here because none exist yet. To produce the scorecard:
```bash
export ANTHROPIC_API_KEY=...        # a full run costs about $4-7 with claude-opus-5 (estimate)
make eval                           # or: python evals/run_eval.py --budget-usd 8 [--model claude-sonnet-5]
```
CI's `warehouse` job runs the same eval, and scores it when the repo has an `ANTHROPIC_API_KEY` secret.

## Anomaly detection
The data contains planted anomalies, and the pre-registered detectors look for them blind. The full story, including the detectors' false positives and the one detector that fired late, is in the [case study](docs/case-study.md). It contains spoilers, so read the dashboard first if you want to find them yourself.

## Cost
- **Per Ask question:** about 3–5 model calls on `claude-opus-5` ($5 / $25 per million input/output tokens). A cached prompt prefix of about 13–15k tokens (tools, rules, metric glossary) is billed at the cache-read rate after the first call. The estimate is about $0.10–0.18 per question; the eval will measure it.
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
- **Topology** (decisions D25): the web app on Vercel from `web/`; the API on Render from [`render.yaml`](render.yaml); Supabase holding only the `marts` schema.
- **The daily job** ([`daily.yml`](.github/workflows/daily.yml)) regenerates the simulation through yesterday in a throwaway CI Postgres, rebuilds and tests it, runs the detectors, and publishes `marts`. This keeps the demo current and the Supabase project awake.
- **Not deployed yet.** It needs the owner's Render, Vercel and Supabase accounts, plus these repository secrets: `SUPABASE_DB_URL`, `AGENT_DB_PASSWORD`, `OPS_DB_PASSWORD` and `ANTHROPIC_API_KEY`.

## Known limitations
- **Phase 1 scope:** no real auth (the RLS stub only), no forecasting, and no Weekly Brief generator (PLAN §11).
- **Claim rates are higher than a real manufacturer's**, to give the anomaly tests statistical power within the row budget (D19).
- **The inventory metrics are served weekly** (D24), and the deployed copy keeps only 60 days of daily inventory detail.
- **Some detector rules underperform**, as the case study reports, because they're kept pre-registered. The three 2024 lot-scan flags are false positives from thin peer data. The stuffing rule is loose. The health rule flagged the churning account late.
- **GitHub disables scheduled workflows in public repos after 60 days without activity.** The daily refresh needs a periodic commit or a manual dispatch.
