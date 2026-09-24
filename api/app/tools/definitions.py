"""The agent's five tools (PLAN §8) as strict JSON schemas. Sorted by name and built once, so the cached prefix is stable."""

from app import config
from app.semantic import FILTER_OPS


def _object(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


_SCALAR = {"anyOf": [{"type": "string"}, {"type": "number"}, {"type": "boolean"}]}
_ROWS = f"at most {config.ROW_CAP} rows, of which you see the first {config.MODEL_ROWS}"

_TOOLS = [
    {
        "name": "list_metrics",
        "description": (
            "List every governed metric in the semantic layer: name, description, grain, dimensions and default "
            "time grain. The same glossary is in the system prompt, so call this only when the user asks what can "
            "be measured, or to cite the glossary as evidence."
        ),
        "input_schema": _object({}),
    },
    {
        "name": "explain_metric",
        "description": (
            "Return one governed metric's full definition: business definition, formula, the SQL template it "
            "compiles to, and caveats. Call it before query_metric whenever you are unsure the metric means what "
            "the question asks, and whenever the user asks how a metric is defined or calculated."
        ),
        "input_schema": _object({"metric_name": {"type": "string", "description": "Exact name from the glossary."}}),
    },
    {
        "name": "query_metric",
        "description": (
            "Compute a governed metric. This is the default way to answer: call it whenever a metric in the "
            "glossary covers the question. MetricFlow compiles the SQL from the metric's definition and it runs "
            "read-only; the result carries the rows and the exact SQL and is labelled governed_metric. Each "
            "glossary metric lists its dimensions, the only names group_by and filters accept: "
            "metric_time__<grain> is the metric's time_dimension at that grain, a bare name such as distributor "
            "is that entity, and entity__attribute names are its attributes. Pass [] for filters or group_by and "
            "null for date_range when you don't need them. Rows grouped by metric_time come back in time order; "
            "any other breakdown comes back largest value first. Distributor-level data is already restricted to "
            f"the viewer's region claim. Returns {_ROWS}."
        ),
        "input_schema": _object({
            "metric_name": {"type": "string", "description": "Exact metric name from the glossary."},
            "filters": {
                "type": "array",
                "description": "Conditions on the metric's dimensions, all of which must hold.",
                "items": _object({
                    "dimension": {"type": "string", "description": "A dimension the glossary lists for this metric."},
                    "op": {"type": "string", "enum": list(FILTER_OPS)},
                    "value": {
                        "anyOf": [_SCALAR, {"type": "array", "items": _SCALAR}],
                        "description": (
                            "A single value (text, number, boolean, or YYYY-MM-DD for metric_time), or a list for "
                            "in / not_in."
                        ),
                    },
                }),
            },
            "group_by": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Dimensions to break the metric down by, time grains included, as the glossary names them.",
            },
            "date_range": _nullable(_object({
                "start": {"type": "string", "format": "date", "description": "First day, inclusive."},
                "end": {"type": "string", "format": "date", "description": "Last day, inclusive."},
            })),
        }),
    },
    {
        "name": "run_readonly_sql",
        "description": (
            "Fallback only: run one read-only SELECT against the marts when no governed metric can express the "
            "question. Check the glossary (and explain_metric) first, and say in your answer that no defined metric "
            "covered it, because the result is labelled ad_hoc_sql_verify. The SQL must be a single SELECT (CTEs, "
            "joins, window functions and UNION are fine) that reads only the marts tables listed in the system "
            "prompt. Writes, other schemas, system catalogs and pg_* or admin functions are rejected before "
            "anything runs, and a rejection lists reason codes so you can fix the query. "
            f"Returns {_ROWS}."
        ),
        "input_schema": _object({"sql": {"type": "string", "description": "One PostgreSQL SELECT statement."}}),
    },
    {
        "name": "get_anomalies",
        "description": (
            "Return the flags raised by ChannelPulse's pre-registered anomaly detectors as of a date: lot_scan "
            "(resin lots whose claim rate for one failure_mode is an outlier), installer_scan (installers with "
            "outlying claim rates), stuffing (quarter-end channel stuffing) and distributor_health (distributors "
            "at risk). Each row is the latest weekly snapshot on or before as_of_date for an entity flagged by "
            "then, with failure_mode (lot_scan only), region (distributor-level rows), effect_size, p_value and "
            "details. Call it for any why, what-changed, what's-unusual or risk question, together with "
            "query_metric for context. Narrate only what it returns; never infer an anomaly it did not return."
        ),
        "input_schema": _object({
            "as_of_date": _nullable({
                "type": "string",
                "format": "date",
                "description": "Snapshot date to read as of; null for the latest snapshot.",
            }),
        }),
    },
]

TOOLS = sorted(({**tool, "strict": True} for tool in _TOOLS), key=lambda tool: tool["name"])
