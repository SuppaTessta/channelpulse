import datetime as dt
import hashlib
import hmac
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import config, main
from app.agent.providers import AnthropicProvider
from app.agent.trace import Trace, write_trace
from app.db import db_conninfo
from app.guardrails import rate_limit
from app.guardrails.rate_limit import TokenBucket, client_ip, visitor_id


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


@pytest.mark.parametrize(("forwarded", "expected"), [
    ("2001:db8:1:2:3:4:5:6, 10.0.0.1", "2001:db8:1:2::/64"),
    ("::ffff:203.0.113.9", "203.0.113.9"),
    ("not-an-address", "10.0.0.2"),
    ("9" * 16_000, "10.0.0.2"),
], ids=["ipv6 is its /64", "ipv4-mapped is ipv4", "garbage is the peer", "16 KB is the peer"])
def test_the_client_is_a_real_address_so_bucket_and_visitor_keys_stay_bounded(monkeypatch, forwarded, expected):
    monkeypatch.setattr(config, "TRUST_PROXY", True)
    assert client_ip(request_from("10.0.0.2", forwarded)) == expected


def test_an_ipv6_peer_is_its_64_too(monkeypatch):
    monkeypatch.setattr(config, "TRUST_PROXY", False)
    assert client_ip(request_from("2001:db8:1:2::99")) == "2001:db8:1:2::/64"


def test_ask_answers_429_with_retry_after_once_the_bucket_is_empty(api, monkeypatch):
    monkeypatch.setattr(rate_limit, "ask_bucket", TokenBucket(rate_per_min=6, burst=1))
    api.use_llm(None)
    api.http.post("/api/ask", json={"question": "hi"})
    response = api.http.post("/api/ask", json={"question": "hi"})
    assert (response.status_code, response.headers["retry-after"]) == (429, "10")
    assert response.json()["detail"]["code"] == "rate_limited"


def test_ask_answers_503_when_the_cap_is_reached(api, claude, monkeypatch):
    monkeypatch.setattr(rate_limit, "owner_spend_usd", lambda *_: (999.0, 999.0))
    llm = claude.client()
    api.use_llm(llm)
    response = api.http.post("/api/ask", json={"question": "What was DSO last month?"})
    assert (response.status_code, response.json()["detail"]["code"]) == (503, "free_paused")
    assert llm.requests == []


def test_the_visitor_id_is_the_salted_hmac_of_the_utc_date_and_address(monkeypatch):
    monkeypatch.setattr(rate_limit, "VISITOR_SALT", b"pepper")
    expected = hmac.new(b"pepper", b"2026-10-29|203.0.113.9", hashlib.sha256).hexdigest()[:32]
    assert visitor_id("203.0.113.9", dt.date(2026, 10, 29)) == expected


def test_a_visitor_id_holds_for_a_day_changes_the_next_and_never_holds_the_address():
    day = dt.date(2026, 10, 29)
    first = visitor_id("203.0.113.9", day)
    assert first == visitor_id("203.0.113.9", day) and len(first) == 32 and "203.0.113.9" not in first
    assert first != visitor_id("203.0.113.9", day + dt.timedelta(days=1))
    assert first != visitor_id("198.51.100.7", day)


def owner_usage(visitor: str) -> tuple[float, float, int]:
    with rate_limit.ops_connect() as conn:
        return *rate_limit.owner_spend_usd(conn), rate_limit.free_questions_used(conn, visitor)


def probe(visitor: str, paid_by: str = "owner", cost: float = 0.25) -> Trace:
    return Trace(question="pytest probe", region_claim="ALL", model="claude-sonnet-5-5", paid_by=paid_by,
                 visitor=visitor, est_cost_usd=cost)


@pytest.fixture
def visitor():
    """A fresh visitor id; its probe rows are deleted after."""
    visitor = uuid.uuid4().hex
    yield visitor
    with psycopg.connect(db_conninfo()) as admin:
        admin.execute("delete from ops.agent_traces where visitor = %s", (visitor,))


@pytest.mark.db
def test_the_caps_and_the_allowance_count_owner_paid_traces_only(visitor):
    """A visitor's own key costs the owner nothing: its traces move neither cap nor the free-question count."""
    before = owner_usage(visitor)
    write_trace(probe(visitor, "owner", 0.25))
    write_trace(probe(visitor, "visitor", 50.0))
    assert [a - b for a, b in zip(owner_usage(visitor), before, strict=True)] == pytest.approx([0.25, 0.25, 1])


