"""Golden-set eval of the Ask agent (PLAN §10). Writes evals/results/latest.json and prints a markdown scorecard.

    python evals/run_eval.py [--model M] [--effort E] [--limit N] [--only SL01,MH02] [--budget-usd 5] [--yes]
                             [--require-llm]

1. Validates the question set and computes every golden answer from its hand-written SQL on marts.* (read-only),
   failing loudly on any error. Golden answers never come from the agent or the generator's answer key.
2. With no Anthropic credentials, records status not_run (exit 0; exit 2 with --require-llm).
3. Otherwise prints an estimated cost and spends nothing until you confirm (or pass --yes; a non-interactive run
   without --yes stops there). Then asks each question in-process through run_agent with region ALL, stopping once
   --budget-usd is spent, and scores the answers (evals/scoring.py). Everything but the model is deterministic.
4. A complete run over the whole set also records every answer as served, for the Ask page's replay mode
   (api/app/recordings/<model>.json, decisions D29).
"""

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import anthropic
import psycopg
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "api")]

from app import config
from app.agent.providers import ProviderError
from app.db import db_conninfo
from app.guardrails.readonly_db import json_safe
from app.guardrails.sql_validator import validate
from evals import scoring

QUESTIONS = ROOT / "evals" / "questions.yaml"
RESULTS = ROOT / "evals" / "results" / "latest.json"
RECORDINGS = ROOT / "api" / "app" / "recordings"
CATEGORIES = ("simple_lookup", "filtered_grouped", "time_comparison", "multi_hop_why", "trap")
PER_CATEGORY = 8
LABELS = ("governed_metric", "ad_hoc_sql_verify", "refused")
COMPARE_BY_CATEGORY = {"trap": {"refusal"}, "multi_hop_why": {"rubric"}}
MAX_GOLDEN_ROWS = 20
GOLDEN_TIMEOUT = "120s"
REGION = "ALL"


# The per-question token profile an estimate assumes before a model has been measured: about 4 model calls, each
# reading a ~14k-token cached prefix (tools, rules, metric glossary; written once per run), plus ~3k new input and
# ~1.5k output tokens per call. Once a run of the same model exists, its measured mean cost replaces the profile.
PROFILE = {"calls": 4, "prefix_tokens": 14_000, "fresh_input_tokens": 3_000, "output_tokens": 1_500}
ESTIMATE_MARGIN = 1.25


class GoldenError(Exception):
    pass


# --- question set and golden answers ----------------------------------------------------------------------------


def load_questions() -> tuple[str, list[dict]]:
    spec = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
    questions = spec["questions"]
    problems = []
    ids = Counter(q["id"] for q in questions)
    problems += [f"duplicate id {i}" for i, n in ids.items() if n > 1]
    per_category = Counter(q["category"] for q in questions)
    if per_category != dict.fromkeys(CATEGORIES, PER_CATEGORY):
        problems.append(f"need {PER_CATEGORY} questions in each of {CATEGORIES}, got {dict(per_category)}")
    for q in questions:
        trap, kind = q["category"] == "trap", q["compare"]["type"]
        if q["expected_label"] not in LABELS or (q["expected_label"] == "refused") != trap:
            problems.append(f"{q['id']}: expected_label {q['expected_label']!r} doesn't fit category {q['category']}")
        if kind not in COMPARE_BY_CATEGORY.get(q["category"], {"scalar", "keyed"}):
            problems.append(f"{q['id']}: compare type {kind!r} doesn't fit category {q['category']}")
        if trap == bool(q.get("golden_sql")):
            problems.append(f"{q['id']}: {'traps have no' if trap else 'needs a'} golden_sql")
    if sum(q["expected_label"] == "ad_hoc_sql_verify" for q in questions) < 2:
        problems.append("need at least 2 ad_hoc_sql_verify questions")
    if problems:
        raise GoldenError("Question set is invalid:\n  " + "\n  ".join(problems))
    return str(spec["as_of"]), questions


def compute_goldens(questions: list[dict]) -> tuple[str, dict[str, dict]]:
    """(marts as-of, {id: golden table}) for every non-trap question; raises GoldenError listing every failure."""
    goldens, errors = {}, []
    with psycopg.connect(db_conninfo(), connect_timeout=5, autocommit=True) as conn:
        conn.execute("set default_transaction_read_only = on")
        conn.execute(f"set statement_timeout = '{GOLDEN_TIMEOUT}'")
        (as_of,) = conn.execute("select max(date_day) from marts.dim_date").fetchone()
        for q in questions:
            if q["category"] == "trap":
                continue
            try:
                goldens[q["id"]] = _golden(conn, q)
            except (psycopg.Error, GoldenError) as e:
                errors.append(f"{q['id']}: {type(e).__name__}: {' '.join(str(e).split())}")
    if errors:
        raise GoldenError("Golden validation failed:\n  " + "\n  ".join(errors))
    return as_of.isoformat(), goldens


