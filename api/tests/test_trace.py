import psycopg
import pytest

from app.agent.providers import Turn, Usage
from app.agent.trace import Trace, price, write_trace
from app.db import db_conninfo, ops_conninfo


def response(model="claude-sonnet-5-5", input_tokens=0, output_tokens=0, cache_read_input_tokens=0,
             cache_creation_input_tokens=0):
    usage = Usage(input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens)
    return Turn("end_turn", "", [], usage, model)


@pytest.mark.parametrize(
    ("model", "expected"),
    [("claude-sonnet-5-5", (2.0, 10.0, 0.20)), ("claude-sonnet-5", (2.0, 10.0, 0.20)),
     ("claude-haiku-5-5", (0.10, 0.50, 0.01)), ("some-future-model", (2.0, 10.0, 0.20))],
)
def test_models_are_priced_from_the_table_and_unknown_ones_at_the_dearest_rate(model, expected):
    assert price(model) == expected


def test_usage_adds_up_tokens_and_cost_across_rounds():
    trace = Trace(question="q", region_claim="ALL", model="claude-sonnet-5-5")
    trace.add_usage(response(input_tokens=1_000_000, output_tokens=100_000))
    trace.add_usage(response(cache_read_input_tokens=1_000_000, cache_creation_input_tokens=1_000_000))
    assert (trace.input_tokens, trace.output_tokens, trace.cache_read_tokens, trace.cache_write_tokens) == (
        1_000_000, 100_000, 1_000_000, 1_000_000)
    assert trace.est_cost_usd == pytest.approx(2.0 + 1.0 + 0.2 + 2.5)  # input, output, cache read, cache write


def test_cost_is_priced_at_the_model_that_served_the_response():
    trace = Trace(question="q", region_claim="ALL", model="claude-haiku-5-5")
    trace.add_usage(response(model="claude-sonnet-5", output_tokens=1_000_000))
    assert (trace.served_model, trace.est_cost_usd) == ("claude-sonnet-5", pytest.approx(10.0))


@pytest.mark.db
def test_a_trace_row_is_written_and_readable_by_the_ops_role():
    trace = Trace(question="pytest probe", region_claim="Assam", model="claude-sonnet-5-5", label="refused",
                  tool_calls=[{"id": "toolu_1", "name": "list_metrics", "error": None}], final_sql=["select 1"],
                  est_cost_usd=0.000123456, paid_by="visitor", visitor="0f" * 16)
    write_trace(trace)
    try:
        with psycopg.connect(ops_conninfo()) as ops:
            row = ops.execute(
                "select question, region_claim, label, tool_calls, final_sql, est_cost_usd::float, created_at is not null,"
                " paid_by, visitor from ops.agent_traces where trace_id = %s", (trace.trace_id,)).fetchone()
        assert row == ("pytest probe", "Assam", "refused", trace.tool_calls, ["select 1"], 0.00012, True, "visitor",
                       "0f" * 16)
    finally:
        with psycopg.connect(db_conninfo()) as admin:
            admin.execute("delete from ops.agent_traces where trace_id = %s", (trace.trace_id,))


@pytest.mark.db
def test_writing_a_trace_again_replaces_its_row():
    """A free question's reservation, then its real values (guardrails/rate_limit)."""
    trace = Trace(question="pytest probe", region_claim="ALL", model="claude-sonnet-5-5", est_cost_usd=0.3)
    write_trace(trace)
    trace.label, trace.est_cost_usd = "refused", 0.01
    write_trace(trace)
    try:
        with psycopg.connect(ops_conninfo()) as ops:
            rows = ops.execute("select label, est_cost_usd::float from ops.agent_traces where trace_id = %s",
                               (trace.trace_id,)).fetchall()
        assert rows == [("refused", 0.01)]
    finally:
        with psycopg.connect(db_conninfo()) as admin:
            admin.execute("delete from ops.agent_traces where trace_id = %s", (trace.trace_id,))
