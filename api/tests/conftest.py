"""Shared fakes. Nothing here needs a database or an Anthropic key; @pytest.mark.db tests skip without Postgres."""

import copy
import dataclasses
import functools
import json
from types import SimpleNamespace

import psycopg
import pytest
from anthropic.types.beta import BetaMessage
from fastapi.testclient import TestClient

from app import main, semantic
from app.db import agent_conninfo, ops_conninfo
from app.guardrails import rate_limit, readonly_db

METRICS = [  # the shape semantic.list_metrics() returns
    {
        "name": "dso",
        "label": "DSO (days)",
        "description": "Amount-weighted average days from invoice to full payment.",
        "type": "ratio",
        "formula": "invoiced_amount_days / invoiced_amount",
        "time_dimension": "invoice_date",
        "default_time_grain": "day",
        "dimensions": ["distributor", "distributor__region", "metric_time__day", "metric_time__month"],
        "glossary": True,
    },
    {
        "name": "primary_sales_value",
        "label": "Primary sales value (₹)",
        "description": "Sell-in to distributors, net of scheme discounts.",
        "type": "simple",
        "formula": "sum(primary_value_inr)",
        "time_dimension": "invoice_date",
        "default_time_grain": "day",
        "dimensions": ["distributor", "distributor__region", "metric_time__day", "metric_time__month", "product__category"],
        "glossary": True,
    },
]
GOVERNED_SQL = "select month, dso_days from marts.fct_invoice_collections where region = %(region)s"


def pytest_configure(config):
    config.addinivalue_line("markers", "db: needs local Postgres with api/sql/roles.sql applied; skipped otherwise")


@functools.cache
def _db_unavailable() -> str | None:
    for role, conninfo in (("channelpulse_agent", agent_conninfo()), ("channelpulse_ops", ops_conninfo())):
        try:
            psycopg.connect(conninfo, connect_timeout=2).close()
        except psycopg.Error as e:
            return f"{role} can't connect ({type(e).__name__}); run `python api/app/admin.py roles` with Postgres up"
    return None


def pytest_runtest_setup(item):
    if item.get_closest_marker("db") and (reason := _db_unavailable()):
        pytest.skip(reason)


class FakeDB:
    """Stands in for readonly_db.run: records (sql, params, region) and returns canned rows."""

    def __init__(self):
        self.calls = []
        self.result = readonly_db.QueryResult(
            sql="", columns=["month", "dso_days"], rows=[["2026-07-01", 41.3], ["2026-08-01", 44.8]],
            row_cap_hit=False, duration_ms=3,
        )

    def run(self, sql, params, region):
        self.calls.append((sql, params, region))
        return dataclasses.replace(self.result, sql=sql)


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(readonly_db, "run", db.run)
    monkeypatch.setattr(readonly_db, "mart_columns", lambda: {"fct_invoice_collections": ["month date", "dso_days numeric"]})
    return db


@pytest.fixture
def fake_semantic(monkeypatch):
    """A two-metric stand-in for the MetricFlow layer (tests/test_semantic.py covers the real one); returns the
    list of compile_query calls."""
    compiled = []

    def compile_query(metric_name, filters, group_by, date_range, region_claim):
        if metric_name not in {m["name"] for m in METRICS}:
            raise semantic.UnknownMetric(f"No governed metric is called {metric_name!r}.")
        compiled.append({"metric_name": metric_name, "filters": filters, "group_by": group_by,
                         "date_range": date_range, "region_claim": region_claim})
        return {"sql": GOVERNED_SQL, "params": {"region": region_claim}}

    monkeypatch.setattr(semantic, "list_metrics", lambda: METRICS)
    monkeypatch.setattr(semantic, "explain_metric", lambda name: {"name": name, "formula": "sum(x) / 0.35"})
    monkeypatch.setattr(semantic, "compile_query", compile_query)
    return compiled


class FakeAnthropic:
    """Replays scripted Messages API responses (as real SDK objects) and records every request."""

    def __init__(self, *responses: dict):
        self.requests = []
        self._responses = list(responses)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **request):
        self.requests.append(copy.deepcopy(request))
        return BetaMessage.model_validate(self._responses.pop(0))


def _message(*content, stop_reason="end_turn", model="claude-opus-5", usage=None, **extra) -> dict:
    tokens = {"input_tokens": 1000, "output_tokens": 200, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    return {
        "id": "msg_test", "type": "message", "role": "assistant", "model": model, "content": list(content),
        "stop_reason": stop_reason, "stop_sequence": None, "usage": {**tokens, **(usage or {})}, **extra,
    }


def _tool_use(tool_use_id: str, name: str, tool_input: dict) -> dict:
    return {"type": "tool_use", "id": tool_use_id, "name": name, "input": tool_input}


def _answer(**fields) -> dict:
    """The final structured-output turn's text block."""
    final = {
        "answer_text": "", "refused": False, "refusal_reason": None, "evidence_tool_use_ids": [],
        "chart_hint": {"type": "none", "x": None, "y": None, "series": None}, **fields,
    }
    return {"type": "text", "text": json.dumps(final)}


@pytest.fixture
def claude():
    """Builders for scripted conversations: claude.client(claude.message(claude.tool_use(...), ...), ...)."""
    return SimpleNamespace(client=FakeAnthropic, message=_message, tool_use=_tool_use, answer=_answer)


@pytest.fixture
def api(monkeypatch, fake_db, fake_semantic):
    """TestClient with fakes behind every endpoint; captured traces in api.traces, LLM via api.use_llm(client)."""
    traces = []
    monkeypatch.setattr(main, "write_trace", traces.append)
    monkeypatch.setattr(rate_limit, "spent_today_usd", lambda: 0.0)
    monkeypatch.setattr(rate_limit, "ask_bucket", rate_limit.TokenBucket(rate_per_min=600, burst=100))

    def use_llm(client):
        main.app.dependency_overrides[main.llm_client] = lambda: client

    yield SimpleNamespace(http=TestClient(main.app), traces=traces, db=fake_db, use_llm=use_llm)
    main.app.dependency_overrides.clear()
