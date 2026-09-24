import functools
import logging
import time
from datetime import date
from typing import Annotated, Any, Literal

import anthropic
import psycopg
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app import config, semantic
from app.agent.loop import AgentError, run_agent
from app.agent.trace import Trace, write_trace
from app.db import db_conninfo
from app.guardrails.rate_limit import enforce_spend_cap, limit_ask_rate
from app.guardrails.readonly_db import QueryError
from app.guardrails.region import region_claim
from app.tools import handlers

log = logging.getLogger("channelpulse.api")

app = FastAPI(title="ChannelPulse API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Demo-Region"],
    expose_headers=["Retry-After"],
)

Scalar = bool | int | float | str
Region = Annotated[str, Depends(region_claim)]


class Filter(BaseModel):
    dimension: str
    op: Literal[semantic.FILTER_OPS]  # the tuple expands to its members
    value: Scalar | list[Scalar]


class DateRange(BaseModel):
    start: date
    end: date


class MetricQuery(BaseModel):
    metric_name: str
    filters: list[Filter] = []
    group_by: list[str] = []
    date_range: DateRange | None = None


class Table(BaseModel):
    columns: list[str]
    rows: list[list[Any]]


class GovernedResult(BaseModel):
    label: Literal["governed_metric"]
    sql: str
    row_count: int
    row_cap_hit: bool
    data: Table


class MetricList(BaseModel):
    metrics: list[dict[str, Any]]


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class ChartSpec(BaseModel):
    type: Literal["line", "bar", "table"]
    x: str | None
    y: str | None
    series: str | None


class AskResponse(BaseModel):
    answer_text: str
    sql: list[str]
    data: Table | None
    chart_spec: ChartSpec | None
    label: Literal["governed_metric", "ad_hoc_sql_verify", "refused"]
    confidence_note: str
    trace_id: str


@app.get("/health")
def health() -> dict:
    try:
        with psycopg.connect(db_conninfo(), connect_timeout=2) as conn:
            conn.execute("select 1")
        db = "ok"
    except psycopg.Error:
        db = "unreachable"
    return {"status": "ok", "db": db}


@app.get("/api/metrics", response_model=MetricList)
def list_metrics() -> dict:
    return _governed(handlers.list_metrics, {}, "ALL")


@app.post("/api/metrics/query", response_model=GovernedResult)
def query_metric(body: MetricQuery, region: Region) -> dict:
    """The dashboard's governed path: the same compile + execute as the agent's query_metric tool."""
    return _governed(handlers.query_metric, body.model_dump(mode="json"), region)


@app.get("/api/anomalies", response_model=GovernedResult)
def anomalies(region: Region, as_of: date | None = None) -> dict:
    return _governed(handlers.get_anomalies, {"as_of_date": as_of}, region)


@functools.cache
def llm_client() -> anthropic.Anthropic | None:
    """The Anthropic client, or None when no credentials resolve (API key, auth token, profile or federation)."""
    try:
        client = anthropic.Anthropic(max_retries=2)
    except anthropic.CredentialsError:  # e.g. ANTHROPIC_PROFILE or ANTHROPIC_CONFIG_DIR names a missing profile
        log.warning("Anthropic credentials are configured but can't be loaded", exc_info=True)
        return None
    return client if client.api_key or client.auth_token or client.credentials else None


@app.post("/api/ask", response_model=AskResponse, dependencies=[Depends(limit_ask_rate)])
def ask(body: AskRequest, region: Region, client: Annotated[anthropic.Anthropic | None, Depends(llm_client)]) -> dict:
    if client is None:
        raise HTTPException(503, "LLM not configured")
    enforce_spend_cap()
    trace = Trace(question=body.question, region_claim=region, model=config.MODEL)
    started = time.monotonic()
    try:
        return run_agent(client, body.question, region, trace)
    except AgentError as e:
        trace.error = str(e)
        raise HTTPException(e.status, str(e)) from e
    except anthropic.APIError as e:
        trace.error = f"{type(e).__name__}: {e}"
        status = 504 if isinstance(e, anthropic.APITimeoutError) else 502
        raise HTTPException(status, "The model API call failed; please try again.") from e
    except Exception as e:
        trace.error = f"{type(e).__name__}: {e}"
        raise
    finally:
        trace.latency_ms = round((time.monotonic() - started) * 1000)
        try:
            write_trace(trace)
        except psycopg.Error:
            log.exception("could not write trace %s", trace.trace_id)


def _governed(handler, tool_input: dict, region: str) -> dict:
    """Run a governed tool handler for an endpoint, mapping its failures to HTTP statuses."""
    try:
        return handler(tool_input, region)
    except semantic.UnknownMetric as e:
        raise HTTPException(404, str(e)) from e
    except semantic.InvalidQuery as e:
        raise HTTPException(422, str(e)) from e
    except QueryError as e:
        raise HTTPException(502, f"Query failed: {e}") from e
