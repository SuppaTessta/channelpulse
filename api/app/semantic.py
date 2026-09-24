"""Semantic layer (PLAN §7, decisions D20): MetricFlow as a compile-only engine over the dbt semantic manifest.

The metrics are defined once, in warehouse/semantic_models/. `python api/app/admin.py semantic` parses them with dbt
into semantic_manifest.json beside this file, which ships in the API image; the API never runs dbt. MetricFlow
compiles each governed query to Postgres SQL, which runs on the read-only, region-filtered agent role.
"""

import copy
import datetime as dt
import difflib
import functools
import json
import math
import re
import threading
from pathlib import Path

from metricflow.engine.metricflow_engine import MetricFlowEngine, MetricFlowQueryRequest
from metricflow.engine.models import Entity
from metricflow.protocols.sql_client import SqlEngine
from metricflow.sql.render.postgres import PostgresSQLSqlPlanRenderer
from metricflow_semantic_interfaces.implementations.semantic_manifest import (
    PydanticSemanticManifest,
)
from metricflow_semantic_interfaces.type_enums import DimensionType
from metricflow_semantics.errors.error_classes import InvalidQueryException
from metricflow_semantics.model.semantic_manifest_lookup import SemanticManifestLookup

from app import config
from app.guardrails.sql_validator import validate

MANIFEST_PATH = Path(__file__).with_name("semantic_manifest.json")

# The twelve PLAN §7 metrics; the other manifest metrics are their building blocks.
GLOSSARY = frozenset({
    "primary_sales_value", "secondary_sales_value", "channel_days_of_stock", "claims_per_1000_units", "dso",
    "distributor_health_score", "stockout_rate", "overstock_rate", "scheme_concentration_ratio",
    "warranty_registration_rate", "collections_efficiency", "installer_claim_rate",
})
TIME_GRAINS = ("day", "week", "month", "quarter", "year")
_SQL_OPS = {"=": "=", "!=": "<>", ">": ">", ">=": ">=", "<": "<", "<=": "<=", "in": "IN", "not_in": "NOT IN"}
FILTER_OPS = tuple(_SQL_OPS)
MAX_VALUE_CHARS = 200
MAX_LIST_VALUES = 200

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# Filter values come from the model. Besides control characters and backslashes, braces are refused: MetricFlow
# renders every filter as a Jinja template, so "{{ ... }}" in a value would be evaluated and could emit a raw quote.
_UNSAFE_TEXT = re.compile(r"[\x00-\x1f\x7f\\{}]")
_PLAIN_COLUMN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TEMPLATE_REFERENCE = re.compile(r"\{\{\s*(?:Dimension|Entity|TimeDimension)\('([^']+)'[^}]*\}\}")

_CAVEATS = {
    "claims_per_1000_units": "Its period is the batch's manufacture date (metric_time is mfg_date), not the claim date.",
    "cohort_cumulative_claims_per_1000": (
        "Only meaningful grouped by batch_cohort_month__months_since_ship: it pools cumulative claims at each age."
    ),
    "dso": "Open invoices are aged to the as-of date, so a distributor who stops paying shows up at once.",
}
_EXAMPLE_GROUP_BY = {"cohort_cumulative_claims_per_1000": ["batch_cohort_month__months_since_ship"]}


class UnknownMetric(LookupError):
    """No governed metric has this name. The message is shown to the model and the user."""


class InvalidQuery(ValueError):
    """The metric exists but can't be compiled this way (unknown dimension, bad op or value, ...)."""


def list_metrics() -> list[dict]:
    """Every metric, sorted by name: name, label, description, type, formula, time_dimension, default_time_grain,
    dimensions (the valid group_by and filter names) and glossary. Deterministic: the cached system prompt embeds it."""
    return copy.deepcopy(list(_glossary().values()))


def explain_metric(name: str) -> dict:
    """One metric's definition, formula (the manifest's type params), a compiled example query and its caveats."""
    entry = _entry(name)
    metric = _metrics()[name]
    example = _EXAMPLE_GROUP_BY.get(name) or [
        "metric_time__month" if "metric_time__month" in entry["dimensions"] else f"metric_time__{entry['default_time_grain']}"
    ]
    return {
        "name": name,
        "label": entry["label"],
        "definition": entry["description"],
        "type": entry["type"],
        "glossary": entry["glossary"],
        "formula": _formula_details(metric),
        "time_dimension": entry["time_dimension"],
        "default_time_grain": entry["default_time_grain"],
        "example_group_by": example,
        "sql": compile_query(name, [], example, None, "ALL")["sql"],
        "caveats": _caveats(metric, entry),
    }


