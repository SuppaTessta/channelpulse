"""Scoring and question-set checks. No database or Anthropic key needed."""

import json
import re
from types import SimpleNamespace

import pytest
from anthropic.types.beta import BetaMessage

from evals import run_eval, scoring

SCALAR = {"type": "scalar", "tolerance_rel": 0.005}
KEYED = {"type": "keyed", "keys": ["region"], "values": ["value"], "tolerance_rel": 0.005, "allow_extra_keys": False}
REGIONS = {"columns": ["region", "value"], "rows": [["Assam", 100.0], ["Odisha", 200.0]]}


def table(columns, *rows):
    return {"columns": columns, "rows": [list(row) for row in rows]}


def question(category="simple_lookup", label="governed_metric", compare=SCALAR):
    return {"id": "Q", "category": category, "expected_label": label, "compare": compare}


def answer(label="governed_metric", text="", data=None):
    return {"label": label, "answer_text": text, "sql": ["select 1"], "data": data}


# --- tolerance and normalisation ---------------------------------------------------------------------------------


@pytest.mark.parametrize(("actual", "expected"), [(100.5, True), (99.5, True), (100.51, False), (99.49, False)])
def test_tolerance_is_relative_and_inclusive_at_the_edge(actual, expected):
    assert scoring.close(actual, 100, 0.005) is expected


def test_a_golden_zero_needs_an_exact_zero():
    assert scoring.close(0.0, 0, 0.005) and not scoring.close(1e-6, 0, 0.005)


@pytest.mark.parametrize("actual", [None, True, "100", float("nan")])
def test_non_numbers_never_match(actual):
    assert not scoring.close(actual, 100, 0.5)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("2025-04-01T00:00:00", "2025-04-01"), ("2025-04-01", "2025-04-01"), (" Assam ", "assam"), (2.0, "2"),
     (1, "1"), (True, "true"), (None, None)],
)
def test_keys_normalise_timestamps_case_and_integral_numbers(value, expected):
    assert scoring.key(value) == expected


# --- scalar -------------------------------------------------------------------------------------------------------


def test_scalar_finds_each_golden_value_in_any_evidence_table():
    golden = table(["fy25", "fy26"], [4.594e9, 4.918e9])
    evidence = [table(["primary_sales_value"], [4.595e9]), table(["primary_sales_value"], [4.918e9])]
    assert scoring.match_scalar(golden, SCALAR, evidence)["ok"]


def test_scalar_fails_when_one_value_is_missing():
    golden = table(["fy25", "fy26"], [4.594e9, 4.918e9])
    result = scoring.match_scalar(golden, SCALAR, [table(["v"], [4.594e9])])
    assert result["found"] == {"fy25": True, "fy26": False} and not result["ok"]


# --- keyed: columns are matched by value, not name ---------------------------------------------------------------


def test_agent_columns_are_matched_by_value_whatever_they_are_called():
    agent = table(["primary_sales_value", "distributor__region"], [100.2, "Assam"], [199.5, "odisha"])
    assert scoring.map_keys(scoring.records(REGIONS), ["region"], agent) == [("region", 1)]
    assert scoring.match_keyed(REGIONS, KEYED, [agent])["ok"]


def test_a_key_may_match_any_of_its_alternative_golden_columns():
    golden = table(["distributor_id", "distributor_name", "dso"], ["D0019", "Mishra Agencies", 81.5])
    spec = {**KEYED, "keys": [["distributor_id", "distributor_name"]], "values": ["dso"]}
    by_name = table(["distributor__distributor_name", "dso"], ["Mishra Agencies", 81.5])
    assert scoring.match_keyed(golden, spec, [by_name])["ok"]


def test_no_key_overlap_means_no_mapping():
    assert scoring.map_keys(scoring.records(REGIONS), ["region"], table(["x"], ["Bihar"])) is None


