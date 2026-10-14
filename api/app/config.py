"""Runtime settings, read from the environment at startup."""

import os

env = os.environ.get

# Anthropic's Messages API is the only provider (decisions D50). Sonnet 5.5 by default, the owner's choice on cost:
# Opus is ruled out. Medium effort is Anthropic's starting point for multistep tool use; claude-haiku-5-5 is the
# model the eval compares against.
MODEL = env("CHANNELPULSE_MODEL", "claude-sonnet-5-5")
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
# The traces view serves live ops.agent_traces rows (visitors' questions) only to a request carrying this token in
# X-Admin-Token. Unset, they're never served; the eval's recorded traces are served either way (decisions D40).
ADMIN_TOKEN = env("ADMIN_TOKEN") or None

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

# USD per million tokens: (input, output, cache read), from Anthropic's model docs on 2026-10-14. Cache reads are 0.1x
# input; 5-minute cache writes are 1.25x. Claude Sonnet 5 is where Sonnet 5.5's refusal fallback re-runs a declined
# request, and an unknown model is priced at the dearest row.
# ponytail: Haiku 5.5's prompts over 100K tokens bill at $0.50 / $2.50; the agent's stay far below that.
PRICES = {
    "claude-sonnet-5-5": (2.0, 10.0, 0.20),
    "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}
CACHE_WRITE_MULTIPLIER = 1.25