@pytest.mark.db
def test_the_day_and_month_windows_leave_out_older_owner_spend(visitor):
    before = owner_usage(visitor)
    yesterday, last_month = probe(visitor, cost=0.25), probe(visitor, cost=50.0)
    for trace in (yesterday, last_month):
        write_trace(trace)
    with psycopg.connect(db_conninfo()) as admin:  # back-dated as only the admin can
        for trace, start in ((yesterday, "day"), (last_month, "month")):
            admin.execute("update ops.agent_traces set created_at = date_trunc(%s, now(), 'UTC') - interval '1 second'"
                          " where trace_id = %s", (start, trace.trace_id))
    in_this_month = 0.25 if rate_limit.utc_now().day > 1 else 0.0
    assert [a - b for a, b in zip(owner_usage(visitor), before, strict=True)] == pytest.approx([0, in_this_month, 0])


ANSWER = {"answer_text": "Answered.", "sql": [], "data": None, "chart_spec": None, "label": "refused",
          "confidence_note": "", "trace_id": ""}


@pytest.fixture
def owner_asks(monkeypatch, claude):
    """POST /api/ask on the owner's path against the real trace table, from the address given: each one a fresh
    visitor. Tests replace main.run_agent, so no model is called; the rows written are deleted after."""
    question = f"pytest probe {uuid.uuid4().hex}"
    monkeypatch.setattr(config, "ASK_LIVE", True)
    monkeypatch.setattr(config, "TRUST_PROXY", True)
    monkeypatch.setattr(main, "llm_provider", lambda: AnthropicProvider(claude.client()))
    monkeypatch.setattr(rate_limit, "ask_bucket", TokenBucket(rate_per_min=600, burst=100))
    http = TestClient(main.app)
    yield lambda ip="203.0.113.9": http.post("/api/ask", json={"question": question}, headers={"X-Forwarded-For": ip})
    with psycopg.connect(db_conninfo()) as admin:
        admin.execute("delete from ops.agent_traces where question = %s", (question,))


@pytest.mark.db
def test_a_trace_the_table_cannot_store_leaves_its_reservation_counted(owner_asks, monkeypatch, caplog):
    """The final write fails (a NUL from the model), so the row keeps its reservation: the conservative outcome."""
    def run_agent(provider, question, region, trace):
        trace.answer_text, trace.label, trace.est_cost_usd = "a NUL\x00 from the model", "refused", 0.01
        return ANSWER | {"trace_id": str(trace.trace_id)}

    monkeypatch.setattr(main, "run_agent", run_agent)
    response = owner_asks()
    assert response.status_code == 200 and "could not write trace" in caplog.text
    with psycopg.connect(db_conninfo()) as admin:
        row = admin.execute("select label, est_cost_usd::float, paid_by from ops.agent_traces where trace_id = %s",
                            (response.json()["trace_id"],)).fetchone()
    assert row == ("error", config.OWNER_RESERVE_USD, "owner")


@pytest.mark.db
def test_concurrent_free_questions_never_spend_past_the_cap(owner_asks, monkeypatch):
    """Twelve visitors at once, each question slow and costing its reservation, with room under the daily cap for
    three: three are answered, nine paused. Counting after the model call let all twelve through."""
    def slow(provider, question, region, trace):
        time.sleep(1)
        trace.est_cost_usd = config.OWNER_RESERVE_USD
        return ANSWER | {"trace_id": str(trace.trace_id)}

    monkeypatch.setattr(main, "run_agent", slow)
    today, month, _ = owner_usage("")
    monkeypatch.setattr(config, "DAILY_SPEND_CAP_USD", today + 3 * config.OWNER_RESERVE_USD - 0.01)
    monkeypatch.setattr(config, "MONTHLY_SPEND_CAP_USD", month + 100)
    with ThreadPoolExecutor(12) as pool:
        statuses = list(pool.map(lambda i: owner_asks(f"198.51.100.{i}").status_code, range(12)))
    assert sorted(statuses) == [200] * 3 + [503] * 9
