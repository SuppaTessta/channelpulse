"""Runtime settings, read from the environment at startup."""

import os

env = os.environ.get

# Which model provider answers (decisions D31): gemini (default), ollama or anthropic. Each reads its own settings:
# gemini GEMINI_API_KEY + GEMINI_MODEL; ollama OLLAMA_BASE_URL + OLLAMA_MODEL (+ OLLAMA_API_TOKEN); anthropic the
# SDK's credentials + CHANNELPULSE_MODEL below.
DEFAULT_PROVIDER = "gemini"
PROVIDER = env("CHANNELPULSE_PROVIDER", DEFAULT_PROVIDER).strip().lower()
GEMINI_MODEL = "gemini-3.8-flash"  # pending the owner's confirmation (Part B)

# Anthropic only. Owner-approved default (Phase 2, A3; decisions D29). Opus 5.5 at medium effort: Anthropic reports it beating
# Opus 5 at high on analysis work, and medium is its own API default.
MODEL = env("CHANNELPULSE_MODEL", "claude-opus-5-5")
EFFORT = env("CHANNELPULSE_EFFORT", "medium")
MAX_TOKENS = 16_000
MAX_TOOL_ROUNDS = int(env("AGENT_MAX_TOOL_ROUNDS", "8"))
AGENT_TIMEOUT_S = float(env("AGENT_TIMEOUT_S", "120"))

ROW_CAP = int(env("AGENT_ROW_CAP", "500"))  # rows any query returns; the API response carries all of them
MODEL_ROWS = 50  # rows of each tool result shown to the model
STATEMENT_TIMEOUT_MS = int(env("AGENT_STATEMENT_TIMEOUT_MS", "10000"))

ASK_RATE_PER_MIN = float(env("ASK_RATE_PER_MIN", "6"))
ASK_RATE_BURST = int(env("ASK_RATE_BURST", "3"))
TRUST_PROXY = env("TRUST_PROXY") == "1"
# Sale dates newer than this are still filling in (decisions D12; dbt var secondary_horizon_days).
PROVISIONAL_DAYS = 17

DAILY_SPEND_CAP_USD = float(env("DAILY_SPEND_CAP_USD", "5.00"))
# Paid model calls are opt-in: /api/ask answers live only when this is "1" AND credentials resolve. Otherwise the
# Ask page replays answers recorded by an eval run (decisions D29).
ASK_LIVE = env("ASK_LIVE") == "1"

CORS_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000", *(o.strip() for o in env("CORS_ORIGINS", "").split(",") if o.strip())]

# The marts run_readonly_sql may read. The first group is region-filtered by RLS (the two channel-inventory marts
# look the region up via the distributor; the rest carry a region column).
MART_TABLES = frozenset({
    "dim_distributor", "fct_primary_sales", "fct_secondary_sales", "fct_channel_inventory_daily",
    "mart_channel_inventory_weekly",
    "fct_invoice_collections", "fct_field_visits", "mart_distributor_health_weekly", "mart_scheme_quarterly",
    "dim_geo", "dim_product", "dim_batch", "fct_warranty_claims", "mart_batch_claim_cohorts",
    "mart_installer_claim_cohorts", "dim_date", "mart_anomaly_flags",
})

# USD per million tokens: (input, output, cache read), from Anthropic's pricing page on 2026-09-27. Cache reads are
# 0.1x input except on Opus 5.5 (0.05x) and Fable 5.1 (0.025x); 5-minute cache writes are 1.25x input everywhere.
# The fallback models a refusal can be re-run on are listed too, and an unknown model is priced at the dearest row.
PRICES = {
    "claude-fable-5-1": (10.0, 50.0, 0.25),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-opus-4-8": (5.0, 25.0, 0.50),
    "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-haiku-4-5": (1.0, 5.0, 0.10),
}
CACHE_WRITE_MULTIPLIER = 1.25
