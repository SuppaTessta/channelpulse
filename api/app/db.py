"""Connection strings for the three database identities the API uses (api/sql/roles.sql creates the last two)."""

import os

from psycopg.conninfo import make_conninfo

ROLE_PASSWORD_VARS = {"channelpulse_agent": "AGENT_DB_PASSWORD", "channelpulse_ops": "OPS_DB_PASSWORD"}


def role_password(role: str) -> str:
    return os.environ.get(ROLE_PASSWORD_VARS[role], role)  # local-dev default: the role name


def _conninfo(url_var: str, user: str, password: str) -> str:
    if url := os.environ.get(url_var):
        return url
    env = os.environ.get
    return make_conninfo(
        # Not "localhost": compose publishes Postgres on 127.0.0.1 only, and a ::1 attempt can stall on Windows.
        host=env("POSTGRES_HOST", "127.0.0.1"),
        port=env("POSTGRES_PORT", "5432"),
        user=user,
        password=password,
        dbname=env("POSTGRES_DB", "channelpulse"),
    )


def db_conninfo() -> str:
    """Admin. DATABASE_URL (deploy) wins; otherwise the same POSTGRES_* vars/defaults as dbt's profile."""
    env = os.environ.get
    return _conninfo("DATABASE_URL", env("POSTGRES_USER", "channelpulse"), env("POSTGRES_PASSWORD", "channelpulse"))


def agent_conninfo() -> str:
    """channelpulse_agent: read-only, SELECT on marts only. Every agent and dashboard query runs as this role."""
    return _conninfo("AGENT_DATABASE_URL", "channelpulse_agent", role_password("channelpulse_agent"))


def ops_conninfo() -> str:
    """channelpulse_ops: INSERT/SELECT on ops.agent_traces only."""
    return _conninfo("OPS_DATABASE_URL", "channelpulse_ops", role_password("channelpulse_ops"))