def compile_query(
    metric_name: str,
    filters: list[dict],
    group_by: list[str],
    date_range: dict | None,
    region_claim: str,
) -> dict:
    """Compile a governed metric query to {"sql": str, "params": {}}; filter values are validated and inlined.

    filters     [{"dimension": a name from the metric's dimensions, "op": one of FILTER_OPS,
                  "value": text | number | boolean (ISO date for metric_time), or a list for in / not_in}]
    group_by    names from the metric's dimensions
    date_range  {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}, both inclusive, or None for all history
    Raises UnknownMetric or InvalidQuery with a message that says what to change.
    """
    # region_claim adds nothing to the SQL: Postgres RLS on the distributor-level marts filters rows by the claim
    # (warehouse/macros/apply_region_rls.sql), and every compiled query runs as the RLS-bound agent role.
    entry = _entry(metric_name)
    allowed = frozenset(entry["dimensions"])
    group_by = list(dict.fromkeys(group_by))
    if unknown := [name for name in group_by if name not in allowed]:
        raise InvalidQuery(
            f"{metric_name} can't be grouped by {', '.join(unknown)}; use names from: {', '.join(entry['dimensions'])}."
        )
    start, end = _date_range(date_range)
    request = MetricFlowQueryRequest.create(
        metric_names=[metric_name],
        group_by_names=group_by,
        where_constraints=[_where(condition, allowed, metric_name) for condition in filters],
        time_constraint_start=start,
        time_constraint_end=end,
        # Time series come back in time order, other breakdowns largest first, so a top N fits in what the model sees.
        order_by_names=group_by if any(n.startswith("metric_time__") for n in group_by) else [f"-{metric_name}", *group_by],
        limit=config.ROW_CAP,
    )
    try:
        with _engine_lock:
            sql = _engine().explain(request).sql_statement.sql
    except InvalidQueryException as e:
        raise InvalidQuery(" ".join(str(e).split())[:500]) from e
    # MetricFlow annotates every plan step with a full-line comment. Values can't contain newlines, so each line
    # starting with -- is one of those.
    sql = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    # The inlined values came from the model, so the compiled SQL must also pass the gate ad-hoc SQL goes through.
    check = validate(sql, config.MART_TABLES, config.ROW_CAP)
    if not check.ok:
        raise InvalidQuery(f"The compiled query failed the SQL safety check: {', '.join(check.reasons)}.")
    return {"sql": sql, "params": {}}


def portable(manifest: dict) -> dict:
    """Make a dbt semantic manifest database-agnostic and stable, in place.

    dbt qualifies each relation with the database it parsed against ("channelpulse" locally, "postgres" on
    Supabase); dropping it leaves "schema"."alias", which works on any database. Top-level lists are sorted by name
    so the shipped file changes only when a definition does.
    """
    relations = [model["node_relation"] for model in manifest["semantic_models"]]
    relations += [spine["node_relation"] for spine in manifest["project_configuration"]["time_spines"]]
    for relation in relations:
        relation["database"] = None
        relation["relation_name"] = f'"{relation["schema_name"]}"."{relation["alias"]}"'
    for key in ("semantic_models", "metrics", "saved_queries"):
        manifest[key] = sorted(manifest[key], key=lambda item: item["name"])
    return manifest


class _CompileOnlyClient:
    """MetricFlow needs only the dialect to render SQL; queries run elsewhere, on the read-only agent role."""

    sql_engine_type = SqlEngine.POSTGRES
    sql_plan_renderer = PostgresSQLSqlPlanRenderer()

    def render_bind_parameter_key(self, bind_parameter_key: str) -> str:
        return f"%({bind_parameter_key})s"


# ponytail: one MetricFlow call at a time (a compile takes ~20 ms); its thread-safety isn't documented.
_engine_lock = threading.Lock()


@functools.cache
def _manifest() -> dict:
    return portable(json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))


@functools.cache
def _engine() -> MetricFlowEngine:
    lookup = SemanticManifestLookup(PydanticSemanticManifest.parse_obj(_manifest()))
    return MetricFlowEngine(lookup, _CompileOnlyClient())


