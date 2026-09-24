import json

import psycopg
import pytest

from app.guardrails import readonly_db
from app.tools.definitions import TOOLS
from app.tools.handlers import ANOMALIES_SQL, ToolError, for_model, run_tool


@pytest.mark.parametrize(
    "sql",
    ["DROP TABLE marts.fct_primary_sales", "DELETE FROM marts.fct_primary_sales",
     "UPDATE marts.fct_primary_sales SET qty = 0", "INSERT INTO marts.dim_geo VALUES ('700001')"],
)
def test_a_write_statement_is_rejected_before_any_database_call(monkeypatch, sql):
    def must_not_run(*_args, **_kwargs):
        raise AssertionError("a rejected statement reached the database layer")

    monkeypatch.setattr(readonly_db, "run", must_not_run)
    monkeypatch.setattr(psycopg, "connect", must_not_run)
    with pytest.raises(ToolError, match="Rejected by the SQL validator before execution: .*forbidden_statement"):
        run_tool("run_readonly_sql", {"sql": sql}, "ALL")


def test_valid_ad_hoc_sql_runs_normalised_and_capped_under_the_claim(fake_db):
    result = run_tool("run_readonly_sql", {"sql": "select region from dim_distributor"}, "Odisha")
    assert fake_db.calls == [("SELECT * FROM (SELECT region FROM marts.dim_distributor) AS q LIMIT 500", None, "Odisha")]
    assert result["label"] == "ad_hoc_sql_verify"


def test_query_metric_compiles_then_executes_under_the_region_claim(fake_db, fake_semantic):
    tool_input = {
        "metric_name": "dso",
        "filters": [{"dimension": "distributor_id", "op": "=", "value": "D0042"}],
        "group_by": ["month"],
        "date_range": {"start": "2026-01-01", "end": "2026-06-30"},
    }
    result = run_tool("query_metric", tool_input, "Assam")
    assert fake_semantic == [{**tool_input, "region_claim": "Assam"}]
    assert fake_db.calls[0][1:] == ({"region": "Assam"}, "Assam")
    assert result["label"] == "governed_metric" and result["data"]["rows"] == fake_db.result.rows


def test_an_unknown_metric_is_a_tool_error_and_runs_nothing(fake_db, fake_semantic):
    with pytest.raises(ToolError, match="No governed metric"):
        run_tool("query_metric", {"metric_name": "revenue", "filters": [], "group_by": [], "date_range": None}, "ALL")
    assert fake_db.calls == []


def test_query_metric_on_the_real_semantic_layer_runs_the_compiled_sql(fake_db):
    tool_input = {"metric_name": "dso", "filters": [{"dimension": "distributor__region", "op": "=", "value": "Assam"}],
                  "group_by": ["metric_time__month"], "date_range": None}
    run_tool("query_metric", tool_input, "Assam")
    ((sql, params, region),) = fake_db.calls
    assert '"marts"."fct_invoice_collections"' in sql and "distributor__region = 'Assam'" in sql
    assert (params, region) == ({}, "Assam")


def test_a_query_the_semantic_layer_rejects_is_a_tool_error_and_runs_nothing(fake_db):
    tool_input = {"metric_name": "dso", "filters": [], "group_by": ["product__category"], "date_range": None}
    with pytest.raises(ToolError, match="can't be grouped by product__category"):
        run_tool("query_metric", tool_input, "ALL")
    assert fake_db.calls == []


def test_database_errors_are_tool_errors(monkeypatch):
    def fail(*_args):
        raise readonly_db.QueryError('relation "marts.dim_geo" does not exist')

    monkeypatch.setattr(readonly_db, "run", fail)
    with pytest.raises(ToolError, match="does not exist"):
        run_tool("run_readonly_sql", {"sql": "select * from marts.dim_geo"}, "ALL")


