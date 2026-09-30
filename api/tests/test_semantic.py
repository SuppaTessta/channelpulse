"""The MetricFlow semantic layer on the shipped manifest. No database; only the staleness check needs dbt."""

import json
import subprocess
from pathlib import Path

import pytest
import sqlglot
from sqlglot import exp

from app import admin, config, semantic
from app.guardrails import readonly_db
from app.guardrails.sql_validator import validate
from app.semantic import InvalidQuery, UnknownMetric

GLOSSARY_QUERIES = {
    "primary_sales_value": ["metric_time__month", "distributor__region"],
    "secondary_sales_value": ["metric_time__quarter", "product__category"],
    "channel_days_of_stock": ["metric_time__week", "distributor__region"],
    "claims_per_1000_units": ["batch__plant_id", "batch__resin_lot_id"],
    "dso": ["distributor"],
    "distributor_health_score": ["metric_time__week", "distributor__tier"],
    "stockout_rate": ["distributor__region", "product__category"],
    "overstock_rate": ["metric_time__month"],
    "scheme_concentration_ratio": ["distributor_scheme_window__fiscal_quarter_label"],
    "warranty_registration_rate": ["batch__plant_id"],
    "collections_efficiency": ["metric_time__month", "distributor__state"],
    "installer_claim_rate": ["installer", "installer_cohort_month__install_district"],
}
ENTRIES = {entry["name"]: entry for entry in semantic.list_metrics()}
MANIFEST_METRICS = json.loads(Path(semantic.__file__).with_name("semantic_manifest.json").read_text(encoding="utf-8"))["metrics"]
REGION = "distributor__region"


def compile_sql(metric="primary_sales_value", group_by=("metric_time__month",), filters=(), date_range=None) -> str:
    query = semantic.compile_query(metric, list(filters), list(group_by), date_range, "ALL")
    assert query["params"] == {}
    return query["sql"]


def region_is(value) -> list[dict]:
    return [{"dimension": REGION, "op": "=", "value": value}]


def test_the_glossary_queries_cover_exactly_the_twelve_plan_metrics():
    assert set(GLOSSARY_QUERIES) == semantic.GLOSSARY == {name for name, entry in ENTRIES.items() if entry["glossary"]}


@pytest.mark.parametrize(("metric", "group_by"), GLOSSARY_QUERIES.items(), ids=GLOSSARY_QUERIES)
def test_every_glossary_metric_compiles_to_one_safe_select_on_the_marts(metric, group_by):
    sql = compile_sql(metric, group_by)
    tree = sqlglot.parse_one(sql, read="postgres")
    assert set(tree.named_selects) == {*group_by, metric}
    assert validate(sql, config.MART_TABLES, config.ROW_CAP).ok
    assert {(table.catalog, table.db) for table in tree.find_all(exp.Table)} == {("", "marts")}
    assert sql.endswith(f"LIMIT {config.ROW_CAP}") and "--" not in sql


@pytest.mark.parametrize("metric", sorted(ENTRIES))
def test_every_offered_dimension_compiles(metric):
    entry = ENTRIES[metric]
    group_by = [d for d in entry["dimensions"] if not d.startswith("metric_time__")]
    compile_sql(metric, [*group_by, f"metric_time__{entry['default_time_grain']}"])


def test_the_example_query_compiles_as_expected():
    assert compile_sql(group_by=["metric_time__month", REGION]) == EXAMPLE_SQL


def test_list_metrics_is_sorted_complete_and_rebuilds_identically():
    first = semantic.list_metrics()
    for cached in (semantic._manifest, semantic._engine, semantic._metrics, semantic._glossary):
        cached.cache_clear()
    assert json.dumps(first, sort_keys=True) == json.dumps(semantic.list_metrics(), sort_keys=True)
    assert [entry["name"] for entry in first] == sorted(ENTRIES) and len(first) == len(MANIFEST_METRICS)
    assert set(first[0]) == {"name", "label", "description", "type", "formula", "time_dimension",
                             "default_time_grain", "dimensions", "glossary"}


def test_the_offered_dimensions_are_the_useful_ones():
    sales = set(ENTRIES["primary_sales_value"]["dimensions"])
    assert {REGION, "product__category", "distributor", "metric_time__month", "metric_time__year"} <= sales
    assert not sales & {"invoice__distributor__region", "batch__product__category", "invoice__due_date"}
    assert "inventory_day" not in ENTRIES["channel_days_of_stock"]["dimensions"]
    assert "batch__product__category" in ENTRIES["claims_per_1000_units"]["dimensions"]  # its only path to category
    assert [d for d in ENTRIES["installer_claim_rate"]["dimensions"] if d.startswith("metric_time__")] == [
        "metric_time__fiscal_quarter", "metric_time__fiscal_year", "metric_time__month", "metric_time__quarter",
        "metric_time__year"]  # its own grain up, plus the fiscal grains (D36)


