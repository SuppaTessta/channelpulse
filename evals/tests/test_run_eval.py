"""The eval's spending gate and its recorded answers (decisions D29). No database or Anthropic key needed."""

import io

import pytest

from evals import run_eval


def test_the_estimate_prices_the_token_profile_at_the_models_rates():
    opus, sonnet = run_eval.estimate_usd("claude-opus-5-5", 40), run_eval.estimate_usd("claude-sonnet-5", 40)
    assert 0 < sonnet < opus
    assert run_eval.estimate_usd("claude-opus-5-5", 80) == pytest.approx(2 * opus)


def test_a_measured_cost_for_the_same_model_replaces_the_profile():
    previous = {"model": "claude-sonnet-5", "results": [{"cost_usd": 0.10}, {"cost_usd": 0.30}, {"skipped": "budget"}]}
    assert run_eval.estimate_usd("claude-sonnet-5", 10, previous) == pytest.approx(10 * 0.20 * run_eval.ESTIMATE_MARGIN)
    assert run_eval.estimate_usd("claude-opus-5-5", 10, previous) == run_eval.estimate_usd("claude-opus-5-5", 10)


class Tty(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture
def no_input(monkeypatch):
    def fail(*_):
        raise AssertionError("asked for input")

    monkeypatch.setattr("builtins.input", fail)


def test_yes_skips_the_question(no_input):
    assert run_eval.confirm_spend(1.23, assume_yes=True, stdin=io.StringIO())


def test_a_non_interactive_run_without_yes_never_spends(no_input):
    assert not run_eval.confirm_spend(1.23, assume_yes=False, stdin=io.StringIO())


@pytest.mark.parametrize(("reply", "expected"), [("y", True), ("yes", True), ("", False), ("n", False)])
def test_an_interactive_run_spends_only_on_an_explicit_yes(monkeypatch, reply, expected):
    monkeypatch.setattr("builtins.input", lambda *_: reply)
    assert run_eval.confirm_spend(1.23, assume_yes=False, stdin=Tty()) is expected


RESPONSE = {"answer_text": "x", "sql": [], "data": None, "chart_spec": None, "label": "refused",
            "confidence_note": "n", "trace_id": "t"}


def test_the_recording_keeps_each_answer_as_served_with_its_eval_verdict():
    meta = {"model": "claude-opus-5-5", "effort": "medium", "timestamp": "2026-09-28T10:00:00+00:00",
            "as_of": "2026-09-23", "region": "ALL", "git_commit": "abc"}
    results = [
        {"id": "T1", "category": "trap", "question": "?", "response": RESPONSE, "correct": True,
         "label_correct": True, "served_model": "claude-opus-5-5", "latency_ms": 5, "cost_usd": 0.01},
        {"id": "Q1", "category": "simple_lookup", "question": "?", "response": None, "correct": False,
         "label_correct": False, "served_model": None, "latency_ms": 5, "cost_usd": 0.0},
    ]
    rec = run_eval.build_recording(meta, "complete", results)
    assert (rec["model"], rec["recorded_at"], rec["region"], rec["status"]) == (
        "claude-opus-5-5", "2026-09-28T10:00:00+00:00", "ALL", "complete")
    assert [a["id"] for a in rec["answers"]] == ["T1"]  # an agent error has no answer to replay
    assert rec["answers"][0]["response"] == RESPONSE and rec["answers"][0]["eval"] == {"correct": True, "label_correct": True}


def test_end_of_input_counts_as_no(monkeypatch):
    # Windows reports NUL (stdin < /dev/null) as a terminal, so the prompt can meet end-of-input.
    def eof(*_):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert run_eval.confirm_spend(1.23, assume_yes=False, stdin=Tty()) is False
