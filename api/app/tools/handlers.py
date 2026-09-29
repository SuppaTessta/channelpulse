"""Tool implementations, shared by the agent loop and the dashboard endpoints so both take the same governed path."""

import json

from app import config, semantic
from app.guardrails import readonly_db
from app.guardrails.sql_validator import validate

GOVERNED = "governed_metric"
AD_HOC = "ad_hoc_sql_verify"

# Latest snapshot per (detector, entity) on or before as_of, kept if the entity was flagged by then. A lot_scan
# entity is a (resin lot, failure mode) pair and a stuffing entity a (distributor, scheme category) pair; the
# other keys are null for the other detectors. The table has its own
# region RLS policy, like the distributor-level marts.
ANOMALIES_SQL = """\
with params as (
    select coalesce(%(as_of)s::date, (select max(snapshot_date) from marts.mart_anomaly_flags)) as as_of
),
latest as (
    select distinct on (f.detector, f.entity_type, f.entity_id, f.failure_mode, f.details ->> 'category') f.*
    from marts.mart_anomaly_flags f, params p
    where f.snapshot_date <= p.as_of
    order by f.detector, f.entity_type, f.entity_id, f.failure_mode, f.details ->> 'category', f.snapshot_date desc
)
select p.as_of, l.detector, l.entity_type, l.entity_id, l.failure_mode, l.region, l.snapshot_date,
       l.first_flag_date, l.effect_size, l.p_value, l.details
from latest l, params p
where l.first_flag_date <= p.as_of
  and (%(detector)s::text is null or l.detector = %(detector)s)
  and (%(failure_mode)s::text is null or l.failure_mode = %(failure_mode)s)
-- Strongest first within each detector, interleaved across detectors (D34): the model reads only the first rows, so
-- one detector's long list must not push the others out of view.
order by row_number() over (partition by l.detector order by l.effect_size desc nulls last, l.entity_id, l.failure_mode),
         l.detector"""


class ToolError(Exception):
    """A failure the model sees as a tool result with is_error: true, so it can change course."""


def list_metrics(_input: dict, _region: str) -> dict:
    return {"metrics": semantic.list_metrics()}


def explain_metric(tool_input: dict, _region: str) -> dict:
    return {"metric": semantic.explain_metric(tool_input["metric_name"])}


def query_metric(tool_input: dict, region: str) -> dict:
    compiled = semantic.compile_query(
        tool_input["metric_name"], tool_input["filters"], tool_input["group_by"], tool_input["date_range"], region
    )
    return _result(readonly_db.run(compiled["sql"], compiled.get("params"), region), GOVERNED)


def run_readonly_sql(tool_input: dict, region: str) -> dict:
    check = validate(tool_input["sql"], config.MART_TABLES, config.ROW_CAP)
    if not check.ok:
        raise ToolError("Rejected by the SQL validator before execution: " + ", ".join(check.reasons))
    return _result(readonly_db.run(check.sql, None, region), AD_HOC)


def get_anomalies(tool_input: dict, region: str) -> dict:
    params = {"as_of": tool_input["as_of_date"], "detector": tool_input.get("detector"),
              "failure_mode": tool_input.get("failure_mode")}
    return _result(readonly_db.run(ANOMALIES_SQL, params, region), GOVERNED)


META_SQL = "select min(date_day) as data_start, max(date_day) as as_of from marts.dim_date"


def data_window(region: str) -> dict:
    """First and last day with data (the as-of date), read from the time spine."""
    result = readonly_db.run(META_SQL, {}, region)
    data_start, as_of = result.rows[0]
    return {"data_start": data_start, "as_of": as_of}


HANDLERS = {
    "explain_metric": explain_metric,
    "get_anomalies": get_anomalies,
    "list_metrics": list_metrics,
    "query_metric": query_metric,
    "run_readonly_sql": run_readonly_sql,
}


def run_tool(name: str, tool_input: dict, region: str) -> dict:
    """Run a tool the model asked for, turning expected failures into ToolError."""
    if name not in HANDLERS:
        raise ToolError(f"Unknown tool {name!r}.")
    try:
        return HANDLERS[name](tool_input, region)
    except (semantic.UnknownMetric, semantic.InvalidQuery, readonly_db.QueryError) as e:
        raise ToolError(str(e)) from e


def for_model(tool_use_id: str, result: dict) -> str:
    """Compact JSON for the model: the first MODEL_ROWS rows plus row_count and the SQL. The API keeps every row."""
    payload = {"tool_use_id": tool_use_id, **{k: v for k, v in result.items() if k != "data"}}
    if data := result.get("data"):
        payload["columns"] = data["columns"]
        payload["rows"] = data["rows"][: config.MODEL_ROWS]
        hidden = len(data["rows"]) - config.MODEL_ROWS
        if hidden > 0:
            payload["rows_not_shown"] = hidden
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False, default=str)


def _result(query: readonly_db.QueryResult, label: str) -> dict:
    return {
        "label": label,
        "sql": query.sql,
        "row_count": len(query.rows),
        "row_cap_hit": query.row_cap_hit,
        "data": query.data,
    }
