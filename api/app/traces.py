"""The agent traces admin view (Part C 2, decisions D40): one list over two sources of ops.agent_traces-shaped rows.

- Recorded: every answer in the shipped eval recordings (recordings/, D29) carries the trace the eval wrote for it.
  These are the golden-set questions, so they're safe to show anyone, but, as in replay, only under the region
  claim they were recorded with: their tool outputs can hold rows another claim may not see.
- Live: ops.agent_traces, written by POST /api/ask. Those questions were typed by real visitors, so they're served
  only with the admin token (ADMIN_TOKEN); with none configured they're never served.
"""

import hmac
from collections import Counter

import psycopg
from psycopg.rows import dict_row

from app import config, replay
from app.db import ops_conninfo

LIVE_LIMIT = 500  # newest live traces read per request
PAGE_MAX = 200
FACETS = ("source", "label", "provider", "model", "category")

_LIVE_SQL = """\
select trace_id::text, created_at, question, region_claim, provider, model, served_model, label, tool_calls,
       final_sql, row_count, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, latency_ms,
       est_cost_usd::float as est_cost_usd, answer_text, error
from ops.agent_traces
order by created_at desc
limit %s"""


def is_admin(token: str | None) -> bool:
    return bool(config.ADMIN_TOKEN) and token is not None and hmac.compare_digest(token, config.ADMIN_TOKEN)


def recorded(region: str) -> list[dict]:
    """Traces from every recording (all providers), newest run first; empty under a different region claim."""
    rows = []
    for recording in replay.load_all():
        if recording["region"] != region:
            continue
        for answer in recording["answers"]:
            trace = answer.get("trace")
            if trace is None:  # recorded before traces were
                continue
            response = answer["response"]
            rows.append({
                **trace,
                "source": "eval",
                "question": answer["question"],
                "category": answer["category"],
                "question_id": answer["id"],
                "region_claim": recording["region"],
                "label": response["label"],
                "final_sql": response["sql"],
                "row_count": len(response["data"]["rows"]) if response["data"] else None,
                "answer_text": response["answer_text"],
                "eval_correct": answer["eval"]["correct"],
                "error": None,
            })
    return rows


def live() -> list[dict]:
    with psycopg.connect(ops_conninfo(), connect_timeout=3, row_factory=dict_row) as conn:
        rows = conn.execute(_LIVE_SQL, (LIVE_LIMIT,)).fetchall()
    return [{**row, "created_at": row["created_at"].isoformat(), "source": "live", "category": None,
             "question_id": None, "eval_correct": None} for row in rows]


def listing(rows: list[dict], filters: dict, q: str | None, limit: int, offset: int) -> dict:
    """Filtered, newest first, paged; facets count the unfiltered rows so every option stays visible."""
    wanted = {k: v for k, v in filters.items() if v}
    needle = (q or "").strip().casefold()
    kept = [
        r for r in rows
        if all(str(r.get(k)) == v for k, v in wanted.items())
        and (not needle or needle in r["question"].casefold() or any(needle in s.casefold() for s in r["final_sql"]))
    ]
    kept.sort(key=lambda r: r["created_at"], reverse=True)
    return {
        "total": len(kept),
        "traces": [_summary(r) for r in kept[offset: offset + min(limit, PAGE_MAX)]],
        "facets": {f: dict(Counter(str(r[f]) for r in rows if r.get(f) is not None).most_common()) for f in FACETS},
        "totals": _totals(kept),
    }


def _summary(row: dict) -> dict:
    """A list row: everything but the tool calls' inputs and outputs."""
    return {k: v for k, v in row.items() if k != "tool_calls"} | {
        "tools": [call["name"] for call in row["tool_calls"]],
        "tool_errors": sum(call.get("error") is not None for call in row["tool_calls"]),
    }


def _totals(rows: list[dict]) -> dict:
    latencies = sorted(r["latency_ms"] for r in rows if r["latency_ms"] is not None)
    return {
        "traces": len(rows),
        "input_tokens": sum(r["input_tokens"] for r in rows),
        "output_tokens": sum(r["output_tokens"] for r in rows),
        "est_cost_usd": round(sum(r["est_cost_usd"] for r in rows), 5),
        "median_latency_ms": latencies[len(latencies) // 2] if latencies else None,
        "by_label": dict(Counter(r["label"] for r in rows)),
    }
