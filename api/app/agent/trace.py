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

    def add_usage(self, response) -> None:
        """Add one Messages API response. Its usage covers the attempt that produced it, priced at the model that
        served it: after a refusal fallback that is the fallback model, not the one requested."""
        usage = response.usage
        cache_read = usage.cache_read_input_tokens or 0
        cache_write = usage.cache_creation_input_tokens or 0
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cache_read_tokens += cache_read
        self.cache_write_tokens += cache_write
        self.served_model = response.model
        input_price, output_price, cache_read_price = price(response.model)
        self.est_cost_usd += (
            (usage.input_tokens + cache_write * config.CACHE_WRITE_MULTIPLIER) * input_price
            + cache_read * cache_read_price
            + usage.output_tokens * output_price
        ) / 1_000_000


_COLUMNS = [f.name for f in fields(Trace)]
_INSERT = sql.SQL("insert into ops.agent_traces ({}) values ({})").format(
    sql.SQL(", ").join(map(sql.Identifier, _COLUMNS)),
    sql.SQL(", ").join(map(sql.Placeholder, _COLUMNS)),
)


def write_trace(trace: Trace) -> None:
    """Insert the trace as channelpulse_ops, the only role that can write ops.agent_traces."""
    row = asdict(trace)
    row["tool_calls"] = Jsonb(row["tool_calls"])
    row["est_cost_usd"] = round(row["est_cost_usd"], 5)
    with psycopg.connect(ops_conninfo(), connect_timeout=3) as conn:
        conn.execute(_INSERT, row)