@functools.cache
def _metrics() -> dict[str, dict]:
    return {metric["name"]: metric for metric in _manifest()["metrics"]}


@functools.cache
def _glossary() -> dict[str, dict]:
    glossary = {}
    for name, metric in sorted(_metrics().items()):
        dimensions, grain = _group_bys(metric)
        glossary[name] = {
            "name": name,
            "label": metric["label"],
            "description": metric["description"],
            "type": metric["type"],
            "formula": _formula(metric),
            "time_dimension": ", ".join(sorted({_aggregation(leaf)["agg_time_dimension"] for leaf in _leaves(metric)})),
            "default_time_grain": grain,
            "dimensions": dimensions,
            "glossary": name in GLOSSARY,
        }
    return glossary


def _entry(name: str) -> dict:
    glossary = _glossary()
    if name in glossary:
        return glossary[name]
    close = difflib.get_close_matches(name, glossary, n=3)
    raise UnknownMetric(f"No governed metric is called {name[:80]!r}." + (f" Did you mean {', '.join(close)}?" if close else ""))


def _group_bys(metric: dict) -> tuple[list[str], str]:
    """The group-by names worth offering for a metric, and its finest metric_time grain.

    MetricFlow lists every join path. This keeps the shortest path to each dimension (distributor__region, not
    invoice__distributor__region), offers metric_time at every standard grain from the metric's own up, and leaves out
    other time dimensions. Entities come from the metric's own semantic models: a bare entity name only works there.
    """
    with _engine_lock:
        items = _engine().list_group_bys([metric["name"]])
    shortest: dict[tuple, str] = {}
    grain = TIME_GRAINS[0]
    for item in items:
        if isinstance(item, Entity):
            continue
        if item.type is DimensionType.TIME:
            if item.dunder_name.startswith("metric_time__"):
                grain = item.dunder_name.removeprefix("metric_time__")
            continue
        key = (item.semantic_model_reference, item.name)
        best = shortest.get(key)
        if best is None or (item.dunder_name.count("__"), item.dunder_name) < (best.count("__"), best):
            shortest[key] = item.dunder_name
    grains = TIME_GRAINS[TIME_GRAINS.index(grain):]
    return sorted({*_entities(metric), *shortest.values(), *(f"metric_time__{g}" for g in grains)}), grain


def _entities(metric: dict) -> set[str]:
    """Entities on every semantic model the metric aggregates, minus compound keys such as inventory_day."""
    models = {model["name"]: model for model in _manifest()["semantic_models"]}
    per_model = [
        {e["name"] for e in models[_aggregation(leaf)["semantic_model"]]["entities"] if _PLAIN_COLUMN.fullmatch(e["expr"] or e["name"])}
        for leaf in _leaves(metric)
    ]
    return set.intersection(*per_model) if per_model else set()


def _where(condition: dict, allowed: frozenset[str], metric_name: str) -> str:
    """One filter as a MetricFlow where constraint, e.g. {{ Dimension('distributor__region') }} = 'Assam'."""
    name, op, value = condition["dimension"], condition["op"], condition["value"]
    if name not in allowed:
        raise InvalidQuery(f"{metric_name} has no dimension {name[:80]!r} to filter on.")
    if op not in _SQL_OPS:
        raise InvalidQuery(f"Unsupported filter op {op[:20]!r}; use one of {', '.join(FILTER_OPS)}.")
    is_time = name.startswith("metric_time__")
    if op in ("in", "not_in"):
        if not isinstance(value, list) or not 0 < len(value) <= MAX_LIST_VALUES:
            raise InvalidQuery(f"{op} needs a list of 1 to {MAX_LIST_VALUES} values.")
        rendered = "(" + ", ".join(_literal(item, is_time) for item in value) + ")"
    elif isinstance(value, list):
        raise InvalidQuery(f"{op} takes a single value, not a list.")
    else:
        rendered = _literal(value, is_time)
    if is_time:
        reference = f"{{{{ TimeDimension('metric_time', '{name.removeprefix('metric_time__')}') }}}}"
    elif "__" in name:
        reference = f"{{{{ Dimension('{name}') }}}}"
    else:
        reference = f"{{{{ Entity('{name}') }}}}"
    return f"{reference} {_SQL_OPS[op]} {rendered}"