def _golden(conn: psycopg.Connection, q: dict) -> dict:
    # The agent's own SQL gate: one SELECT over allowlisted marts only. It also caps the rows it returns.
    check = validate(q["golden_sql"], config.MART_TABLES, MAX_GOLDEN_ROWS + 1)
    if not check.ok:
        raise GoldenError(f"golden_sql rejected by the SQL validator: {', '.join(check.reasons)}")
    cursor = conn.execute(check.sql)
    table = {
        "columns": [column.name for column in cursor.description],
        "rows": [[json_safe(value) for value in row] for row in cursor.fetchall()],
    }
    _check_shape(q["compare"], table)
    return table


def _check_shape(spec: dict, table: dict) -> None:
    rows, columns = scoring.records(table), table["columns"]
    if not rows or len(rows) > MAX_GOLDEN_ROWS:
        count = f"{len(rows)}{'+' if len(rows) > MAX_GOLDEN_ROWS else ''}"
        raise GoldenError(f"returned {count} rows; need 1 to {MAX_GOLDEN_ROWS}")
    if spec["type"] in ("scalar", "rubric") and len(rows) != 1:
        raise GoldenError(f"a {spec['type']} golden needs exactly one row, got {len(rows)}")
    if spec["type"] == "scalar":
        needed, numeric = columns, columns
    elif spec["type"] == "keyed":
        keys = [c for entry in spec["keys"] for c in (entry if isinstance(entry, list) else [entry])]
        needed, numeric = keys + spec["values"], spec["values"]
        if len({tuple(scoring.key(row[k]) for k in keys) for row in rows}) != len(rows):
            raise GoldenError("golden keys are not unique")
    else:
        needed = [c for item in spec.get("must_mention", []) for c in item.get("golden", [])]
        numeric = []
    if missing := [c for c in needed if c not in columns]:
        raise GoldenError(f"golden has no column(s) {missing}")
    if nulls := sorted({c for row in rows for c in needed if row[c] is None}):
        raise GoldenError(f"golden has nulls in {nulls}")
    if non_numeric := sorted({c for row in rows for c in numeric if scoring.number(row[c]) is None}):
        raise GoldenError(f"golden values are not numbers in {non_numeric}")


# --- spending gate ----------------------------------------------------------------------------------------------


def estimate_usd(model: str, questions: int, previous: dict | None = None) -> float:
    """Expected spend for asking `questions` questions: the measured mean of a previous run of the same model, or
    the token profile priced at the model's rates; either way with a safety margin."""
    from app.agent.trace import price

    measured = [r["cost_usd"] for r in (previous or {}).get("results", []) if "cost_usd" in r]
    if previous and previous.get("model") == model and measured:
        per_question = sum(measured) / len(measured)
    else:
        input_price, output_price, cache_read_price = price(model)
        p = PROFILE
        per_question = p["calls"] * (
            p["prefix_tokens"] * cache_read_price
            + p["fresh_input_tokens"] * input_price
            + p["output_tokens"] * output_price
        ) / 1_000_000
    return questions * per_question * ESTIMATE_MARGIN


