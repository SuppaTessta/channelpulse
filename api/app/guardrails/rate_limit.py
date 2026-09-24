"""Abuse and cost guards for POST /api/ask: a per-IP token bucket and a daily spend cap."""

import logging
import math
import threading
import time

import psycopg
from fastapi import HTTPException, Request

from app import config
from app.db import ops_conninfo

log = logging.getLogger("channelpulse.api")


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
    """The socket peer, or the first X-Forwarded-For hop when TRUST_PROXY=1 (only behind a proxy that sets it)."""
    if config.TRUST_PROXY and (forwarded := request.headers.get("x-forwarded-for")):
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def limit_ask_rate(request: Request) -> None:
    """FastAPI dependency for POST /api/ask: 429 with Retry-After once the caller's bucket is empty."""
    if wait := ask_bucket.take(client_ip(request)):
        raise HTTPException(429, "Too many questions from this address; try again shortly.", {"Retry-After": str(wait)})


def spent_today_usd() -> float:
    """Estimated Anthropic spend since 00:00 UTC, from ops.agent_traces."""
    with psycopg.connect(ops_conninfo(), connect_timeout=3) as conn:
        (spent,) = conn.execute(
            "select coalesce(sum(est_cost_usd), 0) from ops.agent_traces"
            " where created_at >= date_trunc('day', now(), 'UTC')"
        ).fetchone()
    return float(spent)


def enforce_spend_cap() -> None:
    """503 once today's spend reaches DAILY_SPEND_CAP_USD. Fails closed: unknown spend is not an allowance."""
    try:
        spent = spent_today_usd()
    except psycopg.Error:
        log.exception("spend cap check failed")
        raise HTTPException(503, "Spend tracking is unavailable, so questions are paused.") from None
    if spent >= config.DAILY_SPEND_CAP_USD:
        raise HTTPException(
            503,
            f"The demo's daily spend cap (${config.DAILY_SPEND_CAP_USD:.2f}) is used up; questions resume at 00:00 UTC.",
        )
