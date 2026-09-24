# ChannelPulse

ChannelPulse is a portfolio project: a synthetic-but-realistic Indian building-products manufacturer, a dbt-modeled Postgres warehouse, a KPI dashboard, and a Claude-powered "ask your data" analyst that answers through a governed semantic layer, cites the SQL behind every answer, refuses what it can't answer, and is scored by a published evaluation harness. The point of the project is trust engineering, not a chatbot: a thin "LLM writes SQL against raw tables" wrapper is the thing this project is deliberately built to look nothing like. Same standard as the rest of this portfolio — ships in Docker, has tests, runs in CI, no notebooks as deliverables — applied here to structured business data instead of vision/RAG/regression.

> **All data is synthetic.** No real company, employer, or proprietary data, schema, or code is used anywhere in this repo.

*Status: Phase 0 (scaffold). Full docs arrive with Phase 1.*

## Quickstart

Requires Docker, Python 3.12, Node 24, and GNU make (Windows: `winget install ezwinports.make`).

```bash
cp .env.example .env   # optional: override ports/credentials (used by compose, dbt, and the API)
make setup             # .venv + Python deps, web deps
make up                # Postgres 17, waits until healthy
make seed              # synthetic data -> raw schema at the pinned as-of (idempotent, ~1 min)
make dbt-debug         # dbt -> Postgres connectivity
make api               # FastAPI on :$API_PORT (default 8000) -> GET /health
make web               # Next.js on :3000
make lint test
make down              # stop Postgres (data persists in the pgdata volume)
```

**Windows:** clone to a short path (e.g. `C:\src\channelpulse`) or enable Windows long-path support. dbt's dependencies install files deep enough that `make setup` fails when the repo path is longer than about 85 characters.
