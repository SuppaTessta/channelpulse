"""Abuse and cost guards for POST /api/ask: a per-IP token bucket for everyone, and for owner-paid questions the
daily and monthly spend caps and each visitor's free allowance (decisions D55)."""

import dataclasses
import hashlib
import hmac
import ipaddress
import logging
import math
import secrets
import threading
import time
from datetime import UTC, date, datetime, timedelta

import psycopg
from fastapi import HTTPException, Request

from app import config
from app.agent.trace import Trace, write_trace
from app.db import ops_conninfo

log = logging.getLogger("channelpulse.api")

FREE_PAUSED = "Free questions are paused right now; use your own key to keep asking."

if config.VISITOR_SALT:
    VISITOR_SALT = config.VISITOR_SALT.encode()
else:
    VISITOR_SALT = secrets.token_bytes(32)
    log.warning("VISITOR_SALT is unset: visitor ids use a random per-process salt, so they reset when the API restarts.")


def ask_error(status: int, code: str, message: str, headers: dict | None = None) -> HTTPException:
    """A /api/ask failure: the web branches on `code`; `message` is a sentence the visitor can act on."""
    return HTTPException(status, {"code": code, "message": message}, headers)


class TokenBucket:
    """Each key holds up to `burst` tokens, refilled at `rate_per_min`; a request spends one."""

    # ponytail: in-memory and per process. Every uvicorn worker or instance keeps its own buckets, and the table is
    # simply cleared at MAX_KEYS. Move the buckets to Redis or Postgres if the API ever runs more than one process.
    MAX_KEYS = 10_000

    def __init__(self, rate_per_min: float, burst: int, clock=time.monotonic):
        self.rate = rate_per_min / 60
        self.burst = burst
        self.clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, time of last update)
        self._lock = threading.Lock()

    def take(self, key: str) -> int:
        """Spend a token for `key`: 0 if allowed, otherwise the whole seconds until one is available."""
        with self._lock:
            now = self.clock()
            tokens, updated = self._buckets.get(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - updated) * self.rate)
            if tokens >= 1:
                if len(self._buckets) >= self.MAX_KEYS:
                    self._buckets.clear()
                self._buckets[key] = (tokens - 1, now)
                return 0
            self._buckets[key] = (tokens, now)
            return math.ceil((1 - tokens) / self.rate)


ask_bucket = TokenBucket(config.ASK_RATE_PER_MIN, config.ASK_RATE_BURST)


def client_ip(request: Request) -> str:
    """The socket peer, or the first X-Forwarded-For hop when TRUST_PROXY=1 (only behind a proxy that sets it) and
    it parses as an address. An IPv6 address counts as its /64, which one subscriber usually holds whole; so the
    buckets and visitor ids are keyed by real addresses, never by whatever text a header carries."""
    peer = request.client.host if request.client else "unknown"
    hop = request.headers.get("x-forwarded-for", "").split(",")[0].strip() if config.TRUST_PROXY else ""
    for candidate in (hop, peer):
        try:
            ip = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        ip = getattr(ip, "ipv4_mapped", None) or ip  # ::ffff:a.b.c.d is an IPv4 client, not one shared /64
        return str(ip) if ip.version == 4 else str(ipaddress.ip_network((ip, 64), strict=False))
    return peer


def limit_ask_rate(request: Request) -> None:
    """FastAPI dependency for POST /api/ask: 429 with Retry-After once the caller's bucket is empty."""
    if wait := ask_bucket.take(client_ip(request)):
        raise ask_error(429, "rate_limited", "Too many questions from this address; try again shortly.",
                        {"Retry-After": str(wait)})


def utc_now() -> datetime:
    return datetime.now(UTC)


def visitor_id(ip: str, day: date) -> str:
    """hmac_sha256(VISITOR_SALT, "<UTC date>|<ip>") as 32 hex characters: the same address on the same UTC day gets
    the same id, a new day an unlinkable one, and the address itself is never kept."""
    return hmac.new(VISITOR_SALT, f"{day.isoformat()}|{ip}".encode(), hashlib.sha256).hexdigest()[:32]


