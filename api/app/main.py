import functools
import logging
import time
from datetime import date
from typing import Annotated, Any, Literal

import anthropic
import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app import config, replay, semantic, traces
from app.agent.loop import AgentError, run_agent
from app.agent.providers import Provider, ProviderError, from_env
from app.agent.trace import Trace, write_trace
from app.db import db_conninfo
from app.guardrails.rate_limit import enforce_spend_cap, limit_ask_rate
from app.guardrails.readonly_db import QueryError
from app.guardrails.region import ALL_REGIONS, REGIONS, region_claim
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
    label: Literal["governed_metric", "ad_hoc_sql_verify", "refused", "needs_clarification"]
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


Detector = Literal["lot_scan", "installer_scan", "stuffing", "distributor_health"]


@app.get("/api/anomalies", response_model=GovernedResult)
def anomalies(region: Region, as_of: date | None = None, detector: Detector | None = None) -> dict:
    return _governed(handlers.get_anomalies, {"as_of_date": as_of, "detector": detector, "failure_mode": None}, region)


class Meta(BaseModel):
    data_start: date
    as_of: date
    provisional_days: int
    regions: list[str]


@app.get("/api/meta", response_model=Meta)
def meta(region: Region) -> dict:
    """What clients need to frame the data: its window, the provisional horizon and the valid region claims."""
    try:
        window = handlers.data_window(region)
    except QueryError as e:
        raise HTTPException(502, f"Query failed: {e}") from e
    return {**window, "provisional_days": config.PROVISIONAL_DAYS, "regions": [*REGIONS, ALL_REGIONS]}


@functools.cache
def llm_client() -> anthropic.Anthropic | None:
    """The Anthropic client, or None when no credentials resolve (API key, auth token, profile or federation)."""
    try:
        client = anthropic.Anthropic(max_retries=2)
    except anthropic.CredentialsError:  # e.g. ANTHROPIC_PROFILE or ANTHROPIC_CONFIG_DIR names a missing profile
        log.warning("Anthropic credentials are configured but can't be loaded", exc_info=True)
        return None
    return client if client.api_key or client.auth_token or client.credentials else None


@functools.cache
def llm_provider() -> Provider | None:
    """The configured model provider (CHANNELPULSE_PROVIDER), or None when it has no credentials or endpoint."""
    return from_env(llm_client() if config.PROVIDER == "anthropic" else None)


LLM = Annotated[Provider | None, Depends(llm_provider)]


class Recording(BaseModel):
    provider: str
    model: str
    effort: str
    recorded_at: str
    as_of: str
    region: str
    status: str
    git_commit: str | None
    count: int


class AskStatus(BaseModel):
    mode: Literal["live", "replay"]
    reason: Literal["no_credentials", "live_off"] | None
    provider: str
    model: str | None
    recording: Recording | None


class ReplayAnswer(BaseModel):
    id: str
    category: str
    question: str
    response: AskResponse
    eval: dict[str, bool]
    served_model: str | None
    latency_ms: int
    cost_usd: float


class Replay(BaseModel):
    recording: Recording | None
    answers: list[ReplayAnswer]
    withheld: bool


def _not_live_reason(provider: Provider | None) -> str | None:
    if provider is None:
        return "no_credentials"
    return None if config.ASK_LIVE else "live_off"


@app.get("/api/ask/status", response_model=AskStatus)
def ask_status(provider: LLM) -> dict:
    """Whether /api/ask answers live, why not, and which recorded eval run the page can replay instead."""
    reason = _not_live_reason(provider)
    return {"mode": "replay" if reason else "live", "reason": reason, "provider": config.PROVIDER,
            "model": provider.model if provider else None, "recording": replay.summary(replay.load())}


@app.get("/api/ask/replay", response_model=Replay)
def ask_replay(region: Region) -> dict:
    return replay.for_region(region)


@app.post("/api/ask", response_model=AskResponse, dependencies=[Depends(limit_ask_rate)])
def ask(body: AskRequest, region: Region, provider: LLM) -> dict:
    reason = _not_live_reason(provider)
    if reason == "no_credentials":
        raise HTTPException(503, "LLM not configured")
    if reason == "live_off":
        raise HTTPException(503, "Live mode is off on this server (set ASK_LIVE=1 to enable paid model calls).")
    enforce_spend_cap()
    trace = Trace(question=body.question, region_claim=region, model=provider.model, provider=provider.name)
    started = time.monotonic()
    try:
        return run_agent(provider, body.question, region, trace)
    except AgentError as e:
        trace.error = str(e)
        raise HTTPException(e.status, str(e)) from e
    except anthropic.APIError as e:
        trace.error = f"{type(e).__name__}: {e}"
        status = 504 if isinstance(e, anthropic.APITimeoutError) else 502
        raise HTTPException(status, "The model API call failed; please try again.") from e
    except ProviderError as e:
        trace.error = f"{e.kind}: {e}"
        status = 503 if e.kind == "rate_limited" else 502
        raise HTTPException(status, "The model provider didn't answer; please try again.") from e
    except Exception as e:
        trace.error = f"{type(e).__name__}: {e}"
        raise
    finally:
        trace.latency_ms = round((time.monotonic() - started) * 1000)
        try:
            write_trace(trace)
        except psycopg.Error:
            log.exception("could not write trace %s", trace.trace_id)


class TraceList(BaseModel):
    total: int
    traces: list[dict[str, Any]]
    facets: dict[str, dict[str, int]]
    totals: dict[str, Any]
    live: Literal["included", "admin_only", "unavailable"]
    withheld: bool  # recordings exist under another region claim


def _all_traces(region: str, admin_token: str | None) -> tuple[list[dict], str]:
    rows, live = traces.recorded(region), "admin_only"
    if traces.is_admin(admin_token):
        try:
            rows += traces.live()
            live = "included"
        except psycopg.Error:
            log.exception("could not read ops.agent_traces")
            live = "unavailable"
    return rows, live


@app.get("/api/traces", response_model=TraceList)
def list_traces(
    region: Region,
    source: str | None = None,
    label: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    category: str | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=traces.PAGE_MAX)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    x_admin_token: Annotated[str | None, Header()] = None,
) -> dict:
    """The admin traces view: recorded eval traces, plus live ones for the admin token; filtered and paged."""
    rows, live = _all_traces(region, x_admin_token)
    filters = {"source": source, "label": label, "provider": provider, "model": model, "category": category}
    withheld = not rows and any(r["region"] != region for r in replay.load_all())
    return traces.listing(rows, filters, q, limit, offset) | {"live": live, "withheld": withheld}


@app.get("/api/traces/{trace_id}")
def get_trace(trace_id: str, region: Region, x_admin_token: Annotated[str | None, Header()] = None) -> dict:
    rows, _ = _all_traces(region, x_admin_token)
    match = next((r for r in rows if r["trace_id"] == trace_id), None)
    if match is None:
        raise HTTPException(404, "No trace with that id is visible to this request.")
    return match


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
