"""Admin tasks.

From the repo root:  .venv/Scripts/python.exe api/app/admin.py roles|semantic
From api/:           ../.venv/Scripts/python.exe -m app.admin roles|semantic

roles     apply api/sql/roles.sql as the database admin user
semantic  dbt-parse warehouse/ (no database needed) and ship the semantic manifest with the API
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]
WAREHOUSE_DIR = API_DIR.parent / "warehouse"


def apply_roles() -> str:
    """Create or refresh the agent and ops roles, their grants and ops.agent_traces (api/sql/roles.sql)."""
    import psycopg  # here, not at the top: `semantic` needs no database driver
    from psycopg import sql

    from app.db import ROLE_PASSWORD_VARS, db_conninfo, role_password

    with psycopg.connect(db_conninfo(), autocommit=True, connect_timeout=10) as conn:
        conn.execute((API_DIR / "sql" / "roles.sql").read_text(encoding="utf-8"))
        for role in ROLE_PASSWORD_VARS:
            conn.execute(sql.SQL("alter role {} with password {}").format(sql.Identifier(role),
                                                                         sql.Literal(role_password(role))))
    return "Applied api/sql/roles.sql: channelpulse_agent (marts, read-only) and channelpulse_ops (ops.agent_traces)."


class DbtUnavailable(RuntimeError):
    """dbt isn't installed here, or can't import its Postgres adapter: an environment problem, not a definition one."""


def parse_semantic_manifest(workdir: Path) -> dict:
    """`dbt parse` the warehouse into workdir and return its semantic manifest, made portable. Needs dbt, no database."""
    from app.semantic import portable

    dbt = shutil.which("dbt", path=str(Path(sys.executable).parent))  # make setup installs it in .venv
    if dbt is None:
        raise DbtUnavailable(f"dbt isn't installed next to {sys.executable}; run `make setup`.")
    run = subprocess.run(
        [dbt, "parse", "--quiet", "--project-dir", str(WAREHOUSE_DIR), "--profiles-dir", str(WAREHOUSE_DIR),
         "--target-path", str(workdir / "target"), "--log-path", str(workdir / "logs")],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if run.returncode:
        output = (run.stdout + run.stderr).strip()
        error = DbtUnavailable if "ImportError" in output else RuntimeError
        raise error(f"dbt parse failed: {output.splitlines()[-1] if output else f'exit {run.returncode}'}")
    return portable(json.loads((workdir / "target" / "semantic_manifest.json").read_text(encoding="utf-8")))


def export_semantic_manifest() -> str:
    """Write api/app/semantic_manifest.json, which the API image ships instead of running dbt."""
    from app.semantic import MANIFEST_PATH

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as workdir:
        manifest = parse_semantic_manifest(Path(workdir))
    text = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    MANIFEST_PATH.write_text(text, encoding="utf-8", newline="\n")  # the same bytes on every OS
    return (
        f"Wrote {MANIFEST_PATH.relative_to(API_DIR.parent).as_posix()}: "
        f"{len(manifest['semantic_models'])} semantic models, {len(manifest['metrics'])} metrics."
    )


COMMANDS = {"roles": apply_roles, "semantic": export_semantic_manifest}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        sys.exit(f"usage: admin.py {'|'.join(COMMANDS)}")
    if not __package__:  # run as a script: put api/ on the path, like uvicorn's --app-dir api
        sys.path.insert(0, str(API_DIR))
    try:
        print(COMMANDS[sys.argv[1]]())
    except RuntimeError as e:
        sys.exit(str(e))
