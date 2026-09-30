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


# --- resumable runs and modes (decisions D32) -------------------------------------------------------------------


class Scripted:
    """A provider that answers every question with a refusal after `fail_at` calls raises RunPaused."""

    name, model = "gemini", "gemini-3.8-flash"

    def __init__(self, fail_at=None):
        self.requests, self.fail_at = [], fail_at

    def complete(self, system, transcript, tools, **kwargs):
        from app.agent.providers import Turn, Usage
        from evals.throttle import RunPaused

        self.requests.append({"system": system, "tools": [t["name"] for t in tools]})
        if self.fail_at is not None and len(self.requests) > self.fail_at:
            raise RunPaused("daily quota")
        final = {"answer_text": "No.", "refused": True, "refusal_reason": "trap", "evidence_tool_use_ids": [],
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
    assert all(r["provider"] == "gemini" and r["mode"] == "governed" and r["asked_at"] for r in saved)
    assert len(llm.requests) == 2


def test_a_pause_stops_the_run_with_earlier_results_already_saved(offline_prompt):
    from evals.throttle import RunPaused

    saved = []
    with pytest.raises(RunPaused):
        run_eval.ask_all(Scripted(fail_at=1), TRAPS, {}, 5.0, on_result=saved.append)
    assert [r["id"] for r in saved] == ["T0"]


def test_raw_mode_offers_only_run_readonly_sql_and_the_raw_prompt(offline_prompt):
    llm = Scripted()
    results = run_eval.ask_all(llm, TRAPS[:1], {}, 5.0, mode="raw")
    assert llm.requests[0] == {"system": "RAW RULES", "tools": ["run_readonly_sql"]}
    assert results[0]["mode"] == "raw" and results[0]["label_correct"]


def test_run_keys_are_file_safe():
    assert run_eval.run_key("ollama", "raw", "qwen3.8-27b:64k") == "ollama__raw__qwen3.8-27b-64k"
    assert run_eval.run_key("gemini", None, "gemini-3.8-flash") == "gemini__gemini-3.8-flash"


def test_gemini_limits_come_from_env_at_80_percent(monkeypatch):
    monkeypatch.setenv("GEMINI_RPM", "15")
    monkeypatch.setenv("GEMINI_TPM", "1000000")
    monkeypatch.setenv("GEMINI_RPD", "1500")
    limits = run_eval.limits_for("gemini")
    assert (limits.rpm, limits.tpm, limits.rpd) == (12, 800_000, 1200)
    assert run_eval.limits_for("ollama").rpm is None


def test_ollama_show_reports_what_the_server_says():
    import httpx2

    from app.agent.providers import ProviderError, ollama_show

    body = {"details": {"quantization_level": "Q4_K_M", "family": "qwen3", "parameter_size": "27B", "format": "gguf"},
            "model_info": {"qwen3.context_length": 131072}, "parameters": "temperature 0.6\nnum_ctx 65536"}
    ok = httpx2.Client(transport=httpx2.MockTransport(lambda r: httpx2.Response(200, json=body)))
    facts = ollama_show("https://secret.example", "m", http=ok)
    assert (facts["quantization"], facts["context_length"], facts["context_length_trained"]) == ("Q4_K_M", 65536, 131072)
    assert facts["server_parameters"] == {"temperature": "0.6", "num_ctx": "65536"}
    down = httpx2.Client(transport=httpx2.MockTransport(lambda r: httpx2.Response(530, text="<html>")))
    with pytest.raises(ProviderError) as caught:
        ollama_show("https://secret.example", "m", http=down)
    assert caught.value.kind == "infrastructure" and "secret" not in str(caught.value)


def test_gemini_defaults_are_the_owners_flash_lite_quota(monkeypatch):
    for var in ("GEMINI_RPM", "GEMINI_TPM", "GEMINI_RPD"):
        monkeypatch.delenv(var, raising=False)
    limits = run_eval.limits_for("gemini")
    assert (limits.rpm, limits.tpm, limits.rpd) == (12, 200_000, 400)
