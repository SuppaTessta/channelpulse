import functools
import logging
import re
import time
import traceback
from datetime import date
from typing import Annotated, Any, Literal

import anthropic
import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app import brief, config, replay, semantic, traces
from app.agent.loop import AgentError, run_agent
from app.agent.providers import AnthropicProvider, ProviderError
from app.agent.trace import Trace, write_trace
from app.db import db_conninfo
from app.guardrails.rate_limit import (
    FREE_PAUSED,
    ask_error,
    free_questions_left,
    limit_ask_rate,
    request_visitor,
    reserve_free_question,
)
from app.guardrails.readonly_db import QueryError
from app.guardrails.region import ALL_REGIONS, REGIONS, region_claim
from app.tools import handlers
from app.tools.definitions import DETECTORS

log = logging.getLogger("channelpulse.api")

app = FastAPI(title="ChannelPulse API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Demo-Region", "X-Anthropic-Key"],
    expose_headers=["Retry-After"],
)
NO_STORE = {"/api/ask", "/api/ask/status"}  # answers per visitor, and per key


@app.middleware("http")  # added after CORS, so it wraps preflight answers too
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    if request.url.path in NO_STORE:
        response.headers["Cache-Control"] = "no-store"
    return response

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
    # No C0 control characters but tab and line breaks: a NUL can't even be stored in the trace.
    question: str = Field(min_length=1, max_length=2000, pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f]*$")


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


Detector = Literal[DETECTORS]


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
def llm_provider() -> AnthropicProvider | None:
    """The model provider, or None when no Anthropic credentials resolve."""
    client = llm_client()
    return AnthropicProvider(client) if client is not None else None


LLM = Annotated[AnthropicProvider | None, Depends(llm_provider)]
Visitor = Annotated[str, Depends(request_visitor)]


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


class FreeQuestions(BaseModel):
    limit: int
    remaining: int  # the requesting visitor's
    available: bool
    reason: Literal["no_credentials", "paused", "used"] | None


class AskStatus(BaseModel):
    mode: Literal["live", "replay"]
    reason: Literal["live_off"] | None
    model: str | None
    recording: Recording | None
    free: FreeQuestions | None  # null in replay
    byok: bool  # a visitor's own key works whenever the mode is live


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


@app.get("/api/ask/status", response_model=AskStatus)
def ask_status(provider: LLM, visitor: Visitor, free: bool = True) -> dict:
    """Whether /api/ask answers live, how many free questions this visitor has left, and which recorded eval run
    the page can replay instead. ?free=0 leaves out the free questions (null), for a caller that isn't the visitor,
    such as the web's own server-side render."""
    live = config.ASK_LIVE
    return {"mode": "live" if live else "replay", "reason": None if live else "live_off",
            "model": config.MODEL if live else None, "recording": replay.summary(replay.load()),
            "free": _free_questions(provider, visitor) if live and free else None, "byok": live}


def _free_questions(provider: AnthropicProvider | None, visitor: str) -> dict:
    remaining, reason = free_questions_left(visitor) if provider else (0, "no_credentials")
    return {"limit": config.FREE_QUESTIONS_PER_DAY, "remaining": remaining, "available": reason is None,
            "reason": reason}


@app.get("/api/ask/replay", response_model=Replay)
def ask_replay(region: Region) -> dict:
    return replay.for_region(region)


KEY_FORMAT = re.compile(r"sk-ant-[A-Za-z0-9_-]{20,200}")
KEY_IN_TEXT = re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")
# A 400 that means the account can't pay, rather than a malformed request.
CANT_PAY = re.compile(r"usage limit|spend limit|credit balance|billing", re.IGNORECASE)


@app.post("/api/ask", response_model=AskResponse, dependencies=[Depends(limit_ask_rate)])
def ask(body: AskRequest, visitor: Visitor, x_demo_region: Annotated[str | None, Header()] = None,
        x_anthropic_key: Annotated[str | None, Header()] = None) -> dict:
    """Answer one question with the visitor's own key, sent in X-Anthropic-Key and read from nowhere else, or else
    as one of the owner's free questions under the spend caps (decisions D55)."""
    if not config.ASK_LIVE:
        raise ask_error(503, "live_off", "Live answers are switched off on this server; the recorded ones still work.")
    try:
        region = region_claim(x_demo_region)  # here, not a dependency, so the kill switch answers first
    except HTTPException as e:
        raise ask_error(400, "bad_region", e.detail) from None
    if KEY_IN_TEXT.search(body.question):  # refused before anything is traced, so the key is never kept
        raise ask_error(400, "key_in_question", "That looks like an API key. Paste it in the key field instead.")
    if x_anthropic_key:
        if not KEY_FORMAT.fullmatch(x_anthropic_key):
            raise ask_error(400, "key_invalid", "That doesn't look like an Anthropic key. They start with sk-ant-.")
        # This request's own client, closed with it: never cached, stored or handed to anything that outlives it.
        # Explicit base URL and auth headers, so the owner's ANTHROPIC_BASE_URL can't redirect the key and
        # ANTHROPIC_CUSTOM_HEADERS can't replace it or add an Authorization header (the SDK applies it after api_key).
        auth = {"X-Api-Key": x_anthropic_key, "Authorization": anthropic.omit}
        with anthropic.Anthropic(api_key=x_anthropic_key, max_retries=2, base_url="https://api.anthropic.com",
                                 default_headers=auth) as client:
            return _answer(AnthropicProvider(client), body.question, region, visitor, key=x_anthropic_key)
    provider = llm_provider()  # resolved here, so the visitor path never touches the owner's credentials
    if provider is None:
        raise ask_error(503, "free_unavailable", "Free questions aren't offered on this server; use your own key.")
    return _answer(provider, body.question, region, visitor)