def previous_results() -> dict | None:
    try:
        return json.loads(RESULTS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def confirm_spend(estimate: float, assume_yes: bool, stdin=sys.stdin) -> bool:
    """Paid calls need an explicit yes: --yes, or typing it. A non-interactive run without --yes never spends."""
    if assume_yes:
        return True
    if not stdin.isatty():
        print("Not interactive and --yes not given: nothing was sent to the model.", file=sys.stderr)
        return False
    try:
        reply = input(f"Spend up to about ${estimate:.2f} on model calls? [y/N] ")
    except EOFError:  # Windows reports NUL as a terminal, so "no input" can still arrive here
        return False
    return reply.strip().lower() in ("y", "yes")


# --- agent run --------------------------------------------------------------------------------------------------


def llm_provider():
    """The API's own provider factory, so the eval resolves settings and credentials exactly as /api/ask does."""
    from app.main import llm_provider

    llm_provider.cache_clear()  # --model may have changed config since the API module was imported
    return llm_provider()


def ask_all(provider, questions: list[dict], goldens: dict, budget_usd: float) -> list[dict]:
    from app.agent import loop
    from app.agent.trace import Trace

    # response["data"] is only the primary result, so every tool result is recorded here to score the rest of the
    # evidence (a comparison answered with one query per period).
    recorded: list[dict] = []
    run_tool = loop.run_tool

    def recording_run_tool(name: str, tool_input: dict, region: str) -> dict:
        result = run_tool(name, tool_input, region)
        recorded.append(result)
        return result

    loop.run_tool = recording_run_tool
    results, spent = [], 0.0
    try:
        for n, q in enumerate(questions, 1):
            if spent > budget_usd:
                results.append({**_identity(q), "skipped": f"budget of ${budget_usd:.2f} spent"})
                continue
            recorded.clear()
            trace = Trace(question=q["question"], region_claim=REGION, model=provider.model, provider=provider.name)
            started = time.monotonic()
            response = error = None
            try:
                response = loop.run_agent(provider, q["question"], REGION, trace)
            except (loop.AgentError, anthropic.APIError, ProviderError) as e:  # as /api/ask does; a bug still stops
                error = f"{type(e).__name__}: {e}"
            latency_ms = round((time.monotonic() - started) * 1000)
            spent += trace.est_cost_usd
            tools_used = [call["name"] for call in trace.tool_calls]
            evidence = _evidence(response, recorded)
            verdict = scoring.score_question(q, goldens.get(q["id"]), response, tools_used, evidence)
            results.append({**_result(q, goldens.get(q["id"]), response, trace, verdict, latency_ms, error),
                            "response": response})
            print(f"[{n}/{len(questions)}] {q['id']} {'ok ' if verdict['correct'] else 'BAD'} "
                  f"{results[-1]['actual_label']} {latency_ms} ms ${trace.est_cost_usd:.4f}", flush=True)
    finally:
        loop.run_tool = run_tool
    return results


def _evidence(response: dict | None, recorded: list[dict]) -> list[dict]:
    """The primary result plus every other tool result whose SQL the response cites."""
    if not response or response["label"] == scoring.REFUSED:
        return []
    cited = set(response["sql"])
    tables = [response["data"]] if response["data"] else []
    return tables + [r["data"] for r in recorded if r.get("data") and r.get("sql") in cited and r["data"] not in tables]


def _identity(q: dict) -> dict:
    return {"id": q["id"], "category": q["category"], "question": q["question"], "expected_label": q["expected_label"]}


def _result(q, golden, response, trace, verdict, latency_ms, error) -> dict:
    return {
        **_identity(q),
        "actual_label": response["label"] if response else scoring.ERROR,
        **verdict,
        "answer_text": response["answer_text"] if response else None,
        "confidence_note": response["confidence_note"] if response else None,
        "sql": response["sql"] if response else [],
        "data_rows": len(response["data"]["rows"]) if response and response["data"] else 0,
        "tools_used": [call["name"] for call in trace.tool_calls],
        "tool_calls": trace.tool_calls,
        "golden": golden,
        "tokens": {
            "input": trace.input_tokens,
            "output": trace.output_tokens,
            "cache_read": trace.cache_read_tokens,
            "cache_write": trace.cache_write_tokens,
        },
        "cost_usd": round(trace.est_cost_usd, 5),
        "latency_ms": latency_ms,
        "served_model": trace.served_model,
        "trace_id": str(trace.trace_id),
        "error": error,
    }


# --- output -----------------------------------------------------------------------------------------------------


def build_recording(meta: dict, status: str, results: list[dict]) -> dict:
    """What the Ask page replays: each answer exactly as /api/ask returned it, with the eval's verdict on it."""
    answers = [
        {
            "id": r["id"], "category": r["category"], "question": r["question"], "response": r["response"],
            "eval": {"correct": r["correct"], "label_correct": r["label_correct"]},
            "served_model": r["served_model"], "latency_ms": r["latency_ms"], "cost_usd": r["cost_usd"],
        }
        for r in results
        if r.get("response")
    ]
    return {
        "model": meta["model"], "effort": meta["effort"], "recorded_at": meta["timestamp"], "as_of": meta["as_of"],
        "region": meta["region"], "status": status, "git_commit": meta["git_commit"], "answers": answers,
    }


def _without_response(result: dict) -> dict:
    return {k: v for k, v in result.items() if k != "response"}


def git_commit() -> str | None:
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True)
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return commit.stdout.strip() + ("-dirty" if dirty.stdout.strip() else "")


def write(payload: dict) -> None:
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def golden_summary(goldens: dict[str, dict]) -> str:
    lines = []
    for qid, table in goldens.items():
        rows = scoring.records(table)
        shown = "; ".join(", ".join(f"{k}={_short(v)}" for k, v in row.items()) for row in rows[:3])
        more = " ..." if len(rows) > 3 else ""
        lines.append(f"  {qid}  {len(rows):>2} row{'s' if len(rows) > 1 else ' '}  {shown}{more}")
    return "\n".join(lines)