def test_formulas_and_time_dimensions_are_summarised():
    assert ENTRIES["primary_sales_value"]["formula"] == "sum(primary_value_inr)"
    assert ENTRIES["dso"]["formula"] == "invoiced_amount_days / invoiced_amount"
    assert ENTRIES["collected_within_terms"]["formula"] == "sum(paid_within_terms_inr), over rows where invoice__is_due"
    assert (ENTRIES["claims_per_1000_units"]["time_dimension"], ENTRIES["distributor_health_score"]["default_time_grain"]) == (
        "mfg_date", "week")


def test_explain_metric_gives_the_definition_formula_compiled_sql_and_caveats():
    dso = semantic.explain_metric("dso")
    assert dso["formula"]["inputs"] == {
        "invoiced_amount_days": "sum(invoice_amount_inr * days_outstanding)", "invoiced_amount": "sum(invoice_amount_inr)"}
    assert dso["example_group_by"] == ["metric_time__month"] and validate(dso["sql"], config.MART_TABLES, 500).ok
    assert dso["definition"].startswith("Amount-weighted")


@pytest.mark.parametrize(
    ("metric", "caveat"),
    [("channel_days_of_stock", "period's last day"), ("channel_stock_units", "period's last day"),
     ("cohort_cumulative_claims_per_1000", "batch_cohort_month__months_since_ship"),
     ("claims_per_1000_units", "manufacture date"), ("dso", "as-of date"),
     ("secondary_sales_value", "secondary_sale__is_settled = true")],
)
def test_explain_metric_states_the_caveats(metric, caveat):
    assert any(caveat in text for text in semantic.explain_metric(metric)["caveats"])


def test_additive_rates_carry_no_snapshot_caveat():
    assert not any("snapshot" in text for text in semantic.explain_metric("stockout_rate")["caveats"])


def test_the_cohort_curve_example_groups_by_age():
    assert semantic.explain_metric("cohort_cumulative_claims_per_1000")["example_group_by"] == [
        "batch_cohort_month__months_since_ship"]


def test_an_unknown_metric_suggests_close_names():
    with pytest.raises(UnknownMetric, match="Did you mean primary_sales_value"):
        compile_sql("primary_sale_value")
    with pytest.raises(UnknownMetric):
        semantic.explain_metric("revenue")


@pytest.mark.parametrize(
    ("condition", "rendered"),
    [({"dimension": REGION, "op": "=", "value": "Assam"}, "distributor__region = 'Assam'"),
     ({"dimension": REGION, "op": "!=", "value": "Assam"}, "distributor__region <> 'Assam'"),
     ({"dimension": REGION, "op": "in", "value": ["Assam", "North Bengal & Sikkim"]},
      "distributor__region IN ('Assam', 'North Bengal & Sikkim')"),
     ({"dimension": REGION, "op": "not_in", "value": ["Odisha"]}, "distributor__region NOT IN ('Odisha')"),
     ({"dimension": "distributor__distributor_name", "op": "=", "value": "O'Brien Traders"},
      "distributor__distributor_name = 'O''Brien Traders'"),
     ({"dimension": "product__capacity_l", "op": ">=", "value": 1000}, "product__capacity_l >= 1000"),
     ({"dimension": "product__capacity_l", "op": "<", "value": 2.5}, "product__capacity_l < 2.5"),
     ({"dimension": "primary_sale_line__is_scheme_invoice", "op": "=", "value": True},
      "primary_sale_line__is_scheme_invoice = TRUE"),
     ({"dimension": "metric_time__day", "op": ">=", "value": "2026-01-01"}, "metric_time__day >= '2026-01-01'"),
     ({"dimension": "distributor", "op": "in", "value": ["D0042", "D0043"]}, "distributor IN ('D0042', 'D0043')")],
)
def test_filters_compile_to_checked_literals(condition, rendered):
    assert rendered in compile_sql(filters=[condition])


@pytest.mark.parametrize(
    "condition",
    [{"dimension": "claim__failure_mode", "op": "=", "value": "leak"},  # not a dimension of this metric
     {"dimension": REGION, "op": "like", "value": "A%"},
     {"dimension": REGION, "op": "in", "value": "Assam"},
     {"dimension": REGION, "op": "in", "value": []},
     {"dimension": REGION, "op": "in", "value": ["Assam"] * 201},
     {"dimension": REGION, "op": "=", "value": ["Assam"]},
     {"dimension": REGION, "op": "=", "value": None},
     {"dimension": REGION, "op": "=", "value": {"region": "Assam"}},
     {"dimension": REGION, "op": "=", "value": float("nan")},
     {"dimension": REGION, "op": "=", "value": "x" * 201},
     {"dimension": "metric_time__day", "op": ">=", "value": "01/02/2026"},
     {"dimension": "metric_time__day", "op": ">=", "value": "2026-02-30"},
     {"dimension": "metric_time__day", "op": ">=", "value": 20260101}],
)
def test_invalid_filters_are_rejected(condition):
    with pytest.raises(InvalidQuery):
        compile_sql(filters=[condition])


