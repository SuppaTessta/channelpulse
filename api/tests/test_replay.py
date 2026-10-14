"""Live mode is opt-in, and without it the Ask page replays answers recorded by an eval run (decisions D29)."""

import json

import pytest

from app import config, replay

QUESTION = {"question": "How has DSO moved this year?"}
ANSWER = {
    "answer_text": "DSO was 36.2 days.", "sql": ["select 1"], "data": {"columns": ["dso"], "rows": [[36.2]]},
    "chart_spec": None, "label": "governed_metric", "confidence_note": "Governed metric.", "trace_id": "t-1",
}


def recording(model="claude-sonnet-5-5", recorded_at="2026-09-28T10:00:00+00:00", region="ALL", provider="anthropic",
              **extra):
    return {
        "provider": provider, "model": model, "effort": "medium", "recorded_at": recorded_at, "as_of": "2026-09-23", "region": region,
        "status": "complete", "git_commit": "abc1234",
        "answers": [{"id": "SL01", "category": "simple_lookup", "question": "What is DSO?", "response": ANSWER,
                     "eval": {"correct": True, "label_correct": True}, "served_model": model,
                     "latency_ms": 9000, "cost_usd": 0.12}],
        **extra,
    }


@pytest.fixture
def recordings(tmp_path, monkeypatch):
    monkeypatch.setattr(replay, "RECORDINGS", tmp_path)

    def add(**kwargs):
        rec = recording(**kwargs)
        (tmp_path / f"{rec['provider']}__{rec['model']}.json").write_text(json.dumps(rec), encoding="utf-8")
        return rec

    return add


def test_credentials_alone_do_not_make_the_agent_live(api, claude, recordings):
    api.use_llm(claude.client(), live=False)
    response = api.http.post("/api/ask", json=QUESTION)
    assert response.status_code == 503 and "live mode is off" in response.json()["detail"].lower()
    assert api.http.get("/api/ask/status").json()["mode"] == "replay"


def test_status_says_why_the_agent_is_not_live(api, claude, recordings):
    api.use_llm(None)
    assert api.http.get("/api/ask/status").json() == {
        "mode": "replay", "reason": "no_credentials", "model": None, "recording": None}
    api.use_llm(claude.client(), live=False)
    assert api.http.get("/api/ask/status").json()["reason"] == "live_off"
    api.use_llm(claude.client(), live=True)
    assert api.http.get("/api/ask/status").json()["mode"] == "live"


def test_replay_is_empty_and_honest_before_any_eval_has_run(api, recordings):
    api.use_llm(None)
    assert api.http.get("/api/ask/replay").json() == {"recording": None, "answers": [], "withheld": False}


def test_replay_serves_the_recorded_answers_with_their_provenance(api, recordings):
    recordings()
    api.use_llm(None)
    body = api.http.get("/api/ask/replay").json()
    assert body["recording"]["model"] == "claude-sonnet-5-5" and body["recording"]["recorded_at"].startswith("2026-09-28")
    assert body["recording"]["count"] == 1 and not body["withheld"]
    assert body["answers"][0]["response"] == ANSWER and body["answers"][0]["eval"]["correct"] is True


def test_replay_withholds_answers_recorded_under_another_region_claim(api, recordings):
    recordings(region="ALL")
    api.use_llm(None)
    body = api.http.get("/api/ask/replay", headers={"X-Demo-Region": "Assam"}).json()
    assert (body["answers"], body["withheld"], body["recording"]["region"]) == ([], True, "ALL")


def test_replay_prefers_the_configured_models_recording_else_the_newest(api, recordings, monkeypatch):
    recordings(model="claude-haiku-5-5", recorded_at="2026-10-16T10:00:00+00:00")
    recordings(model="claude-sonnet-5-5", recorded_at="2026-10-15T10:00:00+00:00")
    api.use_llm(None)
    monkeypatch.setattr(config, "MODEL", "claude-sonnet-5-5")
    assert api.http.get("/api/ask/replay").json()["recording"]["model"] == "claude-sonnet-5-5"
    monkeypatch.setattr(config, "MODEL", "claude-other")  # no recording of its own: the newest one
    assert api.http.get("/api/ask/replay").json()["recording"]["model"] == "claude-haiku-5-5"