def test_keyed_fails_on_a_missing_key_or_a_value_out_of_tolerance():
    missing = table(["r", "v"], ["Assam", 100.0])
    off = table(["r", "v"], ["Assam", 100.0], ["Odisha", 202.0])
    assert scoring.match_keyed(REGIONS, KEYED, [missing])["missing"] == [{"key": ["Odisha"], "value": "value"}]
    assert not scoring.match_keyed(REGIONS, KEYED, [off])["ok"]


def test_extra_keys_fail_only_when_not_allowed():
    agent = table(["r", "v"], ["Assam", 100.0], ["Odisha", 200.0], ["Bihar", 5.0])
    assert not scoring.match_keyed(REGIONS, KEYED, [agent])["ok"]
    assert scoring.match_keyed(REGIONS, {**KEYED, "allow_extra_keys": True}, [agent])["ok"]


def test_a_comparison_answered_with_one_query_per_period_matches_across_tables():
    golden = table(["plant", "fy25", "fy26"], ["DGP", 533, 794], ["HWH", 1129, 1306])
    spec = {**KEYED, "keys": ["plant"], "values": ["fy25", "fy26"]}
    fy25 = table(["batch__plant_id", "warranty_claims"], ["DGP", 533], ["HWH", 1129])
    fy26 = table(["batch__plant_id", "warranty_claims"], ["DGP", 794], ["HWH", 1306])
    assert scoring.match_keyed(golden, spec, [fy25, fy26])["ok"]
    assert scoring.match_keyed(golden, spec, [fy25])["matched"] == 2


def test_a_numeric_key_is_not_mistaken_for_the_value():
    golden = table(["tier", "rate"], [1, 0.33], [2, 0.34])
    spec = {**KEYED, "keys": ["tier"], "values": ["rate"]}
    wrong = table(["distributor__tier", "rate"], [1, 1.0], [2, 2.0])
    assert not scoring.match_keyed(golden, spec, [wrong])["ok"]


def test_monthly_keys_match_metricflow_timestamps():
    golden = table(["month", "value"], ["2025-04-01", 5.987e8])
    spec = {**KEYED, "keys": ["month"]}
    agent = table(["metric_time__month", "secondary_sales_value"], ["2025-04-01T00:00:00", 5.99e8])
    assert scoring.match_keyed(golden, spec, [agent])["ok"]


# --- rubric -------------------------------------------------------------------------------------------------------

RUBRIC = {
    "type": "rubric",
    "must_mention": [{"golden": ["lot"]}],
    "must_not_mention": [r"\bcaused\s+by\s+(a\s+|the\s+)?(production\s+)?batch\b"],
    "evidence_tools": ["get_anomalies", ["query_metric", "run_readonly_sql"]],
}
LOT = table(["lot", "mode"], ["RL-DGP-L2-250310", "base_crack|base crack"])
TOOLS = ["get_anomalies", "query_metric"]


def test_rubric_passes_with_the_golden_term_the_tools_and_no_forbidden_claim():
    result = scoring.match_rubric(LOT, RUBRIC, "Resin lot RL-DGP-L2-250310 has 4x the base-crack rate.", TOOLS)
    assert result["ok"], result


def test_mentions_ignore_case_and_punctuation_and_take_pipe_alternatives():
    spec = {"must_mention": [{"golden": ["mode"]}]}
    assert scoring.match_rubric(LOT, spec, "Mostly Base-Cracks.", [])["ok"]
    assert not scoring.mentions("XRL-DGP-L2-250310", "RL-DGP-L2-250310")


def test_rubric_fails_without_the_golden_term():
    result = scoring.match_rubric(LOT, RUBRIC, "One lot looks bad.", TOOLS)
    assert result["missing_mentions"] == [["RL-DGP-L2-250310"]] and not result["ok"]


def test_a_forbidden_claim_fails_but_its_negation_does_not():
    claim = "RL-DGP-L2-250310 is flagged. The rise was caused by a production batch."
    negated = "RL-DGP-L2-250310 is flagged. The rise was not caused by a production batch."
    forbidden = scoring.match_rubric(LOT, RUBRIC, claim, TOOLS)["forbidden_claims"]
    assert forbidden == ["The rise was caused by a production batch."]
    assert scoring.match_rubric(LOT, RUBRIC, negated, TOOLS)["ok"]


