"""Load raw tables into Postgres: one transaction (drop, create, schema.sql, COPY, run row), then ANALYZE."""

import os
import re
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

SCHEMA_SQL = Path(__file__).with_name("schema.sql")


def conninfo() -> str:
    """DATABASE_URL wins; otherwise the same POSTGRES_* vars and defaults as warehouse/profiles.yml (as api/app/main.py)."""
    if url := os.environ.get("DATABASE_URL"):
        return url
    env = os.environ.get
    return make_conninfo(host=env("POSTGRES_HOST", "localhost"), port=env("POSTGRES_PORT", "5432"),
                         user=env("POSTGRES_USER", "channelpulse"), password=env("POSTGRES_PASSWORD", "channelpulse"),
                         dbname=env("POSTGRES_DB", "channelpulse"))


def tsv(columns: dict) -> str:
    """COPY text format; generated text never contains tabs, newlines or backslashes, so no escaping is needed."""
    cols = [[r"\N" if v is None else str(v) for v in col] for col in columns.values()]
    return "".join("\t".join(row) + "\n" for row in zip(*cols))


def load(tables: dict, schema: str, as_of, anchor_date, seed: int) -> int:
    """Rebuild <schema> from scratch and return its total size in bytes. Safe to re-run."""
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", schema):
        raise ValueError(f"invalid schema name: {schema!r}")
    ddl = re.sub(r"\braw\.", f"{schema}.", SCHEMA_SQL.read_text(encoding="utf-8"))
    ident = sql.Identifier(schema)
    with psycopg.connect(conninfo()) as conn:
        with conn.transaction():
            conn.execute(sql.SQL("drop schema if exists {} cascade").format(ident))
            conn.execute(sql.SQL("create schema {}").format(ident))
            conn.execute(ddl)
            with conn.cursor() as cur:
                for name, columns in tables.items():
                    query = sql.SQL("copy {}.{} ({}) from stdin").format(
                        ident, sql.Identifier(name), sql.SQL(", ").join(map(sql.Identifier, columns)))
                    with cur.copy(query) as copy:
                        copy.write(tsv(columns))
                cur.execute(sql.SQL("insert into {}.generation_run (as_of_date, anchor_date, seed) values (%s, %s, %s)").format(ident),
                            (as_of, anchor_date, seed))
        conn.autocommit = True
        for name in [*tables, "generation_run"]:
            conn.execute(sql.SQL("analyze {}.{}").format(ident, sql.Identifier(name)))
        return conn.execute("select coalesce(sum(pg_total_relation_size(c.oid)), 0) from pg_class c "
                            "join pg_namespace n on n.oid = c.relnamespace where n.nspname = %s and c.relkind = 'r'",
                            (schema,)).fetchone()[0]
