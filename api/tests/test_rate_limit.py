import psycopg
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import config
from app.guardrails import rate_limit
from app.guardrails.rate_limit import TokenBucket, client_ip, enforce_spend_cap


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_the_bucket_allows_a_burst_then_says_how_long_to_wait():
    bucket = TokenBucket(rate_per_min=6, burst=3, clock=Clock())
    assert [bucket.take("1.2.3.4") for _ in range(4)] == [0, 0, 0, 10]


def test_the_bucket_refills_at_the_configured_rate():
    clock = Clock()
    bucket = TokenBucket(rate_per_min=6, burst=3, clock=clock)
    for _ in range(3):
        bucket.take("1.2.3.4")
    clock.now = 10.0
    assert (bucket.take("1.2.3.4"), bucket.take("1.2.3.4")) == (0, 10)


def test_each_address_has_its_own_bucket():
    bucket = TokenBucket(rate_per_min=6, burst=1, clock=Clock())
    assert (bucket.take("1.2.3.4"), bucket.take("5.6.7.8"), bucket.take("1.2.3.4")) == (0, 0, 10)


def request_from(peer: str, forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "headers": headers, "client": (peer, 50000)})


@pytest.mark.parametrize(("trust_proxy", "expected"), [(False, "10.0.0.2"), (True, "203.0.113.9")])
def test_forwarded_for_is_honoured_only_behind_a_trusted_proxy(monkeypatch, trust_proxy, expected):
    monkeypatch.setattr(config, "TRUST_PROXY", trust_proxy)
    assert client_ip(request_from("10.0.0.2", "203.0.113.9, 10.0.0.1")) == expected


def test_ask_answers_429_with_retry_after_once_the_bucket_is_empty(api, monkeypatch):
    monkeypatch.setattr(rate_limit, "ask_bucket", TokenBucket(rate_per_min=6, burst=1))
    api.use_llm(None)
    api.http.post("/api/ask", json={"question": "hi"})
    response = api.http.post("/api/ask", json={"question": "hi"})
    assert (response.status_code, response.headers["retry-after"]) == (429, "10")


def test_the_spend_cap_blocks_once_reached(monkeypatch):
    monkeypatch.setattr(config, "DAILY_SPEND_CAP_USD", 5.0)
    monkeypatch.setattr(rate_limit, "spent_today_usd", lambda: 5.0)
    with pytest.raises(HTTPException) as caught:
        enforce_spend_cap()
    assert caught.value.status_code == 503 and "spend cap" in caught.value.detail


def test_spend_under_the_cap_is_allowed(monkeypatch):
    monkeypatch.setattr(rate_limit, "spent_today_usd", lambda: config.DAILY_SPEND_CAP_USD - 0.01)
    enforce_spend_cap()


def test_the_spend_cap_fails_closed_when_spend_is_unknown(monkeypatch):
    def ops_down():
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(rate_limit, "spent_today_usd", ops_down)
    with pytest.raises(HTTPException) as caught:
        enforce_spend_cap()
    assert caught.value.status_code == 503


def test_ask_answers_503_when_the_cap_is_reached(api, claude, monkeypatch):
    monkeypatch.setattr(rate_limit, "spent_today_usd", lambda: 999.0)
    llm = claude.client()
    api.use_llm(llm)
    response = api.http.post("/api/ask", json={"question": "What was DSO last month?"})
    assert response.status_code == 503 and "spend cap" in response.json()["detail"]
    assert llm.requests == []


@pytest.mark.db
def test_todays_spend_is_read_from_the_trace_table():
    assert rate_limit.spent_today_usd() >= 0
