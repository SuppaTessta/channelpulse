import datetime as dt
import decimal
import uuid

import pytest

from app import config
from app.guardrails import readonly_db
from app.guardrails.readonly_db import QueryError, json_safe, run


@pytest.mark.parametrize(
    ("value", "expected"),
    [(decimal.Decimal("12.50"), 12.5), (dt.date(2026, 9, 1), "2026-09-01"),
     (dt.datetime(2026, 9, 1, 8, 30, tzinfo=dt.UTC), "2026-09-01T08:30:00+00:00"), (dt.timedelta(days=2), 172800.0),
     (float("nan"), None), (decimal.Decimal("Infinity"), None), (True, True), (None, None),
     ({"rate": decimal.Decimal("4.1"), "dates": [dt.date(2026, 1, 4)]}, {"rate": 4.1, "dates": ["2026-01-04"]}),
     (uuid.UUID(int=1), "00000000-0000-0000-0000-000000000001")],
)
def test_values_come_back_json_safe(value, expected):
    assert json_safe(value) == expected


# The rest runs against Postgres as channelpulse_agent, calling the executor directly: no SQL validator in front,
# so these show the database role is the hard boundary on its own.


@pytest.mark.db
def test_rows_come_back_json_safe_with_their_columns():
    result = run("select 1.50::numeric as amount, date '2026-09-01' as day, 'x' as label", None, "ALL")
    assert (result.columns, result.rows) == (["amount", "day", "label"], [[1.5, "2026-09-01", "x"]])


@pytest.mark.db
def test_the_query_runs_under_the_region_claim():
    assert run("select current_setting('app.region', true) as claim", None, "Assam").rows == [["Assam"]]


@pytest.mark.db
def test_the_transaction_stays_read_only_even_if_sql_asks_otherwise():
    with pytest.raises(QueryError, match="read-write"):
        run("select set_config('transaction_read_only', 'off', true)", None, "ALL")


@pytest.mark.db
@pytest.mark.parametrize("sql", ["create table marts.cp_probe (x int)", "create temp table cp_probe (x int)"])
def test_the_agent_role_cannot_create_anything(sql):
    with pytest.raises(QueryError):
        run(sql, None, "ALL")


@pytest.mark.db
def test_the_agent_role_cannot_read_ops():
    with pytest.raises(QueryError, match="permission denied"):
        run("select * from ops.agent_traces", None, "ALL")


@pytest.mark.db
def test_a_second_statement_is_refused_at_the_protocol_level():
    with pytest.raises(QueryError, match="multiple commands"):
        run("select 1; select 2", None, "ALL")


@pytest.mark.db
def test_the_statement_timeout_cancels_slow_queries(monkeypatch):
    monkeypatch.setattr(config, "STATEMENT_TIMEOUT_MS", 100)
    with pytest.raises(QueryError, match="statement timeout"):
        run("select pg_sleep(2)", None, "ALL")


@pytest.mark.db
def test_rows_are_capped(monkeypatch):
    monkeypatch.setattr(config, "ROW_CAP", 10)
    result = run("select generate_series(1, 25) as n", None, "ALL")
    assert len(result.rows) == 10 and result.row_cap_hit


@pytest.mark.db
def test_the_sql_shown_has_its_params_inlined():
    result = run("select %(region)s::text as region", {"region": "North Bengal & Sikkim"}, "ALL")
    assert result.sql == "select 'North Bengal & Sikkim'::text as region"
    assert result.rows == [["North Bengal & Sikkim"]]


@pytest.mark.db
def test_the_mart_catalog_lists_only_allowlisted_marts(monkeypatch):
    monkeypatch.setattr(readonly_db, "_catalog", (0.0, {}))
    assert set(readonly_db.mart_columns()) <= config.MART_TABLES