def _answer(provider: AnthropicProvider, question: str, region: str, visitor: str, key: str | None = None) -> dict:
    """Run the agent and write its trace; the visitor pays when `key` is theirs, and the owner's free question is
    reserved before the model call. A failure becomes a coded error for whoever pays, and any text built from it has
    the key redacted (Anthropic's errors don't echo keys today)."""
    trace = Trace(question=question, region_claim=region, model=provider.model, provider=provider.name,
                  paid_by="visitor" if key else "owner", visitor=visitor)
    if key is None:
        reserve_free_question(trace)
    started = time.monotonic()
    try:
        return run_agent(provider, question, region, trace)
    except AgentError as e:
        trace.error = _redact(str(e), key)
        raise ask_error(e.status, "agent_error", trace.error) from e
    except (anthropic.APIError, ProviderError) as e:
        trace.error = _redact(f"{type(e).__name__}: {e}", key)
        raise _model_error(e, by_visitor=key is not None) from e
    except Exception as e:
        trace.error = _redact(f"{type(e).__name__}: {e}", key)
        _log_exception(f"/api/ask failed, trace {trace.trace_id}", key)
        # Raised, not left unhandled, so the 500 still has a code, the security headers and CORS.
        raise ask_error(500, "server_error", "Something went wrong on the server; please try again.") from e
    finally:
        trace.latency_ms = round((time.monotonic() - started) * 1000)
        try:
            write_trace(trace)
        except Exception:  # noqa: BLE001 - never in place of the response; a reservation stays counted
            _log_exception(f"could not write trace {trace.trace_id}", key)


def _log_exception(message: str, key: str | None) -> None:
    """log.exception, with the key redacted from the whole traceback, chained exceptions included."""
    log.error("%s\n%s", message, _redact(traceback.format_exc(), key))


def _model_error(e: Exception, by_visitor: bool) -> HTTPException:
    """Anthropic's failure as the error its payer can act on: a visitor hears about their key; when the owner's
    account can't pay, free questions pause."""
    # The SDK has no class for a 402 or a 504: they come as a bare APIStatusError and an InternalServerError.
    status, kind = getattr(e, "status_code", None), getattr(e, "type", None)
    if isinstance(e, anthropic.APITimeoutError) or status == 504 or kind == "timeout_error":
        return ask_error(504, "model_timeout", "The model took too long to answer; please try again.")
    if by_visitor and isinstance(e, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        return ask_error(401, "key_rejected", "Anthropic didn't accept that key. Check it, or make a new one.")
    if (isinstance(e, anthropic.RateLimitError) or status == 402 or kind == "billing_error"
            or (isinstance(e, anthropic.BadRequestError) and CANT_PAY.search(str(e)))):
        if by_visitor:
            return ask_error(402, "key_limited", "Your key hit an Anthropic rate or spend limit.")
        return ask_error(503, "free_paused", FREE_PAUSED)
    return ask_error(502, "model_error", "The model API call failed; please try again.")


def _redact(text: str, key: str | None) -> str:
    return text.replace(key, "[redacted]") if key else text


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


@app.get("/api/brief/weeks")
def brief_weeks(region: Region) -> dict:
    """The complete weeks a brief can be written for, newest first."""
    try:
        return {"weeks": brief.weeks(region)}
    except QueryError as e:
        raise HTTPException(502, f"Query failed: {e}") from e


@app.get("/api/brief")
def weekly_brief(region: Region, provider: LLM, week: date | None = None) -> dict:
    """The Weekly Channel & Quality Brief for the week starting `week` (a Monday; default the latest complete week),
    after the numbers check. A blocked brief comes back with status blocked and no sentences."""
    try:
        weeks = brief.weeks(region)
        start = week.isoformat() if week else weeks[0]
        if start not in weeks:
            raise HTTPException(422, "week must be the Monday of a complete week in the data.")
        as_of = date.fromisoformat(str(handlers.data_window(region)["as_of"])[:10])
        return brief.build(date.fromisoformat(start), region, as_of, provider)
    except (QueryError, semantic.InvalidQuery) as e:
        raise HTTPException(502, f"Query failed: {e}") from e


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
