"""Pacing for eval runs on free tiers and self-hosted servers (decisions D32).

ThrottledProvider wraps any provider:
- It keeps below the key's per-minute requests and tokens and its per-day requests, each set at 80% of the quota.
- It backs off on 429s, honouring the server's retry delay.
- It retries infrastructure failures (unreachable, timed out, 5xx, a tunnel's error page) a few times.

When a limit can't be waited out (the day's quota, a server that stays down) it raises RunPaused: the run saves
its progress and stops, and nothing is scored as a model failure. Retries and waits are counted for the scorecard.
"""

import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.agent.providers import ProviderError, Turn

HEADROOM = 0.8
RATE_LIMIT_ATTEMPTS = 6
INFRA_ATTEMPTS = 5  # waits of 15, 30, 45 and 60 s: rides out a provider's brief 503 ('high demand') or a tunnel blip
PACIFIC = ZoneInfo("America/Los_Angeles")  # Gemini's per-day quotas reset at midnight Pacific time


class RunPaused(Exception):
    """Stop the run here; progress is saved and the run resumes where it stopped."""


@dataclass(frozen=True)
class Limits:
    rpm: int | None = None
    tpm: int | None = None
    rpd: int | None = None

    @classmethod
    def from_quota(cls, rpm: int | None = None, tpm: int | None = None, rpd: int | None = None) -> "Limits":
        def cut(v):
            return max(1, int(v * HEADROOM)) if v else None

        return cls(cut(rpm), cut(tpm), cut(rpd))


def pacific_today() -> str:
    return datetime.now(PACIFIC).date().isoformat()


class ThrottledProvider:
    def __init__(self, inner, limits: Limits, state: dict, *, now=time.monotonic, sleep=time.sleep,
                 today=pacific_today):
        self.inner, self.limits, self.state = inner, limits, state
        self.name, self.model = inner.name, inner.model
        self._now, self._sleep, self._today = now, sleep, today
        self._window: deque[tuple[float, int]] = deque()  # (time, input tokens) of the last minute's calls
        self._last_tokens = 0
        self.stats = {"requests": 0, "rate_limit_waits": 0, "infra_retries": 0, "throttle_wait_s": 0.0}
        state.setdefault("requests_by_day", {})

    def settings(self) -> dict:
        return self.inner.settings()

    def complete(self, *args, **kwargs) -> Turn:
        rate_limited = infra = 0
        while True:
            self._pace()
            try:
                turn = self.inner.complete(*args, **kwargs)
            except ProviderError as e:
                if e.kind == "rate_limited" and "perday" in (getattr(e, "quota_id", None) or "").lower():
                    raise RunPaused(f"{self.name}: the daily quota is spent ({e.quota_id}). Waiting a few seconds "
                                    "won't help; resume after it resets at midnight Pacific time.") from e
                if e.kind == "rate_limited":
                    rate_limited += 1
                    if rate_limited >= RATE_LIMIT_ATTEMPTS:
                        raise RunPaused(f"{self.name} kept answering 429 (rate limit): most likely the day's quota "
                                        "is spent. Resume after it resets.") from e
                    self.stats["rate_limit_waits"] += 1
                    self._wait(e.retry_after or min(120.0, 10.0 * 2 ** (rate_limited - 1)))
                    continue
                if e.kind == "infrastructure":
                    infra += 1
                    if infra >= INFRA_ATTEMPTS:
                        raise RunPaused(f"{self.name} infrastructure failure ({e}). If it's the self-hosted server, "
                                        "restart the session, update its URL in .env, and resume.") from e
                    self.stats["infra_retries"] += 1
                    self._wait(15.0 * infra)
                    continue
                raise
            self._last_tokens = turn.usage.input_tokens
            stamp, _ = self._window[-1]
            self._window[-1] = (stamp, self._last_tokens)  # the call's real size replaces its estimate
            return turn

    def _pace(self) -> None:
        day = self._today()
        used = self.state["requests_by_day"].get(day, 0)
        if self.limits.rpd is not None and used >= self.limits.rpd:
            raise RunPaused(f"{self.name}: {used} requests today reach the daily limit ({self.limits.rpd}, 80% of "
                            "the quota). Resume after it resets at midnight Pacific time.")
        while True:
            now = self._now()
            while self._window and now - self._window[0][0] >= 60:
                self._window.popleft()
            too_many = self.limits.rpm is not None and len(self._window) >= self.limits.rpm
            tokens = sum(t for _, t in self._window) + self._last_tokens
            too_big = self.limits.tpm is not None and self._window and tokens > self.limits.tpm
            if not (too_many or too_big):
                break
            self._wait(max(0.5, 60 - (now - self._window[0][0])))
        self._window.append((self._now(), self._last_tokens))
        self.state["requests_by_day"][day] = used + 1
        self.stats["requests"] += 1  # every request spends quota, retries included

    def _wait(self, seconds: float) -> None:
        self.stats["throttle_wait_s"] += seconds
        self._sleep(seconds)