def test_get_anomalies_binds_as_of_as_a_parameter(fake_db):
    run_tool("get_anomalies", {"as_of_date": "2026-03-01"}, "ALL")
    assert fake_db.calls == [(ANOMALIES_SQL, {"as_of": "2026-03-01"}, "ALL")]


def test_an_unknown_tool_is_a_tool_error():
    with pytest.raises(ToolError, match="Unknown tool"):
        run_tool("drop_everything", {}, "ALL")


def test_the_model_sees_compact_json_with_the_first_rows_row_count_and_sql():
    rows = [[i] for i in range(120)]
    result = {"label": "governed_metric", "sql": "select n", "row_count": 120, "row_cap_hit": False,
              "data": {"columns": ["n"], "rows": rows}}
    payload = json.loads(for_model("toolu_1", result))
    assert payload == {"tool_use_id": "toolu_1", "label": "governed_metric", "sql": "select n", "row_count": 120,
                       "row_cap_hit": False, "columns": ["n"], "rows": rows[:50], "rows_not_shown": 70}


def _object_schemas(schema):
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            yield schema
        for value in schema.values():
            yield from _object_schemas(value)
    elif isinstance(schema, list):
        for value in schema:
            yield from _object_schemas(value)


def test_the_five_tools_are_strict_sorted_and_closed():
    assert [tool["name"] for tool in TOOLS] == [
        "explain_metric", "get_anomalies", "list_metrics", "query_metric", "run_readonly_sql"]
    assert all(tool["strict"] for tool in TOOLS)
    for schema in _object_schemas([tool["input_schema"] for tool in TOOLS]):
        assert schema["additionalProperties"] is False and schema["required"] == list(schema["properties"])


FLAGS = """(select * from (values
    ('lot_scan', 'resin_lot', 'L1', 'base_crack', null, '2026-01-04'::date, '2026-01-04'::date, 3.0::numeric,
     0.001::numeric, '{}'::jsonb),
    ('lot_scan', 'resin_lot', 'L1', 'base_crack', null, '2026-01-11', '2026-01-04', 3.5, 0.0004, '{"claims": 9}'),
    ('lot_scan', 'resin_lot', 'L1', 'leak', null, '2026-01-11', '2026-01-11', 2.1, 0.003, '{}'),
    ('installer_scan', 'installer', 'I7', null, null, '2026-01-11', '2026-01-11', 2.9, 0.002, '{}'),
    ('stuffing', 'distributor', 'D1', null, 'Assam', '2026-01-11', null, 1.2, null, '{}'),
    ('distributor_health', 'distributor', 'D2', null, 'Odisha', '2026-01-18', '2026-01-18', 1.8, null, '{}')
) v(detector, entity_type, entity_id, failure_mode, region, snapshot_date, first_flag_date, effect_size, p_value,
    details))"""


@pytest.mark.db
@pytest.mark.parametrize(
    ("as_of", "expected"),
    [("2026-01-11", [("installer_scan", "I7", None, "2026-01-11"), ("lot_scan", "L1", "base_crack", "2026-01-11"),
                     ("lot_scan", "L1", "leak", "2026-01-11")]),
     ("2026-01-04", [("lot_scan", "L1", "base_crack", "2026-01-04")]),
     (None, [("distributor_health", "D2", None, "2026-01-18"), ("installer_scan", "I7", None, "2026-01-11"),
             ("lot_scan", "L1", "base_crack", "2026-01-11"), ("lot_scan", "L1", "leak", "2026-01-11")])],
)
def test_anomalies_are_the_latest_snapshot_per_entity_flagged_by_as_of(as_of, expected):
    result = readonly_db.run(ANOMALIES_SQL.replace("marts.mart_anomaly_flags", FLAGS), {"as_of": as_of}, "ALL")
    at = result.columns.index
    rows = [(r[at("detector")], r[at("entity_id")], r[at("failure_mode")], r[at("snapshot_date")]) for r in result.rows]
    assert rows == expected
    assert result.columns[4:6] == ["failure_mode", "region"]
