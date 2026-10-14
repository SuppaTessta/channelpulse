"""Runs SQL as channelpulse_agent, the read-only marts role (the hard boundary; the SQL validator is defence in depth)."""

import datetime as dt
import decimal
import math
import time
from dataclasses import dataclass

import psycopg
from psycopg import ClientCursor

from app import config
from app.db import agent_conninfo

CATALOG_TTL_S = 300


class QueryError(Exception):
    """The database refused or failed the query. The message is safe to show the model and the user."""


@dataclass
class QueryResult:
    sql: str  # the SQL that ran, with any params inlined for display
    columns: list[str]
    rows: list[list]
    row_cap_hit: bool  # exactly ROW_CAP rows came back, so there may be more

    @property
    def data(self) -> dict:
        return {"columns": self.columns, "rows": self.rows}


def run(sql: str, params: dict | None, region: str) -> QueryResult:
    """Execute one SELECT in a read-only transaction under the caller's region claim; return at most ROW_CAP rows."""
    params = params or None  # with no params psycopg leaves a literal % alone
    try:
        with psycopg.connect(agent_conninfo(), connect_timeout=5) as conn:
            conn.read_only = True  # transactions open with BEGIN READ ONLY
            with conn.cursor() as cur:
                cur.execute(f"set local statement_timeout = {int(config.STATEMENT_TIMEOUT_MS)}")
                cur.execute("set local search_path = marts")
                # The RLS filter and MetricFlow's date_trunc() predicates make the planner estimate a fact table at a
                # handful of rows, so it nests a loop over the time spine: a fiscal-grain query took 10 s instead of
                # 0.15 s (D39). Index scans still serve filters; only joins change, to hash or merge joins, which suit
                # these fact-to-dimension joins at mart sizes.
                cur.execute("set local enable_nestloop = off")
                cur.execute("select set_config('app.region', %s, true)", (region,))  # transaction-local RLS claim
                # prepare=True sends the query over the extended protocol, which refuses a second statement.
                cur.execute(sql, params, prepare=True)
                if cur.description is None:
                    raise QueryError("the statement returned no rows to read")
                columns = [column.name for column in cur.description]
                rows = cur.fetchmany(config.ROW_CAP)
            shown = ClientCursor(conn).mogrify(sql, params) if params else sql
    except psycopg.Error as e:
        raise QueryError(_message(e)) from e
    return QueryResult(
        sql=shown,
        columns=columns,
        rows=[[json_safe(value) for value in row] for row in rows],
        row_cap_hit=len(rows) >= config.ROW_CAP,
    )


_catalog: tuple[float, dict[str, list[str]]] = (0.0, {})


def mart_columns() -> dict[str, list[str]]:
    """'column type' strings per allowlisted mart as the agent role sees them. Cached; the system prompt renders it."""
    global _catalog
    fetched_at, catalog = _catalog
    if catalog and time.monotonic() - fetched_at < CATALOG_TTL_S:
        return catalog
    with psycopg.connect(agent_conninfo(), connect_timeout=5) as conn:
        rows = conn.execute(
            "select table_name, column_name, data_type from information_schema.columns"
            " where table_schema = 'marts' and table_name = any(%s) order by table_name, ordinal_position",
            (sorted(config.MART_TABLES),),
        ).fetchall()
    catalog = {}
    for table, column, data_type in rows:
        catalog.setdefault(table, []).append(f"{column} {data_type}")
    _catalog = (time.monotonic(), catalog)
    return catalog


def json_safe(value):
    """Make a database value JSON-serialisable: Decimal -> float, dates -> ISO text, NaN/Infinity -> None."""
    if isinstance(value, decimal.Decimal | float):
        value = float(value)
        return value if math.isfinite(value) else None
    if value is None or isinstance(value, str | int):
        return value
    if isinstance(value, dt.date | dt.time):  # datetime is a date
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return value.total_seconds()
    if isinstance(value, list | tuple):
        return [json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    return str(value)  # UUID, inet, ranges and anything else psycopg hands back


def _message(error: psycopg.Error) -> str:
    if error.diag.message_primary:
        return error.diag.message_primary
    if isinstance(error, psycopg.OperationalError):
        return "the database is unavailable"
    return str(error)
