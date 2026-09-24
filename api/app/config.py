"""Runtime settings, read from the environment at startup."""

import os

env = os.environ.get

MODEL = env("CHANNELPULSE_MODEL", "claude-opus-5")
EFFORT = env("CHANNELPULSE_EFFORT", "high")
MAX_TOKENS = 16_000
MAX_TOOL_ROUNDS = int(env("AGENT_MAX_TOOL_ROUNDS", "8"))
AGENT_TIMEOUT_S = float(env("AGENT_TIMEOUT_S", "120"))

ROW_CAP = int(env("AGENT_ROW_CAP", "500"))  # rows any query returns; the API response carries all of them
MODEL_ROWS = 50  # rows of each tool result shown to the model
STATEMENT_TIMEOUT_MS = int(env("AGENT_STATEMENT_TIMEOUT_MS", "5000"))

ASK_RATE_PER_MIN = float(env("ASK_RATE_PER_MIN", "6"))
ASK_RATE_BURST = int(env("ASK_RATE_BURST", "3"))
TRUST_PROXY = env("TRUST_PROXY") == "1"
DAILY_SPEND_CAP_USD = float(env("DAILY_SPEND_CAP_USD", "5.00"))

CORS_ORIGINS = ["http://localhost:3000", *(o.strip() for o in env("CORS_ORIGINS", "").split(",") if o.strip())]

# The marts run_readonly_sql may read. The first group carries a region column and the region RLS policy.
MART_TABLES = frozenset({
    "dim_distributor", "fct_primary_sales", "fct_secondary_sales", "fct_channel_inventory_daily",
    "fct_invoice_collections", "fct_field_visits", "mart_distributor_health_weekly", "mart_scheme_quarterly",
    "dim_geo", "dim_product", "dim_batch", "fct_warranty_claims", "mart_batch_claim_cohorts",
    "mart_installer_claim_cohorts", "dim_date", "mart_anomaly_flags",
})

# USD per million tokens: (input, output). Cache reads bill at 0.1x input, 5-minute cache writes at 1.25x.
PRICES = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),  # where the server-side refusal fallback sends cyber-category declines
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER = 1.25