@pytest.mark.parametrize(
    "payload",
    ["'; drop table marts.dim_geo; --", "') or 1=1 --", "' or '1'='1", "x' union select rolname from pg_roles --",
     "Assam'; select pg_sleep(10); --", "Assam' -- ", "''''"],
)
def test_quote_injection_stays_inside_one_string_literal(payload):
    sql = compile_sql(filters=region_is(payload))
    assert validate(sql, config.MART_TABLES, config.ROW_CAP).ok  # one SELECT, no writes, no catalog, no pg_*
    tree = sqlglot.parse_one(sql, read="postgres")
    assert payload in [literal.this for literal in tree.find_all(exp.Literal) if literal.is_string]
    assert not list(tree.find_all(exp.Union, exp.Drop))


@pytest.mark.parametrize(
    "payload",
    ["{{ 7*7 }}", "{% for x in range(3) %}x{% endfor %}", "{# hidden #}", "{{ \"'\" }} or 1=1 --", "a}b",
     "line\nbreak", "nul\x00byte", "tab\there", "del\x7f", "\\' or 1=1 --"],
)
def test_values_that_could_run_as_jinja_or_escape_the_literal_are_rejected(payload):
    # MetricFlow renders every filter as a Jinja template: "{{ 7*7 }}" would become 49, and {{ "'" }} a raw quote.
    with pytest.raises(InvalidQuery):
        compile_sql(filters=region_is(payload))


@pytest.mark.parametrize(
    ("group_by", "filters"),
    [(["distributor__region; drop table marts.dim_geo"], []),
     (["pg_catalog.pg_roles"], []),
     ([], [{"dimension": "distributor__region') }} or 1=1 --", "op": "=", "value": "x"}]),
     ([], [{"dimension": REGION, "op": "= 'x' or 1 =", "value": "1"}])],
)
def test_names_and_ops_outside_the_allowlist_are_rejected(group_by, filters):
    with pytest.raises(InvalidQuery):
        compile_sql(group_by=group_by, filters=filters)


def test_a_grain_finer_than_the_metrics_own_is_rejected():
    with pytest.raises(InvalidQuery, match="can't be grouped by metric_time__day"):
        compile_sql("installer_claim_rate", ["metric_time__day"])


def test_the_date_range_is_an_inclusive_time_constraint():
    sql = compile_sql("dso", date_range={"start": "2026-01-01", "end": "2026-03-31"})
    assert "BETWEEN '2026-01-01' AND '2026-03-31'" in sql


@pytest.mark.parametrize(
    "date_range",
    [{"start": "2026-03-31", "end": "2026-01-01"}, {"start": "2026-01-01' or '1'='1", "end": "2026-03-31"},
     {"start": "yesterday", "end": "2026-03-31"}, {"start": "2026-13-01", "end": "2026-12-31"}],
)
def test_bad_date_ranges_are_rejected(date_range):
    with pytest.raises(InvalidQuery):
        compile_sql("dso", date_range=date_range)


def test_time_series_come_back_in_time_order_and_breakdowns_largest_first():
    assert compile_sql(group_by=["metric_time__month", REGION]).endswith(
        "ORDER BY metric_time__month, distributor__region\nLIMIT 500")
    assert compile_sql(group_by=[REGION]).endswith("ORDER BY primary_sales_value DESC, distributor__region\nLIMIT 500")


def test_portable_drops_the_database_and_sorts_by_name():
    relation = {"alias": "dim_geo", "schema_name": "marts", "database": "postgres",
                "relation_name": '"postgres"."marts"."dim_geo"'}
    manifest = {"semantic_models": [{"name": "b", "node_relation": dict(relation)}, {"name": "a", "node_relation": dict(relation)}],
                "metrics": [], "saved_queries": [], "project_configuration": {"time_spines": [{"node_relation": dict(relation)}]}}
    result = semantic.portable(manifest)
    assert [model["name"] for model in result["semantic_models"]] == ["a", "b"]
    assert result["project_configuration"]["time_spines"][0]["node_relation"] == {
        **relation, "database": None, "relation_name": '"marts"."dim_geo"'}


def test_the_shipped_manifest_names_no_database():
    shipped = json.loads(semantic.MANIFEST_PATH.read_text(encoding="utf-8"))
    relations = [model["node_relation"] for model in shipped["semantic_models"]]
    relations += [spine["node_relation"] for spine in shipped["project_configuration"]["time_spines"]]
    assert relations and all(relation["database"] is None for relation in relations)


