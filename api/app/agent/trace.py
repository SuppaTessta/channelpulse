"""One ops.agent_traces row per /api/ask: question, tool calls, SQL, row counts, tokens, latency and estimated cost."""

import re
import uuid
from dataclasses import asdict, dataclass, field, fields

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from app import config
from app.db import ops_conninfo


def price(model: str) -> tuple[float, float, float]:
    """(input, output, cache read) USD per MTok. An unknown model gets the dearest known rate, so the cap errs high."""
    return config.PRICES.get(re.sub(r"-\d{8}$", "", model)) or max(config.PRICES.values())


@dataclass
class Trace:
    question: str
    region_claim: str
    model: str
    trace_id: uuid.UUID = field(default_factory=uuid.uuid4)
    provider: str = "anthropic"
    served_model: str | None = None
    label: str = "error"
    tool_calls: list[dict] = field(default_factory=list)
    final_sql: list[str] = field(default_factory=list)
    row_count: int | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: int | None = None
    est_cost_usd: float = 0.0
    answer_text: str | None = None
    error: str | None = None
    paid_by: str = "owner"  # or "visitor", for a question asked with the visitor's own key (decisions D55)
    visitor: str | None = None  # guardrails/rate_limit.visitor_id: the same address on the same UTC day

    def add_usage(self, turn) -> None:
        """Add one model turn. Its usage covers the attempt that produced it, priced at the model that served it
        (after a refusal fallback, the fallback model)."""
        usage = turn.usage
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cache_read_tokens += usage.cache_read_tokens
        self.cache_write_tokens += usage.cache_write_tokens
        self.served_model = turn.model
        input_price, output_price, cache_read_price = price(turn.model)
        self.est_cost_usd += (
            (usage.input_tokens + usage.cache_write_tokens * config.CACHE_WRITE_MULTIPLIER) * input_price
            + usage.cache_read_tokens * cache_read_price
            + usage.output_tokens * output_price
        ) / 1_000_000

_COLUMNS = [f.name for f in fields(Trace)]
_COLUMN_LIST = sql.SQL(", ").join(map(sql.Identifier, _COLUMNS))
_UPSERT = sql.SQL("insert into ops.agent_traces ({}) values ({}) on conflict (trace_id) do update set ({}) = ({})").format(
    _COLUMN_LIST,
    sql.SQL(", ").join(map(sql.Placeholder, _COLUMNS)),
    _COLUMN_LIST,
    sql.SQL(", ").join(sql.SQL("excluded.{}").format(sql.Identifier(c)) for c in _COLUMNS),
)


def write_trace(trace: Trace, conn: psycopg.Connection | None = None) -> None:
    """Insert the trace as channelpulse_ops, the only role that can write ops.agent_traces, or replace the row a free
    question reserved under the same trace_id (guardrails/rate_limit). On `conn`, inside the caller's transaction."""
    row = asdict(trace)
    row["tool_calls"] = Jsonb(row["tool_calls"])
    row["est_cost_usd"] = round(row["est_cost_usd"], 5)
    if conn is not None:
        conn.execute(_UPSERT, row)
        return
    with psycopg.connect(ops_conninfo(), connect_timeout=3) as own:
        own.execute(_UPSERT, row)