def test_every_evidence_tool_is_required_and_a_list_means_any_of():
    text = "RL-DGP-L2-250310."
    assert scoring.match_rubric(LOT, RUBRIC, text, ["get_anomalies", "run_readonly_sql"])["ok"]
    assert scoring.match_rubric(LOT, RUBRIC, text, ["query_metric"])["missing_tools"] == ["get_anomalies"]


# --- refusal, labels and confidently wrong -----------------------------------------------------------------------

TRAP = question("trap", "refused", {"type": "refusal"})
ONE = table(["v"], [1.0])


def test_a_refused_trap_is_correct():
    verdict = scoring.score_question(TRAP, None, answer("refused"), [], [])
    assert (verdict["correct"], verdict["refusal_correct"], verdict["label_correct"], verdict["confidently_wrong"]) == (
        True, True, True, False)


def test_an_answered_trap_is_a_refusal_miss_and_confidently_wrong():
    verdict = scoring.score_question(TRAP, None, answer(data=ONE), [], [ONE])
    assert (verdict["correct"], verdict["refusal_correct"], verdict["confidently_wrong"]) == (False, False, True)


def test_refusing_an_answerable_question_is_wrong_but_not_confidently_wrong():
    verdict = scoring.score_question(question(), ONE, answer("refused"), [], [])
    assert (verdict["correct"], verdict["refusal_correct"], verdict["confidently_wrong"]) == (False, False, False)


def test_wrong_data_is_confidently_wrong():
    verdict = scoring.score_question(question(), ONE, answer(data=table(["v"], [2.0])), [], [table(["v"], [2.0])])
    assert (verdict["correct"], verdict["refusal_correct"], verdict["confidently_wrong"]) == (False, True, True)


def test_an_agent_error_is_neither_refused_nor_confidently_wrong():
    verdict = scoring.score_question(question(), ONE, None, [], [])
    assert (verdict["correct"], verdict["refused"], verdict["confidently_wrong"], verdict["label_correct"]) == (
        False, False, False, False)


def test_label_correctness_compares_expected_and_actual_labels():
    adhoc = question(label="ad_hoc_sql_verify")
    assert not scoring.score_question(adhoc, ONE, answer(data=ONE), [], [ONE])["label_correct"]
    assert scoring.score_question(adhoc, ONE, answer("ad_hoc_sql_verify", data=ONE), [], [ONE])["label_correct"]


# --- scorecard ----------------------------------------------------------------------------------------------------


def result(qid, category, correct, refused=False, latency=1000, cost=0.01, skipped=None):
    if skipped:
        return {"id": qid, "category": category, "skipped": skipped}
    trap = category == "trap"
    return {
        "id": qid, "category": category, "correct": correct, "refused": refused,
        "refusal_correct": refused == trap, "label_correct": correct, "actual_label": "refused" if refused else "x",
        "confidently_wrong": not refused and not correct, "latency_ms": latency, "cost_usd": cost,
        "tokens": {"input": 10, "output": 5, "cache_read": 100, "cache_write": 0},
    }


def test_p95_is_nearest_rank():
    assert scoring.p95(list(range(1, 21))) == 19 and scoring.p95([7]) == 7 and scoring.p95([]) is None


def test_scorecard_scores_traps_by_refusal_and_leaves_skipped_questions_out():
    results = [
        result("A", "simple_lookup", True, latency=100),
        result("B", "simple_lookup", False, latency=300),
        result("C", "trap", True, refused=True, latency=200),
        result("D", "trap", False, latency=400),
        result("E", "trap", False, skipped="budget"),
    ]
    card = scoring.scorecard(results)
    assert card["execution_accuracy"] == 0.5 and card["accuracy_by_category"]["trap"] == 0.5
    refusals = (card["refusal_correctness"], card["refused_exactly_the_traps"], card["missed_traps"])
    assert refusals == (0.75, False, ["D"])
    assert card["confidently_wrong"] == ["B", "D"] and (card["scored"], card["skipped"]) == (4, 1)
    assert (card["avg_latency_ms"], card["p95_latency_ms"], card["total_cost_usd"]) == (250, 400, 0.04)
    assert card["total_tokens"]["cache_read"] == 400
    rendered = scoring.markdown(card, {"model": "m", "effort": "e", "as_of": "d"})
    assert "Execution accuracy (answerable) | 50.0%" in rendered


