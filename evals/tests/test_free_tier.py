"""The eval's free tier (decisions D39): every check in the golden set that needs no model. It runs in CI on every PR
through `make test`: the routing, validator and compile checks everywhere, the database checks where Postgres is up.

- Refusal routing: the model-free router refuses exactly the questions marked `router`, and nothing answerable.
- SQL validator: every trap's `attack_sql`, the SQL a compliant model would run, is rejected before it runs.
- Semantic layer: every governed question's `governed_call` compiles, and on the database its result matches the
  hand-written golden SQL under the same scorer the model suite uses.
- Goldens: the whole set validates against the marts, and every ambiguous question's readings really disagree.
"""

import json

import psycopg
import pytest

from app import config, semantic
from app.db import db_conninfo
from app.guardrails import refusal_routing
from app.guardrails.sql_validator import validate
from app.tools.handlers import query_metric
from evals import run_eval, scoring

_, QUESTIONS = run_eval.load_questions()
GOVERNED = [q for q in QUESTIONS if q.get("governed_call")]
ATTACKS = [(q["id"], sql) for q in QUESTIONS for sql in q.get("attack_sql", [])]
MATCHERS = {"scalar": scoring.match_scalar, "keyed": scoring.match_keyed}


def _calls(q: dict) -> list[dict]:
    """The query_metric inputs as the model would send them: dates as ISO strings, every key present."""
    return [{"filters": [], "group_by": [], "date_range": None, **json.loads(json.dumps(c, default=str))}
            for c in q["governed_call"]]


def test_the_set_has_six_categories_and_over_a_hundred_questions():
    assert len(QUESTIONS) >= run_eval.MIN_QUESTIONS
    assert {q["category"] for q in QUESTIONS} == set(run_eval.CATEGORIES)


@pytest.mark.parametrize("q", QUESTIONS, ids=lambda q: q["id"])
def test_refusal_routing(q):
    assert refusal_routing.route(q["question"]) == q.get("router")


@pytest.mark.parametrize(("qid", "sql"), ATTACKS, ids=[f"{qid}-{n}" for n, (qid, _) in enumerate(ATTACKS)])
def test_attack_sql_is_rejected(qid, sql):
    assert not validate(sql, config.MART_TABLES, config.ROW_CAP).ok


@pytest.mark.parametrize("q", GOVERNED, ids=lambda q: q["id"])
def test_governed_call_compiles(q):
    for call in _calls(q):
        semantic.compile_query(call["metric_name"], call["filters"], call["group_by"], call["date_range"], "ALL")


@pytest.fixture(scope="module")
def conn():
    with psycopg.connect(db_conninfo(), connect_timeout=5, autocommit=True) as c:
        c.execute("set default_transaction_read_only = on")
        yield c


@pytest.mark.db
@pytest.mark.parametrize("q", GOVERNED, ids=lambda q: q["id"])
def test_governed_call_reproduces_the_golden(q, conn):
    golden = run_eval._golden(conn, q)
    tables = [query_metric(call, run_eval.REGION)["data"] for call in _calls(q)]
    match = MATCHERS[q["compare"]["type"]](golden, q["compare"], tables)
    assert match["ok"], match


@pytest.mark.db
def test_every_golden_validates_and_every_ambiguous_question_has_distinct_readings():
    _, goldens = run_eval.compute_goldens(QUESTIONS)  # raises GoldenError listing every failure
    assert {q["id"] for q in QUESTIONS if q["category"] != "trap"} == goldens.keys()


@pytest.mark.db
def test_channel_stock_units_counts_all_stock_and_days_of_stock_only_the_selling_pairs(conn):
    """D45: channel stock is every unit held; days of stock divides only the stock that has recent sell-out."""
    week = {"start": "2026-09-14", "end": "2026-09-20"}
    (total, selling, dos), = conn.execute(
        "select sum(stock_units), sum(stock_units) filter (where days_of_stock is not null),"
        " sum(stock_units) filter (where days_of_stock is not null)::numeric"
        " / sum(avg_daily_secondary_units) filter (where days_of_stock is not null)"
        " from marts.mart_channel_inventory_weekly where week_start = '2026-09-14'").fetchall()

    def metric(name):
        call = {"metric_name": name, "filters": [], "group_by": ["metric_time__week"], "date_range": week}
        return query_metric(call, run_eval.REGION)["data"]["rows"][-1][-1]

    assert metric("channel_stock_units") == total and metric("channel_stock_units_selling") == selling
    assert scoring.close(metric("channel_days_of_stock"), float(dos), 1e-5)
