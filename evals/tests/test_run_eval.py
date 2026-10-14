"""The eval's spending gate and its recorded answers (decisions D29). No database or Anthropic key needed."""

import io

import pytest

from evals import run_eval


def test_the_estimate_prices_the_token_profile_at_the_models_rates():
    haiku, sonnet = run_eval.estimate_usd("claude-haiku-5-5", 40), run_eval.estimate_usd("claude-sonnet-5-5", 40)
    assert 0 < haiku < sonnet
    assert run_eval.estimate_usd("claude-sonnet-5-5", 80) == pytest.approx(2 * sonnet)


def test_a_measured_cost_for_the_same_model_replaces_the_profile():
    previous = {"model": "claude-sonnet-5-5", "results": [{"cost_usd": 0.10}, {"cost_usd": 0.30}, {"skipped": "budget"}]}
    assert run_eval.estimate_usd("claude-sonnet-5-5", 10, previous) == pytest.approx(10 * 0.20 * run_eval.ESTIMATE_MARGIN)
    assert run_eval.estimate_usd("claude-haiku-5-5", 10, previous) == run_eval.estimate_usd("claude-haiku-5-5", 10)


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
    meta = {"model": "claude-sonnet-5-5", "effort": "medium", "timestamp": "2026-09-28T10:00:00+00:00",
            "as_of": "2026-09-23", "region": "ALL", "git_commit": "abc"}
    results = [
        {"id": "T1", "category": "trap", "question": "?", "response": RESPONSE, "correct": True,
         "label_correct": True, "served_model": "claude-sonnet-5-5", "latency_ms": 5, "cost_usd": 0.01,
         "trace_id": "tr-1", "asked_at": "2026-09-28T10:01:00+00:00", "tool_calls": [],
         "tokens": {"input": 10, "output": 2, "cache_read": 0, "cache_write": 0}},
        {"id": "Q1", "category": "simple_lookup", "question": "?", "response": None, "correct": False,
         "label_correct": False, "served_model": None, "latency_ms": 5, "cost_usd": 0.0},
    ]
    rec = run_eval.build_recording(meta, "complete", results)
    assert (rec["model"], rec["recorded_at"], rec["region"], rec["status"]) == (
        "claude-sonnet-5-5", "2026-09-28T10:00:00+00:00", "ALL", "complete")
    assert [a["id"] for a in rec["answers"]] == ["T1"]  # an agent error has no answer to replay
    assert rec["answers"][0]["response"] == RESPONSE and rec["answers"][0]["eval"] == {"correct": True, "label_correct": True}
    trace = rec["answers"][0]["trace"]  # the traces view's row in replay (D40)
    assert (trace["trace_id"], trace["created_at"], trace["input_tokens"], trace["model"]) == (
        "tr-1", "2026-09-28T10:01:00+00:00", 10, "claude-sonnet-5-5")


def test_end_of_input_counts_as_no(monkeypatch):
    # Windows reports NUL (stdin < /dev/null) as a terminal, so the prompt can meet end-of-input.
    def eof(*_):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert run_eval.confirm_spend(1.23, assume_yes=False, stdin=Tty()) is False


# --- resumable runs and modes (decisions D50) -------------------------------------------------------------------


class Scripted:
    """A provider that answers every question with a refusal, and raises `error` after `fail_at` calls."""

    name, model = "anthropic", "claude-haiku-5-5"

    def __init__(self, fail_at=None, error=None):
        self.requests, self.fail_at, self.error = [], fail_at, error

    def complete(self, system, transcript, tools, **kwargs):
        from app.agent.providers import Turn, Usage

        self.requests.append({"system": system, "tools": [t["name"] for t in tools]})
        if self.fail_at is not None and len(self.requests) > self.fail_at:
            raise self.error
        final = {"answer_text": "No.", "refused": True, "refusal_reason": "trap", "clarifying_question": None,
                 "evidence_tool_use_ids": [],
                 "chart_hint": {"type": "none", "x": None, "y": None, "series": None}}
        return Turn("end_turn", __import__("json").dumps(final), [], Usage(100, 10), self.model)

    def settings(self):
        return {}


TRAPS = [{"id": f"T{i}", "category": "trap", "question": "?", "expected_label": "refused",
          "compare": {"type": "refusal"}} for i in range(3)]


@pytest.fixture
def offline_prompt(monkeypatch):
    from app.agent import prompt

    monkeypatch.setattr(prompt, "system_prompt", lambda: "GOVERNED RULES")
    monkeypatch.setattr(prompt, "raw_system_prompt", lambda: "RAW RULES")


def test_a_resumed_run_skips_answered_questions_and_saves_each_new_one(offline_prompt):
    saved, llm = [], Scripted()
    done = {"T0": {"id": "T0", "category": "trap", "from": "earlier"}}
    results = run_eval.ask_all(llm, TRAPS, {}, 5.0, done=done, on_result=saved.append)
    assert results[0] == done["T0"] and [r["id"] for r in saved] == ["T1", "T2"]
    assert all(r["provider"] == "anthropic" and r["mode"] == "governed" and r["asked_at"] for r in saved)
    assert len(llm.requests) == 2


def _api_error(status=None, message=""):
    import anthropic
    import httpx2

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    if status is None:
        return anthropic.APIConnectionError(request=request)
    response = httpx2.Response(status, request=request)
    return anthropic.APIStatusError(message, response=response, body=None)


@pytest.mark.parametrize("error", [_api_error(), _api_error(429), _api_error(529), _api_error(500),
                                   _api_error(400, "Your credit balance is too low to access the Anthropic API.")],
                         ids=["unreachable", "rate-limited", "overloaded", "5xx", "out-of-credit"])
def test_a_service_failure_pauses_the_run_with_earlier_results_already_saved(offline_prompt, error):
    saved = []
    with pytest.raises(run_eval.RunPaused):
        run_eval.ask_all(Scripted(fail_at=1, error=error), TRAPS, {}, 5.0, on_result=saved.append)
    assert [r["id"] for r in saved] == ["T0"]


def test_a_rejected_request_is_the_questions_failure_not_a_pause(offline_prompt):
    saved = []
    results = run_eval.ask_all(Scripted(fail_at=1, error=_api_error(400, "messages: bad")), TRAPS, {}, 5.0,
                               on_result=saved.append)
    assert [r["id"] for r in results] == ["T0", "T1", "T2"] and results[1]["error"].startswith("APIStatusError")


def test_raw_mode_offers_only_run_readonly_sql_and_the_raw_prompt(offline_prompt):
    llm = Scripted()
    results = run_eval.ask_all(llm, TRAPS[:1], {}, 5.0, mode="raw")
    assert llm.requests[0] == {"system": "RAW RULES", "tools": ["run_readonly_sql"]}
    assert results[0]["mode"] == "raw" and results[0]["label_correct"]


def test_run_keys_are_file_safe():
    assert run_eval.run_key("anthropic", "raw", "claude:haiku 5.5") == "anthropic__raw__claude-haiku-5.5"
    assert run_eval.run_key("anthropic", None, "claude-sonnet-5-5") == "anthropic__claude-sonnet-5-5"