def request_visitor(request: Request) -> str:
    """FastAPI dependency: the caller's visitor id for today."""
    # ponytail: client_ip() takes the first X-Forwarded-For hop, which a visitor can forge to look new each time and
    # get past FREE_QUESTIONS_PER_DAY, though never past the daily spend cap. Take the hop the proxy appends to stop it.
    return visitor_id(client_ip(request), utc_now().date())


def ops_connect() -> psycopg.Connection:
    """A connection as channelpulse_ops; its `with` block is one transaction, committed on a clean exit."""
    return psycopg.connect(ops_conninfo(), connect_timeout=3)


def owner_spend_usd(conn: psycopg.Connection) -> tuple[float, float]:
    """Owner-paid estimated spend since 00:00 UTC today and since the 1st of the month, from ops.agent_traces."""
    today, month = conn.execute(
        "select coalesce(sum(est_cost_usd) filter (where created_at >= date_trunc('day', now(), 'UTC')), 0),"
        " coalesce(sum(est_cost_usd), 0) from ops.agent_traces"
        " where paid_by = 'owner' and created_at >= date_trunc('month', now(), 'UTC')"
    ).fetchone()
    return float(today), float(month)


def free_questions_used(conn: psycopg.Connection, visitor: str) -> int:
    """Owner-paid questions this visitor id has asked since 00:00 UTC, from ops.agent_traces."""
    (used,) = conn.execute(
        "select count(*) from ops.agent_traces"
        " where paid_by = 'owner' and visitor = %s and created_at >= date_trunc('day', now(), 'UTC')",
        (visitor,),
    ).fetchone()
    return used


def _free_left(conn: psycopg.Connection, visitor: str) -> tuple[int, str | None]:
    today, month = owner_spend_usd(conn)
    if today >= config.DAILY_SPEND_CAP_USD or month >= config.MONTHLY_SPEND_CAP_USD:
        return 0, "paused"  # the caps answer before the allowance
    left = max(0, config.FREE_QUESTIONS_PER_DAY - free_questions_used(conn, visitor))
    return left, None if left else "used"


def free_questions_left(visitor: str) -> tuple[int, str | None]:
    """This visitor's free questions left today, and why there are none: "paused" past either owner spend cap or
    when the trace table can't be read (fails closed: unknown spend is not an allowance), or "used"."""
    try:
        with ops_connect() as conn:
            return _free_left(conn, visitor)
    except psycopg.Error:
        log.exception("free question check failed")
        return 0, "paused"


RESERVE_LOCK = 550_055  # pg_advisory_xact_lock key for reserving free questions; no other code takes it


def reserve_free_question(trace: Trace) -> None:
    """Before an owner-paid question's model call, write its trace row counted at OWNER_RESERVE_USD (write_trace
    replaces it with the real values after), or refuse: 503 free_paused past either cap or when the trace table
    can't be read or written, so the model is never called on unknown spend; 429 free_used, with Retry-After until
    00:00 UTC, once this visitor's free questions are used up."""
    # ponytail: one global advisory lock serialises every reservation's check and insert (a few ms each), so
    # concurrent questions can't all pass before any is counted. The reservation is flat: a question dearer than
    # OWNER_RESERVE_USD can still take a cap past its limit by the difference, once per question in flight. Raise
    # OWNER_RESERVE_USD if recorded costs come near it.
    try:
        with ops_connect() as conn:
            conn.execute("select pg_advisory_xact_lock(%s)", (RESERVE_LOCK,))
            _, why = _free_left(conn, trace.visitor)
            if why is None:
                write_trace(dataclasses.replace(trace, est_cost_usd=config.OWNER_RESERVE_USD), conn)
    except psycopg.Error:
        log.exception("could not reserve a free question")
        why = "paused"
    if why == "paused":
        raise ask_error(503, "free_paused", FREE_PAUSED)
    if why == "used":
        now = utc_now()
        midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        raise ask_error(429, "free_used", "Today's free questions are used up; use your own key to keep asking.",
                        {"Retry-After": str(math.ceil((midnight - now).total_seconds()))})
