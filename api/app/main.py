import os

import psycopg
from fastapi import FastAPI
from psycopg.conninfo import make_conninfo

app = FastAPI(title="ChannelPulse API")


def db_conninfo() -> str:
    """DATABASE_URL (deploy) wins; otherwise the same POSTGRES_* vars/defaults as dbt's profile."""
    if url := os.environ.get("DATABASE_URL"):
        return url
    env = os.environ.get
    return make_conninfo(
        host=env("POSTGRES_HOST", "localhost"),
        port=env("POSTGRES_PORT", "5432"),
        user=env("POSTGRES_USER", "channelpulse"),
        password=env("POSTGRES_PASSWORD", "channelpulse"),
        dbname=env("POSTGRES_DB", "channelpulse"),
    )


@app.get("/health")
def health() -> dict:
    try:
        with psycopg.connect(db_conninfo(), connect_timeout=2) as conn:
            conn.execute("select 1")
        db = "ok"
    except psycopg.Error:
        db = "unreachable"
    return {"status": "ok", "db": db}