# --- the harness, offline: a scripted Claude and a fake tool ----------------------------------------------------


def message(*content, stop_reason="end_turn"):
    usage = {"input_tokens": 1000, "output_tokens": 200, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    return BetaMessage.model_validate({
        "id": "msg", "type": "message", "role": "assistant", "model": "claude-opus-5", "content": list(content),
        "stop_reason": stop_reason, "stop_sequence": None, "usage": usage,
    })


def final(**fields):
    body = {"answer_text": "", "refused": False, "refusal_reason": None, "evidence_tool_use_ids": [],
            "chart_hint": {"type": "none", "x": None, "y": None, "series": None}, **fields}
    return {"type": "text", "text": json.dumps(body)}


def test_ask_all_scores_every_cited_result_refuses_traps_and_stops_at_the_budget(monkeypatch):
    from app.agent import loop
    from app.agent.providers import AnthropicProvider

    def fake_tool(name, tool_input, region):
        value = tool_input["value"]
        return {"label": "governed_metric", "sql": f"select {value}", "row_count": 1, "row_cap_hit": False,
                "data": {"columns": ["metric"], "rows": [[value]]}}

    uses = [{"type": "tool_use", "id": f"t{i}", "name": "query_metric", "input": {"value": v}}
            for i, v in enumerate((10.0, 20.0), 1)]
    replies = [
        message(*uses, stop_reason="tool_use"),  # each call is priced at $0.01
        message(final(answer_text="FY25 10, FY26 20.", evidence_tool_use_ids=["t1", "t2"])),
        message(final(refused=True, answer_text="I can't forecast.")),
    ]
    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=lambda **_: replies.pop(0))))
    monkeypatch.setattr(loop, "run_tool", fake_tool)
    monkeypatch.setattr(loop, "system_prompt", lambda: "rules")
    questions = [{**question(), "id": "Q1", "question": "?"}, {**TRAP, "id": "T1", "question": "?"},
                 {**TRAP, "id": "T2", "question": "?"}]
    golden = table(["fy25", "fy26"], [10.0, 20.0])

    results = run_eval.ask_all(AnthropicProvider(client), questions, {"Q1": golden}, budget_usd=0.025)

    assert results[0]["correct"] and results[0]["tools_used"] == ["query_metric", "query_metric"]  # fy26 is only in t2
    assert results[1]["refused"] and results[1]["correct"] and results[2]["skipped"]
    assert loop.run_tool is fake_tool


# --- the question set itself -------------------------------------------------------------------------------------


def test_the_golden_set_is_well_formed():
    _, questions = run_eval.load_questions()
    patterns = [p for q in questions for p in q["compare"].get("must_not_mention", [])]
    assert len(questions) >= run_eval.MIN_QUESTIONS and all(re.compile(p) for p in patterns)


# --- raw mode (decisions D32) and the per-provider scorecard -----------------------------------------------------


def test_raw_mode_scores_a_why_question_on_its_answer_not_on_tools_it_never_had():
    why = question("multi_hop_why", "governed_metric", RUBRIC)
    text = "RL-DGP-L2-250310."
    governed = scoring.score_question(why, LOT, answer("ad_hoc_sql_verify", text=text), ["run_readonly_sql"], [], "governed")
    raw = scoring.score_question(why, LOT, answer("ad_hoc_sql_verify", text=text), ["run_readonly_sql"], [], "raw")
    assert not governed["correct"] and raw["correct"]


def test_raw_mode_expects_ad_hoc_answers_and_refused_traps():
    assert scoring.score_question(question(), ONE, answer("ad_hoc_sql_verify", data=ONE), [], [ONE], "raw")["label_correct"]
    assert scoring.score_question(TRAP, None, answer("refused"), [], [], "raw")["label_correct"]


