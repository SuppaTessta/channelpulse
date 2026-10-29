"""Repo-wide pytest hooks: @pytest.mark.db tests, in any test directory, skip when Postgres isn't reachable."""

import functools

import psycopg
import pytest

from app.db import agent_conninfo, ops_conninfo


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
