import pytest
import sqlglot

from app.config import MART_TABLES
from app.guardrails.sql_validator import validate

CAP = 500


def check(sql: str):
    return validate(sql, MART_TABLES, CAP)


def reasons(sql: str) -> tuple[str, ...]:
    result = check(sql)
    assert not result.ok and result.sql is None
    return result.reasons


def statement_count(sql: str) -> int:
    return len(sqlglot.parse(sql, read="postgres"))


WRITES = {
    "drop": "drop table marts.fct_primary_sales",
    "delete": "delete from marts.fct_primary_sales",
    "update": "update marts.fct_primary_sales set qty = 0",
    "insert": "insert into marts.fct_primary_sales select * from marts.fct_primary_sales",
    "truncate": "truncate marts.fct_primary_sales",
    "alter": "alter table marts.fct_primary_sales add column x int",
    "create": "create table marts.fct_copy as select * from marts.fct_primary_sales",
    "grant": "grant select on marts.fct_primary_sales to public",
    "revoke": "revoke select on marts.fct_primary_sales from public",
    "copy": "copy marts.fct_primary_sales to '/tmp/out.csv'",
    "merge": "merge into marts.dim_geo g using marts.dim_geo s on true when matched then delete",
}


@pytest.mark.parametrize("sql", WRITES.values(), ids=WRITES.keys())
def test_every_write_verb_is_rejected(sql):
    assert any(reason.startswith("forbidden_statement:") for reason in reasons(sql))


@pytest.mark.parametrize(
    "sql",
    ["set search_path = raw", "begin", "commit", "explain analyze delete from marts.dim_geo",
     "do $$ begin perform 1; end $$", "call refresh()", "lock table marts.dim_geo", "listen ch", "discard all",
     "comment on table marts.dim_geo is 'x'", "values (1)", "(select 1)"],
)
def test_anything_but_a_top_level_select_is_rejected(sql):
    assert not check(sql).ok


@pytest.mark.parametrize(
    "sql",
    ["select 1; drop table marts.fct_primary_sales", "select 1;select 2",
     "select * from marts.dim_geo; delete from marts.dim_geo"],
)
def test_stacked_statements_are_rejected(sql):
    assert reasons(sql) == ("multiple_statements",)


@pytest.mark.parametrize(
    "sql",
    ["select 1 -- ; drop table marts.dim_geo",
     "select 1 /* ; drop table marts.dim_geo */",
     "select 1 /* nested /* comment */ ; drop table marts.dim_geo; -- */",
     "select 1 -- */; drop table marts.dim_geo; /*"],
)
def test_comments_cannot_smuggle_in_a_second_statement(sql):
    result = check(sql)
    assert result.ok and "drop" not in result.sql.lower() and statement_count(result.sql) == 1


def test_comments_do_not_hide_a_statement_or_a_function():
    assert any(r.startswith("forbidden_statement:") for r in reasons("/* harmless */ drop table marts.dim_geo"))
    assert reasons("select pg_sleep/**/(10)") == ("function_not_allowed:pg_sleep",)


def test_string_literal_tricks_stay_one_statement():
    result = check("select '; drop table marts.dim_geo' as s")
    assert result.ok and statement_count(result.sql) == 1
    assert not check("select '\\' ; drop table marts.dim_geo; --'").ok


@pytest.mark.parametrize(
    "sql",
    ["with d as (delete from marts.fct_primary_sales returning *) select * from d",
     "with u as (update marts.dim_geo set region = 'x' returning *) select count(*) from u",
     "with i as (insert into marts.dim_geo select * from marts.dim_geo returning *) select 1"],
)
def test_data_modifying_ctes_are_rejected(sql):
    assert any(reason.startswith("forbidden_statement:") for reason in reasons(sql))


def test_select_into_is_rejected():
    assert "select_into" in reasons("select * into marts.geo_copy from marts.dim_geo")


@pytest.mark.parametrize("clause", ["for update", "for share", "for no key update", "for key share", "for update nowait"])
def test_locking_clauses_are_rejected(clause):
    assert "locking_clause" in reasons(f"select * from marts.dim_geo {clause}")


@pytest.mark.parametrize(
    ("sql", "reason"),
    [("select * from pg_catalog.pg_authid", "catalog_access:pg_catalog"),
     ("select table_name from information_schema.tables", "catalog_access:information_schema"),
     ("select rolname from pg_roles", "catalog_access:pg_roles"),
     ("select * from marts.dim_geo where exists (select 1 from pg_stat_activity)", "catalog_access:pg_stat_activity")],
)
def test_catalog_access_is_rejected(sql, reason):
    assert reason in reasons(sql)


@pytest.mark.parametrize(
    "sql",
    ["with a as (select * from pg_roles), pg_roles as (select 1) select * from a",  # a later sibling isn't visible
     "select * from (with pg_roles as (select 1) select * from pg_roles) a, pg_roles b"],  # used out of scope
)
def test_a_cte_name_cannot_smuggle_in_a_catalog_table(sql):
    assert "catalog_access:pg_roles" in reasons(sql)


def test_a_cte_may_shadow_a_catalog_name_inside_its_scope():
    assert check("with pg_roles as (select 1 as x) select * from pg_roles").ok