def test_the_scorecard_reports_median_tokens_per_question_and_infrastructure_separately():
    results = [result("A", "simple_lookup", True, latency=100), result("B", "simple_lookup", True, latency=300),
               result("C", "trap", True, refused=True, latency=200)]
    results[0]["infra_retries"], results[1]["rate_limit_waits"] = 2, 1
    card = scoring.scorecard(results)
    assert (card["median_latency_ms"], card["tokens_per_question"]) == (200, {"input": 10, "output": 5})
    assert (card["infra_retries"], card["rate_limit_waits"]) == (2, 1)
    rendered = scoring.markdown(card, {"provider": "gemini", "mode": "governed", "model": "m", "effort": "e", "as_of": "d"})
    assert "gemini" in rendered and "governed" in rendered and "Infrastructure retries" in rendered


# --- ambiguous questions, the router and the threshold (decisions D39) -------------------------------------------

CLARIFY = {"type": "clarify"}


def test_an_ambiguous_question_is_correct_only_when_the_agent_asks():
    q = question(scoring.CLARIFY, "needs_clarification", CLARIFY)
    asked = scoring.score_question(q, None, answer("needs_clarification"), [], [])
    guessed = scoring.score_question(q, None, answer("governed_metric"), [], [])
    assert asked["correct"] and asked["label_correct"] and not asked["confidently_wrong"]
    assert not guessed["correct"] and guessed["confidently_wrong"]


def test_a_needless_clarification_is_wrong_but_not_confidently_wrong():
    verdict = scoring.score_question(question(), table(["v"], [1.0]), answer("needs_clarification"), [], [])
    assert (verdict["correct"], verdict["confidently_wrong"], verdict["clarified"]) == (False, False, True)


def test_raw_mode_expects_a_clarification_on_ambiguous_questions():
    q = question(scoring.CLARIFY, "needs_clarification", CLARIFY)
    assert scoring.score_question(q, None, answer("needs_clarification"), [], [], "raw")["label_correct"]


def test_scorecard_keeps_ambiguous_questions_out_of_accuracy_and_checks_the_threshold():
    results = [
        result("A", "simple_lookup", True),
        result("B", "simple_lookup", False),
        {**result("C", scoring.CLARIFY, True), "clarified": True},
        {**result("D", "simple_lookup", False), "clarified": True, "confidently_wrong": False},
        {**result("E", "trap", True, refused=True), "confidence_note": "Refused before any model call (write); ..."},
    ]
    card = scoring.scorecard(results, threshold=0.5)
    assert (card["execution_accuracy"], card["meets_threshold"], card["clarification_correctness"]) == (0.3333, False, 1.0)
    assert (card["needless_clarifications"], card["refused_before_model"]) == (["D"], ["E"])
    assert scoring.scorecard(results)["meets_threshold"] is None
    assert "Accuracy threshold 50.0% | NOT met" in scoring.markdown(card, {"model": "m", "effort": "e", "as_of": "d"})


def test_confidently_wrong_is_split_into_its_three_failures_and_trap_refusals_into_router_and_model():
    results = [
        result("A", "simple_lookup", False),
        {**result("C", scoring.CLARIFY, False), "confidently_wrong": True},
        result("T1", "trap", False),  # answered
        {**result("T2", "trap", True, refused=True), "confidence_note": "Refused before any model call (write)."},
        result("T3", "trap", True, refused=True),
    ]
    card = scoring.scorecard(results)
    assert card["confidently_wrong_by_kind"] == {"wrong_answer": ["A"], "ambiguous_answered": ["C"], "trap_answered": ["T1"]}
    assert card["trap_refusals"] == {"router": 1, "model": 1, "model_of": 2}
    shown = scoring.markdown(card, {"model": "m", "effort": "e", "as_of": "d"})
    assert "| Traps answered | 1: T1 |" in shown and "1 before any model call / 1 of 2 by the model" in shown