def _short(value) -> str:
    return f"{value:,.4g}" if isinstance(value, float) else str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ChannelPulse golden-set eval")
    parser.add_argument("--model", help="Anthropic model id (default: CHANNELPULSE_MODEL); other providers read "
                                         "GEMINI_MODEL / OLLAMA_MODEL")
    parser.add_argument("--effort", default=config.EFFORT, help="output effort (default: CHANNELPULSE_EFFORT)")
    parser.add_argument("--limit", type=int, help="ask only the first N selected questions")
    parser.add_argument("--only", help="comma-separated question ids")
    parser.add_argument("--budget-usd", type=float, default=5.00, help="stop once this much is spent (default 5.00)")
    parser.add_argument("--yes", action="store_true", help="spend without asking (after printing the estimate)")
    parser.add_argument("--require-llm", action="store_true", help="exit 2 instead of 0 when no credentials resolve")
    args = parser.parse_args(argv)

    try:
        pinned_as_of, questions = load_questions()
        as_of, goldens = compute_goldens(questions)
    except GoldenError as e:
        print(e, file=sys.stderr)
        return 1
    print(f"Validated {len(goldens)} golden answers against marts (as of {as_of}):\n{golden_summary(goldens)}")
    if as_of != pinned_as_of:
        print(f"WARNING: marts are as of {as_of}, but the golden set is pinned to {pinned_as_of}.", file=sys.stderr)

    selected = questions
    if args.only:
        wanted = {i.strip() for i in args.only.split(",") if i.strip()}
        if unknown := wanted - {q["id"] for q in questions}:
            print(f"Unknown question id(s): {', '.join(sorted(unknown))}", file=sys.stderr)
            return 1
        selected = [q for q in questions if q["id"] in wanted]
    selected = selected[: args.limit] if args.limit is not None else selected

    config.MODEL, config.EFFORT = args.model or config.MODEL, args.effort  # the Anthropic adapter reads these
    meta = {
        "model": config.MODEL,
        "effort": args.effort,
        "as_of": as_of,
        "pinned_as_of": pinned_as_of,
        "region": REGION,
        "git_commit": git_commit(),
        "timestamp": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "budget_usd": args.budget_usd,
        "question_count": len(questions),
        "golden_count": len(goldens),
        "selected": [q["id"] for q in selected],
    }
    provider = llm_provider()
    if provider is None:
        reason = f"The {config.PROVIDER} provider isn't configured (no credentials or endpoint); agent not run."
        write({"status": "not_run", "reason": reason, **meta, "goldens": goldens})
        print(f"\nnot_run: {reason}\nGolden answers are validated; results written to {RESULTS.relative_to(ROOT)}.")
        return 2 if args.require_llm else 0

    meta |= {"provider": provider.name, "model": provider.model, "settings": provider.settings()}
    if provider.name == "anthropic":  # the only paid provider: nothing is spent without a yes
        estimate = estimate_usd(provider.model, len(selected), previous_results())
        print(f"\nAbout to ask {len(selected)} question(s) with {provider.model} (effort {args.effort}). "
              f"Estimated cost ${estimate:.2f}; the run stops once ${args.budget_usd:.2f} is spent (--budget-usd).")
        if estimate > args.budget_usd:
            print("WARNING: the estimate exceeds the budget, so the run will probably stop early and not be recorded "
                  "for replay. Raise --budget-usd (make eval BUDGET=...) to ask every question.")
        if not confirm_spend(min(estimate, args.budget_usd), args.yes):
            print("Cancelled before any model call.")
            return 3

    results = ask_all(provider, selected, goldens, args.budget_usd)
    card = scoring.scorecard(results)
    status = "partial" if card["skipped"] else "complete"
    write({"status": status, **meta, "scorecard": card, "results": [_without_response(r) for r in results]})
    print(f"\n{scoring.markdown(card, meta)}\n\n{status}: results written to {RESULTS.relative_to(ROOT)}.")
    if status == "complete" and len(selected) == len(questions):
        RECORDINGS.mkdir(parents=True, exist_ok=True)
        path = RECORDINGS / f"{args.model}.json"
        path.write_text(json.dumps(build_recording(meta, status, results), indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8", newline="\n")
        print(f"Recorded {len(results)} answers for replay: {path.relative_to(ROOT)}.")
    else:
        print("Not recorded for replay: only a complete run over the whole question set replaces the recording.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
