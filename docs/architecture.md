# Architecture

```mermaid
flowchart LR
    subgraph gen["generator/ (Python, rules-based simulator)"]
        cfg[config.yaml<br/>ground_truth.yaml]
        sim[generate.py]
        cfg --> sim
    end

    subgraph pg["Postgres 17"]
        raw[(raw<br/>20 tables, ~1.86M rows)]
        stg[(staging<br/>1:1 views, dedup)]
        int[(intermediate<br/>calendar, serials, daily series)]
        marts[(marts<br/>dims, facts, cohorts, health,<br/>anomaly flags. RLS by region)]
        ops[(ops<br/>agent_traces)]
    end

    subgraph dbt["warehouse/ (dbt 1.12)"]
        models[models + 160 tests]
        sem[semantic_models/<br/>13 semantic models, 49 metrics]
    end

    det[detectors/<br/>pre-registered scans]

    subgraph api["api/ (FastAPI)"]
        mf[MetricFlow engine<br/>compile-only]
        val[sqlglot validator]
        loop[hand-rolled Claude<br/>tool-use loop]
        tools[list_metrics · query_metric ·<br/>run_readonly_sql · get_anomalies ·<br/>explain_metric]
    end

    web[web/ Next.js 15<br/>4 dashboard pages]
    claude([Claude API<br/>claude-opus-5])

    sim -- COPY --> raw
    raw --> stg --> int --> marts
    models -. builds .-> marts
    sem -. semantic_manifest.json .-> mf
    marts --> det -- mart_anomaly_flags --> marts
    loop <--> claude
    loop --> tools
    tools --> mf
    tools --> val
    mf -- "SELECT as channelpulse_agent<br/>(read-only, marts only, RLS)" --> marts
    val -- same role --> marts
    loop -- traces as channelpulse_ops --> ops
    web -- "/api/metrics/query<br/>/api/ask · /api/anomalies" --> api
```

## Trust boundaries
- **The agent never sees raw data.** `channelpulse_agent` has `USAGE` on `marts` only and `SELECT` on its tables. It defaults to read-only transactions with a statement timeout and `search_path = marts`. Postgres enforces all of this, not application code.
- **Region claims are enforced by Postgres row-level security.** Every distributor-level mart has a policy keyed on `current_setting('app.region')`. The API sets it per transaction from the `X-Demo-Region` header. This is a stub: there is no real authentication.
- **Governed first.** `query_metric` compiles SQL from the semantic definitions: MetricFlow, running in-process with no database access. It also passes the compiled SQL through the same validator as the ad-hoc path.
- **Ad-hoc SQL is the fallback.** `run_readonly_sql` goes through a sqlglot AST validator before any database call:
  - it allows a single SELECT on allow-listed marts;
  - it rejects write verbs, catalog access, dangerous functions and data-modifying CTEs;
  - it caps rows.

  The model sees the result labelled `ad_hoc_sql_verify`.
- **Code, not the model, labels the answer.** The final response's SQL, data and `governed_metric` / `ad_hoc_sql_verify` / `refused` label are built from the tool calls that actually ran. A numbers check traces every figure in the answer back to returned data.
- **Anomalies are computed, not invented.** `get_anomalies` returns rows the pre-registered detectors wrote. The LLM only narrates them.
- **Every question is traced.** `ops.agent_traces` records the question, tool calls, SQL, row counts, tokens, latency and estimated cost, written by the separate `channelpulse_ops` role.

## Data flow per request
1. The dashboard calls `POST /api/metrics/query`.
2. MetricFlow compiles the SQL.
3. The SQL is validated.
4. It executes as the agent role with the region claim set.
5. The API returns the rows and the exact SQL, labelled `governed_metric`.

The Ask panel's agent uses the same function through the `query_metric` tool, so the dashboard and the agent can't disagree about a metric.

## Deployment (decisions D25)
- **Web:** Vercel, deployed from `web/`.
- **API:** Render, as the Docker image from `api/`, via `render.yaml`.
- **Database:** Supabase, holding only the `marts` schema. The daily GitHub Action regenerates the data through yesterday (IST) in a throwaway Postgres, rebuilds and tests the warehouse, runs the detectors, and publishes `marts`. Raw data never leaves CI.
