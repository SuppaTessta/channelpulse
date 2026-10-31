"""The database roles from api/sql/roles.sql, checked against the local Postgres."""

import uuid

import psycopg
import pytest

from app.admin import apply_roles
from app.db import agent_conninfo, db_conninfo, ops_conninfo
from app.guardrails import readonly_db

pytestmark = pytest.mark.db

# The expression warehouse/macros/apply_region_rls.sql puts on every distributor-level mart.
REGION_POLICY = "coalesce(nullif(current_setting('app.region', true), ''), 'ALL') in ('ALL', region)"


@pytest.fixture
def probe_mart():
    """A throwaway marts table created by the admin user after the roles script ran, as dbt would, with RLS."""
    name = f"cp_probe_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(db_conninfo(), autocommit=True, connect_timeout=5) as admin:
        admin.execute(f"create table marts.{name} (region text, units int)")
        admin.execute(f"insert into marts.{name} values ('Assam', 1), ('Odisha', 2)")
        admin.execute(f"alter table marts.{name} enable row level security")
        admin.execute(f"create policy region_claim on marts.{name} for select using ({REGION_POLICY})")
        try:
            yield name
        finally:
            admin.execute(f"drop table marts.{name}")


def test_the_roles_script_is_idempotent():
    apply_roles()
    apply_roles()


def test_the_agent_can_read_marts_tables_created_later(probe_mart):
    assert readonly_db.run(f"select units from marts.{probe_mart} order by units", None, "ALL").rows == [[1], [2]]


def test_the_region_claim_filters_distributor_level_rows(probe_mart):
    assert readonly_db.run(f"select region from marts.{probe_mart}", None, "Assam").rows == [["Assam"]]


def test_the_ops_role_cannot_read_marts(probe_mart):
    with psycopg.connect(ops_conninfo()) as ops, pytest.raises(psycopg.errors.InsufficientPrivilege):
        ops.execute(f"select * from marts.{probe_mart}")


@pytest.mark.parametrize("schema", ["raw", "staging", "intermediate", "ops", "public"])
def test_the_agent_has_no_usage_outside_marts(schema):
    with psycopg.connect(db_conninfo()) as admin:
        if not admin.execute("select 1 from pg_namespace where nspname = %s", (schema,)).fetchone():
            pytest.skip(f"schema {schema} doesn't exist yet")
        (usage,) = admin.execute("select has_schema_privilege('channelpulse_agent', %s, 'USAGE')", (schema,)).fetchone()
    assert usage is False


@pytest.mark.parametrize("statement", ["create temp table cp_probe (x int)", "create table marts.cp_probe (x int)"])
def test_the_agent_cannot_write_even_in_a_read_write_transaction(statement):
    with psycopg.connect(agent_conninfo()) as conn:
        conn.execute("set transaction read write")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(statement)


def test_the_agent_role_defaults_to_read_only_marts_with_a_timeout():
    with psycopg.connect(agent_conninfo()) as conn:
        settings = {name: conn.execute(f"show {name}").fetchone()[0]
                    for name in ("default_transaction_read_only", "statement_timeout", "search_path")}
    assert settings == {"default_transaction_read_only": "on", "statement_timeout": "5s", "search_path": "marts"}


def test_the_ops_role_can_append_read_and_update_traces_but_never_delete_them():
    """Update, so a free question's reserved row can take its real values (decisions D55)."""
    with psycopg.connect(ops_conninfo()) as ops:
        ops.execute("select count(*) from ops.agent_traces")
        ops.execute("update ops.agent_traces set label = label where false")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            ops.execute("delete from ops.agent_traces")


def test_a_trace_is_paid_for_by_the_owner_or_a_visitor_and_no_one_else():
    with psycopg.connect(ops_conninfo()) as ops, pytest.raises(psycopg.errors.CheckViolation):
        ops.execute("insert into ops.agent_traces (trace_id, question, region_claim, model, label, paid_by)"
                    " values (%s, 'q', 'ALL', 'm', 'error', 'a friend')", (uuid.uuid4(),))
