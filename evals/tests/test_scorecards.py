"""The README's comparison table is built from committed run files, never typed by hand (decisions D38)."""

import json

import pytest

from evals import scorecards, scoring


def run_file(tmp_path, name, *, provider="gemini", mode="governed", status="complete", accuracy=0.875):
    card = {"execution_accuracy": accuracy, "refusal_correctness": 1.0, "confidently_wrong": ["TC01"],
            "median_latency_ms": 9016, "p95_latency_ms": 44469, "tokens_per_question": {"input": 40670, "output": 304},
            "infra_retries": 1, "rate_limit_waits": 0, "scored": 40, "questions": 40,
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
    for column in ("Execution accuracy", "Wrong answers", "Ambiguous answered without asking", "Traps answered",
                   "Traps refused: router + model", "Latency median / p95", "Tokens / question", "Infra retries"):
        assert column in header
    assert "71.9%" in row and "raw" in row and "9.0 s / 44.5 s" in row and "40,670 / 304" in row and "2026-09-30" in row


def test_the_readme_block_between_the_markers_is_replaced_and_nothing_else(tmp_path):
    run_file(tmp_path, "gemini__raw__m-1.json", mode="raw", accuracy=0.719)
    readme = tmp_path / "README.md"
    readme.write_text("intro\n<!-- scorecard:start -->\nold table\n<!-- scorecard:end -->\noutro\n", encoding="utf-8")
    scorecards.update_readme(readme, scorecards.load(tmp_path))
    text = readme.read_text(encoding="utf-8")
    assert text.startswith("intro\n<!-- scorecard:start -->\n") and text.endswith("<!-- scorecard:end -->\noutro\n")
    assert "old table" not in text and "71.9%" in text


def result(qid, category, correct, refused=False, routed=False):
    return {"id": qid, "category": category, "correct": correct, "refused": refused,
            "confidence_note": "Refused before any model call (write)." if routed else ""}


def test_the_paired_table_counts_changes_between_raw_and_governed_on_answerable_questions(tmp_path):
    governed = [result("A", "simple_lookup", True), result("B", "simple_lookup", True),
                result("C", "simple_lookup", False), result("T", "trap", True, refused=True)]
    raw = [result("A", "simple_lookup", False), result("B", "simple_lookup", True),
           result("C", "simple_lookup", True), result("T", "trap", False)]
    p = scoring.paired(governed, raw)
    assert (p["questions"], p["wrong_to_right"], p["right_to_wrong"], p["both_right"], p["both_wrong"]) == (3, 1, 1, 1, 0)
    assert p["right_to_wrong_ids"] == ["C"] and p["mcnemar_p"] == 1.0


@pytest.mark.parametrize(("b", "c", "p"), [(0, 0, 1.0), (5, 0, 0.0625), (20, 1, 2 * 22 / 2**21), (3, 3, 1.0)])
def test_mcnemar_exact(b, c, p):
    assert scoring.mcnemar_exact(b, c) == pytest.approx(p)
