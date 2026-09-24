"""Gatekeeper for run_readonly_sql, the agent's ad-hoc SQL fallback (PLAN §8).

The database role is the hard boundary; this is defence in depth and deliberately strict. A query passes only if it
is one SELECT (WITH ... SELECT and UNION/INTERSECT/EXCEPT of SELECTs included) that reads allowlisted marts and
calls no system functions. The SQL that runs is regenerated from the checked syntax tree, so what executes is what
was checked: comments are dropped, unqualified marts are pinned to schema `marts`, and the query is wrapped in a row
cap that also caps any larger inner LIMIT.
"""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers

MAX_SQL_CHARS = 20_000

# Statements that write, change schema, privileges, settings or transaction state. The walk covers the whole tree,
# so a data-modifying CTE (WITH d AS (DELETE ... RETURNING *) SELECT ...) is caught too.
FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Drop, exp.Create, exp.Alter, exp.TruncateTable,
    exp.Command, exp.Copy, exp.Grant, exp.Revoke, exp.Set, exp.Transaction, exp.Commit, exp.Rollback,
)

# pg_* covers pg_sleep*, pg_read_file, pg_read_binary_file, pg_ls_dir, pg_terminate_backend, pg_cancel_backend,
# advisory locks and the rest of the admin surface. *_to_xml functions (query_to_xml, table_to_xml, ...) run SQL
# passed in as a string, which would bypass every check here.
BLOCKED_FUNCTION_PREFIXES = ("pg_", "lo_", "dblink", "txid_")
BLOCKED_FUNCTIONS = frozenset({"set_config", "current_setting", "nextval", "setval", "currval", "lastval"})
SQL_RUNNING_FUNCTION_MARKER = "_to_xml"


@dataclass(frozen=True)
class Validation:
    ok: bool
    sql: str | None = None  # normalised, row-capped SQL; None when rejected
    reasons: tuple[str, ...] = ()


def validate(sql: str, allowed_tables: frozenset[str], row_cap: int) -> Validation:
    """Check one ad-hoc query; on success return the exact SQL to execute."""
    if not sql.strip():
        return Validation(False, reasons=("empty",))
    if len(sql) > MAX_SQL_CHARS:
        return Validation(False, reasons=("too_long",))
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
        if len(statements) != 1:
            return Validation(False, reasons=("multiple_statements",) if statements else ("empty",))
        tree = normalize_identifiers(statements[0], dialect="postgres")
        reasons = _check(tree, allowed_tables)
    except SqlglotError:
        return Validation(False, reasons=("parse_error",))
    except RecursionError:
        return Validation(False, reasons=("too_complex",))
    if reasons:
        return Validation(False, reasons=tuple(dict.fromkeys(reasons)))
    capped = exp.select("*").from_(tree.subquery("q")).limit(row_cap)
    return Validation(True, sql=capped.sql(dialect="postgres", comments=False))


def _check(tree: exp.Expression, allowed_tables: frozenset[str]) -> list[str]:
    reasons = []
    if not isinstance(tree, exp.Select | exp.SetOperation):
        reasons.append(f"not_select:{type(tree).__name__}")
    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            reasons.append(f"forbidden_statement:{type(node).__name__}")
        elif isinstance(node, exp.Into):
            reasons.append("select_into")
        elif isinstance(node, exp.Lock):
            reasons.append("locking_clause")
        elif isinstance(node, exp.Dot) and isinstance(node.expression, exp.Func):
            reasons.append(f"qualified_function:{node.this.sql()}")
        elif isinstance(node, exp.Func) and _is_blocked(name := _function_name(node)):
            reasons.append(f"function_not_allowed:{name}")
    _check_tables(tree, frozenset(), allowed_tables, reasons)
    return reasons


def _function_name(node: exp.Func) -> str:
    # Unknown functions (Anonymous) keep their written name; known ones are sqlglot's modelled standard functions.
    return (node.this if isinstance(node.this, str) else node.sql_name()).lower()


def _is_blocked(name: str) -> bool:
    return (
        name.startswith(BLOCKED_FUNCTION_PREFIXES)
        or name in BLOCKED_FUNCTIONS
        or SQL_RUNNING_FUNCTION_MARKER in name
    )


def _check_tables(node: exp.Expression, ctes: frozenset[str], allowed: frozenset[str], reasons: list[str]) -> None:
    """Resolve every table reference the way Postgres scopes CTE names, so a CTE can't smuggle in a catalog table."""
    with_ = node.args.get("with_")
    if isinstance(with_, exp.With):
        names = [cte.alias_or_name for cte in with_.expressions]
        for i, cte in enumerate(with_.expressions):
            # A non-recursive CTE sees only the CTEs defined before it; an unresolved name falls through to the
            # search_path, where pg_catalog comes first.
            visible = names if with_.args.get("recursive") else names[:i]
            _check_tables(cte.this, ctes | set(visible), allowed, reasons)
        ctes |= set(names)
    for child in node.iter_expressions():
        if child is with_:
            continue
        if isinstance(child, exp.Table):
            _check_table(child, ctes, allowed, reasons)
        _check_tables(child, ctes, allowed, reasons)


def _check_table(table: exp.Table, ctes: frozenset[str], allowed: frozenset[str], reasons: list[str]) -> None:
    if not isinstance(table.this, exp.Identifier):
        return  # a table function such as generate_series(); the function check covers it
    schema = ".".join(part for part in (table.catalog, table.db) if part)
    name = table.name
    if not schema:
        if name in ctes:
            return
        if name in allowed:
            table.set("db", exp.to_identifier("marts"))  # don't rely on search_path, where pg_catalog comes first
            return
        reasons.append(f"catalog_access:{name}" if _is_catalog(name) else f"table_not_allowed:{name}")
    elif schema == "marts":
        if name not in allowed:
            reasons.append(f"table_not_allowed:marts.{name}")
    else:
        reasons.append(f"catalog_access:{schema}" if _is_catalog(schema) else f"schema_not_allowed:{schema}")


def _is_catalog(name: str) -> bool:
    return name == "information_schema" or name.startswith("pg_")
