"""The eval's pacing for free tiers and flaky self-hosted servers (decisions D32). A fake clock; no model calls."""

import pytest

from app.agent.providers import ProviderError, Turn, Usage
from evals.throttle import Limits, RunPaused, ThrottledProvider


class Clock:
    def __init__(self):
        self.t, self.slept = 0.0, []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += seconds


class Inner:
    name, model = "gemini", "gemini-3.8-flash"

    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), 0

    def complete(self, *args, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0) if self.outcomes else "ok"
        if isinstance(outcome, Exception):
            raise outcome
        return Turn("end_turn", "{}", [], Usage(input_tokens=1000, output_tokens=100), self.model)

    def settings(self):
        return {"temperature": 0.0}


TWO_A_MINUTE = Limits(rpm=2, tpm=None, rpd=None)


def throttled(inner, limits=TWO_A_MINUTE, state=None, clock=None):
    clock = clock or Clock()
    return ThrottledProvider(inner, limits, state if state is not None else {}, now=clock.now, sleep=clock.sleep,
                             today=lambda: "2026-09-29"), clock


def call(p):
    return p.complete("s", [], [], final_only=False, timeout=60)


def test_limits_are_applied_at_80_percent():
    assert Limits.from_quota(rpm=10, tpm=250_000, rpd=250) == Limits(rpm=8, tpm=200_000, rpd=200)


def test_requests_beyond_the_per_minute_limit_wait_for_the_window():
    p, clock = throttled(Inner())
    call(p), call(p), call(p)
    assert clock.slept and clock.slept[0] == pytest.approx(60.0)


def test_the_token_limit_waits_too():
    p, clock = throttled(Inner(), Limits(rpm=None, tpm=1500, rpd=None))
    call(p), call(p)  # the second call's estimate (the last input size) would exceed 1500 tokens a minute
    assert clock.slept


def test_a_429_backs_off_by_its_retry_delay_then_succeeds():
    inner = Inner(ProviderError("rate limited", "rate_limited", 429, retry_after=37))
    p, clock = throttled(inner)
    assert call(p).stop == "end_turn" and 37 in clock.slept and p.stats["rate_limit_waits"] == 1


def test_persistent_429s_pause_the_run_instead_of_failing_questions():
    inner = Inner(*[ProviderError("rate limited", "rate_limited", 429)] * 10)
    p, _ = throttled(inner)
    with pytest.raises(RunPaused, match="rate limit"):
        call(p)


def test_the_daily_quota_pauses_the_run_before_it_is_exceeded():
    state = {}
    p, _ = throttled(Inner(), Limits(rpm=None, tpm=None, rpd=2), state)
    call(p), call(p)
    with pytest.raises(RunPaused, match="daily"):
        call(p)
    assert state["requests_by_day"] == {"2026-09-29": 2}


def test_infrastructure_failures_are_retried_and_counted_separately():
    inner = Inner(ProviderError("couldn't connect", "infrastructure"))
    p, _ = throttled(inner)
    assert call(p).stop == "end_turn" and p.stats["infra_retries"] == 1


def test_a_dead_server_pauses_the_run_and_is_never_scored():
    inner = Inner(*[ProviderError("server error 530", "infrastructure", 530)] * 5)
    p, _ = throttled(inner)
    with pytest.raises(RunPaused, match="infrastructure"):
        call(p)


def test_a_rejected_request_is_not_retried():
    inner = Inner(ProviderError("request rejected (400)", "rejected", 400))
    p, _ = throttled(inner)
    with pytest.raises(ProviderError):
        call(p)
    assert inner.calls == 1


def test_the_wrapper_keeps_the_providers_identity():
    p, _ = throttled(Inner())
    assert (p.name, p.model, p.settings()) == ("gemini", "gemini-3.8-flash", {"temperature": 0.0})