@pytest.mark.skipif(not admin.WAREHOUSE_DIR.is_dir(), reason="needs the warehouse/ dbt project")
def test_the_shipped_manifest_matches_the_warehouse_definitions(tmp_path):
    try:
        fresh = admin.parse_semantic_manifest(tmp_path)
    except admin.DbtUnavailable as e:  # an install problem; a definition dbt rejects still fails the test
        pytest.skip(str(e))
    assert fresh == json.loads(semantic.MANIFEST_PATH.read_text(encoding="utf-8")), (
        "api/app/semantic_manifest.json is stale: run `.venv/Scripts/python.exe api/app/admin.py semantic`")


@pytest.mark.parametrize(
    ("output", "error"),
    [("ImportError: DLL load failed while importing _psycopg", admin.DbtUnavailable),
     ("Parsing Error: Invalid metrics config given in warehouse/semantic_models/sales.yml", RuntimeError)],
)
def test_only_a_broken_dbt_install_counts_as_dbt_unavailable(monkeypatch, tmp_path, output, error):
    failed = subprocess.CompletedProcess(args=[], returncode=2, stdout="", stderr=output)
    monkeypatch.setattr(admin.subprocess, "run", lambda *_args, **_kwargs: failed)
    with pytest.raises(RuntimeError, match="dbt parse failed") as caught:
        admin.parse_semantic_manifest(tmp_path)
    assert type(caught.value) is error


@pytest.mark.db
def test_a_compiled_query_runs_read_only_on_the_marts():
    built = readonly_db.run("select to_regclass('marts.fct_primary_sales') is not null as built", None, "ALL")
    if not built.rows[0][0]:
        pytest.skip("the marts aren't built yet (dbt build)")
    query = semantic.compile_query("primary_sales_value", [], ["metric_time__month", REGION], None, "ALL")
    result = readonly_db.run(query["sql"], query["params"], "ALL")
    assert result.columns == ["metric_time__month", "distributor__region", "primary_sales_value"]


EXAMPLE_SQL = """\
SELECT
  DATE_TRUNC('month', primary_sales_src_10000.invoice_date) AS metric_time__month
  , distributors_src_10000.region AS distributor__region
  , SUM(primary_sales_src_10000.primary_value_inr) AS primary_sales_value
FROM "marts"."fct_primary_sales" primary_sales_src_10000
LEFT OUTER JOIN
  "marts"."dim_distributor" distributors_src_10000
ON
  primary_sales_src_10000.distributor_id = distributors_src_10000.distributor_id
GROUP BY
  DATE_TRUNC('month', primary_sales_src_10000.invoice_date)
  , distributors_src_10000.region
ORDER BY metric_time__month, distributor__region
LIMIT 500"""


# --- the Indian fiscal year as a time grain (decisions D36) -------------------------------------------------------


def test_the_fiscal_grains_are_offered_next_to_the_calendar_ones():
    dims = set(ENTRIES["primary_sales_value"]["dimensions"])
    assert {"metric_time__fiscal_year", "metric_time__fiscal_quarter", "metric_time__year"} <= dims


def _fiscal(metric, group_by, filters=()):
    built = readonly_db.run("select to_regclass('marts.fct_primary_sales') is not null as built", None, "ALL")
    if not built.rows[0][0]:
        pytest.skip("the marts aren't built yet (dbt build)")
    query = semantic.compile_query(metric, list(filters), group_by, None, "ALL")
    result = readonly_db.run(query["sql"], query["params"], "ALL")
    return [dict(zip(result.columns, row, strict=True)) for row in result.rows]


@pytest.mark.db
def test_fiscal_year_sales_match_the_eval_golden_answer():
    # TC01's golden SQL: invoice dates April 2024 to March 2025 (FY25) and April 2025 to March 2026 (FY26).
    rows = {r["metric_time__fiscal_year"]: float(r["primary_sales_value"])
            for r in _fiscal("primary_sales_value", ["metric_time__fiscal_year"])}
    assert rows["FY25"] == pytest.approx(4_563_765_266.46) and rows["FY26"] == pytest.approx(4_890_601_104.28)


@pytest.mark.db
def test_fiscal_year_claims_by_plant_match_the_eval_golden_answer():
    # TC05's golden SQL: base-crack claims by claim date, per plant, FY25 and FY26.
    base_crack = [{"dimension": "claim__failure_mode", "op": "=", "value": "base_crack"}]
    rows = {(r["batch__plant_id"], r["metric_time__fiscal_year"]): r["warranty_claims"]
            for r in _fiscal("warranty_claims", ["metric_time__fiscal_year", "batch__plant_id"], base_crack)}
    assert [rows[(p, fy)] for p in ("DGP", "GHY", "HWH") for fy in ("FY25", "FY26")] == [538, 755, 592, 709, 1113, 1341]
