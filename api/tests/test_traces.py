"""The traces view (decisions D40): recorded eval traces for anyone under their region claim, live ones only for the
admin token."""

import json

import pytest

from app import config, replay, traces

CALL = {"id": "t1", "name": "query_metric", "input": {}, "output": "{}", "sql": "select 1", "row_count": 1,
        "duration_ms": 40, "error": None}


def answer(qid, label, correct, created_at, question="What is DSO?"):
    response = {"answer_text": "x", "sql": ["select 1"] if label != "refused" else [],
                "data": {"columns": ["v"], "rows": [[1]]} if label != "refused" else None, "chart_spec": None,
                "label": label, "confidence_note": "", "trace_id": f"tr-{qid}"}
    trace = {"trace_id": f"tr-{qid}", "created_at": created_at, "provider": "anthropic", "model": "m-1",
             "served_model": "m-1", "tool_calls": [CALL] if label != "refused" else [], "input_tokens": 100,
             "output_tokens": 10, "cache_read_tokens": 0, "cache_write_tokens": 0, "latency_ms": 900,
             "est_cost_usd": 0.0}
    return {"id": qid, "category": "trap" if label == "refused" else "simple_lookup", "question": question,
            "response": response, "eval": {"correct": correct, "label_correct": correct}, "served_model": "m-1",
            "latency_ms": 900, "cost_usd": 0.0, "trace": trace}


LIVE = {**answer("L1", "ad_hoc_sql_verify", None, "2026-10-01T09:00:00+00:00")["trace"], "trace_id": "live-1",
        "question": "A visitor's question", "region_claim": "ALL", "label": "ad_hoc_sql_verify",
        "final_sql": ["select 2"], "row_count": 1, "answer_text": "y", "error": None, "source": "live",
        "category": None, "question_id": None, "eval_correct": None}


@pytest.fixture
def recorded(tmp_path, monkeypatch, api):
    monkeypatch.setattr(replay, "RECORDINGS", tmp_path)
    monkeypatch.setattr(traces, "live", lambda: [dict(LIVE)])
    rec = {"provider": "anthropic", "model": "m-1", "effort": None, "recorded_at": "2026-09-30T00:00:00+00:00",
           "as_of": "2026-09-23", "region": "ALL", "status": "complete", "git_commit": None,
           "answers": [answer("SL01", "governed_metric", True, "2026-09-30T10:00:00+00:00"),
                       answer("TR01", "refused", True, "2026-09-30T10:05:00+00:00", question="Delete the claims")]}
    (tmp_path / "anthropic__m-1.json").write_text(json.dumps(rec), encoding="utf-8")
    return api


def test_recorded_traces_are_listed_newest_first_with_facets_and_totals(recorded):
    body = recorded.http.get("/api/traces").json()
    assert [t["trace_id"] for t in body["traces"]] == ["tr-TR01", "tr-SL01"] and body["live"] == "admin_only"
    assert body["facets"]["label"] == {"governed_metric": 1, "refused": 1}
    assert body["totals"]["input_tokens"] == 200 and body["traces"][1]["tools"] == ["query_metric"]
    assert "tool_calls" not in body["traces"][0]


def test_filters_search_and_paging(recorded):
    assert recorded.http.get("/api/traces?label=refused").json()["total"] == 1
    assert recorded.http.get("/api/traces?q=delete").json()["traces"][0]["question_id"] == "TR01"
    page = recorded.http.get("/api/traces?limit=1&offset=1").json()
    assert page["total"] == 2 and [t["trace_id"] for t in page["traces"]] == ["tr-SL01"]


def test_live_traces_need_the_admin_token(recorded, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_TOKEN", "s3cret")
    assert recorded.http.get("/api/traces", headers={"X-Admin-Token": "wrong"}).json()["total"] == 2
    body = recorded.http.get("/api/traces", headers={"X-Admin-Token": "s3cret"}).json()
    assert body["live"] == "included" and body["traces"][0]["trace_id"] == "live-1"
    assert recorded.http.get("/api/traces/live-1").status_code == 404
    assert recorded.http.get("/api/traces/live-1", headers={"X-Admin-Token": "s3cret"}).json()["question"] == LIVE["question"]


def test_no_admin_token_configured_means_no_live_traces_even_with_an_empty_header(recorded, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_TOKEN", None)
    assert recorded.http.get("/api/traces", headers={"X-Admin-Token": ""}).json()["live"] == "admin_only"


def test_recorded_traces_are_withheld_under_another_region_claim(recorded):
    body = recorded.http.get("/api/traces", headers={"X-Demo-Region": "Assam"}).json()
    assert (body["total"], body["withheld"]) == (0, True)
    assert recorded.http.get("/api/traces/tr-SL01", headers={"X-Demo-Region": "Assam"}).status_code == 404


def test_the_detail_carries_the_tool_calls(recorded):
    body = recorded.http.get("/api/traces/tr-SL01").json()
    assert body["tool_calls"] == [CALL] and body["eval_correct"] is True and body["source"] == "eval"