def _literal(value, is_time: bool) -> str:
    """A filter value as a SQL literal. The value comes from the model, so only plain, checked types get through."""
    if is_time:
        return f"'{_iso_date(value, 'Time filters').isoformat()}'"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and math.isfinite(value):
        return repr(value)
    if isinstance(value, str) and len(value) <= MAX_VALUE_CHARS and not _UNSAFE_TEXT.search(value):
        return "'" + value.replace("'", "''") + "'"
    raise InvalidQuery(
        f"Unsupported filter value {str(value)[:60]!r}: use text (no control characters, braces or backslashes, at most "
        f"{MAX_VALUE_CHARS} characters), a number or a boolean."
    )


def _iso_date(value, what: str) -> dt.date:
    if isinstance(value, str) and _ISO_DATE.fullmatch(value):
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            pass
    raise InvalidQuery(f"{what} take ISO dates (YYYY-MM-DD), not {str(value)[:40]!r}.")


def _date_range(date_range: dict | None) -> tuple[dt.datetime | None, dt.datetime | None]:
    if date_range is None:
        return None, None
    start, end = (_iso_date(date_range[key], "date_range start and end") for key in ("start", "end"))
    if start > end:
        raise InvalidQuery("date_range starts after it ends.")
    return dt.datetime.combine(start, dt.time()), dt.datetime.combine(end, dt.time())


def _aggregation(metric: dict) -> dict | None:
    return metric["type_params"]["metric_aggregation_params"]


def _descendants(metric: dict) -> list[dict]:
    """Every metric this one is computed from, depth first, without repeats."""
    params = metric["type_params"]
    refs = [ref for ref in (params["numerator"], params["denominator"]) if ref] + params["metrics"]
    found = {}
    for ref in refs:
        child = _metrics()[ref["name"]]
        found[child["name"]] = child
        found.update((grandchild["name"], grandchild) for grandchild in _descendants(child))
    return list(found.values())


def _leaves(metric: dict) -> list[dict]:
    """The simple metrics (the ones that aggregate a column) underneath a metric."""
    return [m for m in (metric, *_descendants(metric)) if _aggregation(m)]


def _formula(metric: dict) -> str:
    """How a metric is computed, in one line: sum(primary_value_inr), numerator / denominator, or an expression."""
    params = metric["type_params"]
    if aggregation := _aggregation(metric):
        text = f"{aggregation['agg']}({params['expr']})"
        if window := aggregation["non_additive_dimension"]:
            text += f" on the {'last' if window['window_choice'] == 'max' else 'first'} {window['name']} of each period"
    elif metric["type"] == "ratio":
        text = f"{params['numerator']['name']} / {params['denominator']['name']}"
    else:
        aliases = [f"{ref['alias']} = {ref['name']}" for ref in params["metrics"] if ref["alias"]]
        text = params["expr"] + (f" with {', '.join(aliases)}" if aliases else "")
    if metric["filter"]:
        conditions = [_TEMPLATE_REFERENCE.sub(r"\1", f["where_sql_template"]) for f in metric["filter"]["where_filters"]]
        text += f", over rows where {' and '.join(conditions)}"
    return text


def _formula_details(metric: dict) -> dict:
    params = metric["type_params"]
    aggregation = _aggregation(metric) or {}
    details = {
        "summary": _formula(metric),
        "semantic_model": aggregation.get("semantic_model"),
        "agg": aggregation.get("agg"),
        "expr": params["expr"],
        "numerator": (params["numerator"] or {}).get("name"),
        "denominator": (params["denominator"] or {}).get("name"),
        "input_metrics": [{"name": ref["name"], "alias": ref["alias"]} for ref in params["metrics"]],
        "filters": [f["where_sql_template"] for f in (metric["filter"] or {}).get("where_filters", [])],
        "non_additive_dimension": aggregation.get("non_additive_dimension"),
        "inputs": {child["name"]: _formula(child) for child in _descendants(metric)},
    }
    return {key: value for key, value in details.items() if value}


def _caveats(metric: dict, entry: dict) -> list[str]:
    caveats = []
    if any(_aggregation(leaf)["non_additive_dimension"] for leaf in _leaves(metric)):
        caveats.append("Stock is a snapshot: over a period it is read on the period's last day, not added up across days.")
    if settled := [name for name in entry["dimensions"] if name.endswith("__is_settled")]:
        caveats.append(
            f"The newest days are provisional while late sell-out reports arrive; filter {settled[0]} = true for "
            "settled figures."
        )
    if note := _CAVEATS.get(metric["name"]):
        caveats.append(note)
    return caveats