@pytest.mark.parametrize(
    ("sql", "reason"),
    [("select * from raw.distributors", "schema_not_allowed:raw"),
     ("select * from staging.stg_distributors", "schema_not_allowed:staging"),
     ("select * from intermediate.int_channel_stock", "schema_not_allowed:intermediate"),
     ("select * from ops.agent_traces", "schema_not_allowed:ops"),
     ("select * from public.anything", "schema_not_allowed:public"),
     ('select * from "raw"."distributors"', "schema_not_allowed:raw"),
     ("select * from RAW.Distributors", "schema_not_allowed:raw"),
     ('select * from "MARTS".dim_geo', "schema_not_allowed:MARTS"),  # quoted is case-sensitive: not marts
     ('select * from "marts.dim_geo"', "table_not_allowed:marts.dim_geo"),  # one identifier containing a dot
     ("select * from channelpulse.marts.dim_geo", "schema_not_allowed:channelpulse.marts"),
     ("select * from marts.secret_table", "table_not_allowed:marts.secret_table"),
     ("select * from dim_geo g join raw.distributors d on true", "schema_not_allowed:raw")],
)
def test_other_schemas_and_unlisted_tables_are_rejected(sql, reason):
    assert reason in reasons(sql)


def test_unquoted_schema_names_fold_to_lower_case_like_postgres():
    assert "FROM marts.dim_geo" in check("select * from MARTS.Dim_Geo").sql


@pytest.mark.parametrize(
    "call",
    ["pg_sleep(10)", "pg_sleep_for('5 minutes')", "PG_SLEEP(1)", "pg_read_file('/etc/passwd')",
     "pg_read_binary_file('global/pg_control')", "pg_ls_dir('.')", "lo_import('/etc/passwd')", "lo_export(1, '/tmp/x')",
     "dblink('host=evil', 'select 1')", "set_config('app.region', 'ALL', true)", "current_setting('app.region')",
     "pg_terminate_backend(1)", "pg_cancel_backend(1)", "query_to_xml('select * from pg_authid', true, true, '')",
     "nextval('s')", "txid_current()"],
)
def test_dangerous_functions_are_rejected(call):
    assert any(reason.startswith("function_not_allowed:") for reason in reasons(f"select {call}"))


def test_admin_functions_are_rejected_in_from_and_lateral_too():
    assert "function_not_allowed:pg_ls_dir" in reasons("select * from pg_ls_dir('.') f")
    assert "function_not_allowed:pg_sleep" in reasons("select * from marts.dim_geo, lateral (select pg_sleep(1)) s")


def test_schema_qualified_function_calls_are_rejected():
    assert "qualified_function:pg_catalog" in reasons("select pg_catalog.pg_sleep(1)")


def test_version_is_allowed():
    assert check("select version()").ok


VALID = [
    "select region, sum(primary_value_inr) as value from marts.fct_primary_sales group by region order by value desc",
    (
        "with monthly as (select date_trunc('month', invoice_date) as month, sum(primary_value_inr) as value"
        " from fct_primary_sales group by 1)"
        " select month, value, value - lag(value) over (order by month) as change from monthly"
    ),
    (
        "select d.region, count(distinct d.distributor_id) from marts.dim_distributor d"
        " join marts.fct_secondary_sales s on s.distributor_id = d.distributor_id"
        " where s.sale_date >= date '2026-01-01' group by d.region"
    ),
    (
        "select distributor_id, rank() over (partition by region order by health_score desc)"
        " from marts.mart_distributor_health_weekly"
    ),
    "select sku from marts.dim_product union all select sku from marts.fct_primary_sales",
    (
        "select distinct on (batch_id) batch_id, claims from marts.mart_batch_claim_cohorts"
        " order by batch_id, months_in_service desc"
    ),
    "select percentile_cont(0.5) within group (order by effect_size) from marts.mart_anomaly_flags",
    "select count(*) filter (where status = 'open') as open_claims from marts.fct_warranty_claims",
    "select d::date from generate_series(date '2026-01-01', date '2026-03-01', interval '1 month') d",
    "with recursive n(i) as (select 1 union all select i + 1 from n where i < 3) select i from n",
    (
        "select coalesce(nullif(region, ''), 'unknown'), case when qty > 10 then 'big' else 'small' end"
        " from marts.fct_primary_sales"
    ),
]


@pytest.mark.parametrize("sql", VALID)
def test_valid_analytical_queries_pass(sql):
    result = check(sql)
    assert result.ok, result.reasons
    assert statement_count(result.sql) == 1


def test_unqualified_marts_are_pinned_to_the_marts_schema():
    assert check("select * from dim_geo").sql == "SELECT * FROM (SELECT * FROM marts.dim_geo) AS q LIMIT 500"


def test_the_row_cap_wraps_the_query_and_caps_a_larger_inner_limit():
    result = check("select * from marts.dim_geo limit 100000")
    assert result.sql == "SELECT * FROM (SELECT * FROM marts.dim_geo LIMIT 100000) AS q LIMIT 500"


def test_comments_are_dropped_from_the_sql_that_runs():
    assert check("select 1 -- a note */").sql == "SELECT * FROM (SELECT 1) AS q LIMIT 500"


@pytest.mark.parametrize(
    ("sql", "reason"),
    [("", "empty"), ("   ", "empty"), (";", "empty"), ("select (1", "parse_error"), ("selec 1", "parse_error"),
     ("select 1" + " " * 20_000, "too_long")],
)
def test_empty_malformed_and_oversized_input_is_rejected(sql, reason):
    assert reasons(sql) == (reason,)
