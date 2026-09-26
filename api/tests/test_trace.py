from types import SimpleNamespace

import psycopg
import pytest

from app.agent.trace import Trace, price, write_trace
from app.db import db_conninfo, ops_conninfo


def response(model="claude-opus-5", **usage):
    tokens = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    return SimpleNamespace(model=model, usage=SimpleNamespace(**{**tokens, **usage}))


@pytest.mark.parametrize(
    ("model", "expected"),
    [("claude-opus-5-5", (4.0, 20.0, 0.20)), ("claude-opus-5", (5.0, 25.0, 0.50)), ("claude-sonnet-5", (2.0, 10.0, 0.20)),
     ("claude-haiku-4-5-20251001", (1.0, 5.0, 0.10)), ("claude-opus-4-8", (5.0, 25.0, 0.50)),
     ("some-future-model", (10.0, 50.0, 0.25))],
)
def test_models_are_priced_from_the_table_and_unknown_ones_at_the_dearest_rate(model, expected):
    assert price(model) == expected


def test_cache_reads_bill_at_each_models_own_rate():
    trace = Trace(question="q", region_claim="ALL", model="claude-opus-5-5")
    trace.add_usage(response(model="claude-opus-5-5", cache_read_input_tokens=1_000_000))
    assert trace.est_cost_usd == pytest.approx(0.20)  # 0.05x input on Opus 5.5, not the usual 0.1x


def test_usage_adds_up_tokens_and_cost_across_rounds():
    trace = Trace(question="q", region_claim="ALL", model="claude-opus-5")
    trace.add_usage(response(input_tokens=1_000_000, output_tokens=100_000))
    trace.add_usage(response(cache_read_input_tokens=1_000_000, cache_creation_input_tokens=1_000_000))
    assert (trace.input_tokens, trace.output_tokens, trace.cache_read_tokens, trace.cache_write_tokens) == (
        1_000_000, 100_000, 1_000_000, 1_000_000)
    assert trace.est_cost_usd == pytest.approx(5.0 + 2.5 + 0.5 + 6.25)  # input, output, cache read, cache write


def test_cost_is_priced_at_the_model_that_served_the_response():
    trace = Trace(question="q", region_claim="ALL", model="claude-sonnet-5")
    trace.add_usage(response(model="claude-opus-4-8", output_tokens=1_000_000))
    assert (trace.served_model, trace.est_cost_usd) == ("claude-opus-4-8", pytest.approx(25.0))


@pytest.mark.db
def test_a_trace_row_is_written_and_readable_by_the_ops_role():
    trace = Trace(question="pytest probe", region_claim="Assam", model="claude-opus-5", label="refused",
                  tool_calls=[{"id": "toolu_1", "name": "list_metrics", "error": None}], final_sql=["select 1"],
                  est_cost_usd=0.000123456)
    write_trace(trace)
    try:
        with psycopg.connect(ops_conninfo()) as ops:
            row = ops.execute(
                "select question, region_claim, label, tool_calls, final_sql, est_cost_usd::float, created_at is not null"
                " from ops.agent_traces where trace_id = %s", (trace.trace_id,)).fetchone()
        assert row == ("pytest probe", "Assam", "refused", trace.tool_calls, ["select 1"], 0.00012, True)
    finally:
        with psycopg.connect(db_conninfo()) as admin:
            admin.execute("delete from ops.agent_traces where trace_id = %s", (trace.trace_id,))
