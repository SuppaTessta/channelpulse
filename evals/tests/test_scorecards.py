"""The README's comparison table is built from committed run files, never typed by hand (decisions D38)."""

import json

from evals import scorecards


def run_file(tmp_path, name, *, provider="gemini", mode="governed", status="complete", accuracy=0.875):
    card = {"execution_accuracy": accuracy, "refusal_correctness": 1.0, "confidently_wrong": ["TC01"],
            "median_latency_ms": 9016, "p95_latency_ms": 44469, "tokens_per_question": {"input": 40670, "output": 304},
            "infra_retries": 1, "rate_limit_waits": 0, "scored": 40,
            "accuracy_by_category": {"simple_lookup": 1.0, "trap": 1.0}}
    body = {"status": status, "meta": {"provider": provider, "mode": mode, "model": "m-1", "timestamp": "2026-09-30T01:00:00+00:00",
                                       "settings": {"temperature": 0.0, "thinking": "off"}}}
    if status == "complete":
        body["scorecard"] = card
    (tmp_path / name).write_text(json.dumps(body), encoding="utf-8")


def test_only_complete_runs_are_tabled_with_their_label(tmp_path):
    run_file(tmp_path, "gemini__governed__m-1.json")
    run_file(tmp_path, "gemini__governed__m-1__before-D36.json", accuracy=0.8)
    run_file(tmp_path, "ollama__governed__q__partial-pre-D37.json", provider="ollama", status="partial")
    rows = scorecards.load(tmp_path)
    assert [(r["provider"], r["label"], r["accuracy"]) for r in rows] == [
        ("gemini", "current", 0.875), ("gemini", "before-D36", 0.8)]


def test_the_table_shows_every_reported_measure(tmp_path):
    run_file(tmp_path, "gemini__raw__m-1.json", mode="raw", accuracy=0.719)
    table = scorecards.markdown(scorecards.load(tmp_path))
    header, _, row = table.splitlines()[:3]
    for column in ("Execution accuracy", "Refusal correctness", "Confidently wrong", "Latency median / p95",
                   "Tokens / question", "Infra retries"):
        assert column in header
    assert "71.9%" in row and "raw" in row and "9.0 s / 44.5 s" in row and "40,670 / 304" in row and "2026-09-30" in row
