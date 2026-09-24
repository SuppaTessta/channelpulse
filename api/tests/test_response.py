import pytest

from app.agent.response import (
    NO_EVIDENCE_ANSWER,
    ToolCall,
    assemble,
    chart_spec,
    confidence_note,
    figures,
)

DATA = {"columns": ["month", "dso_days"], "rows": [["2026-07-01", 41.3], ["2026-08-01", 44.8]]}


def call(call_id, name="query_metric", data=DATA, sql="select month, dso_days from marts.x", error=None):
    result = None if error else {"label": "governed_metric", "sql": sql, "row_count": 2, "row_cap_hit": False,
                                 "data": data}
    return ToolCall(call_id, name, {}, result, error, 5)


def final(answer="DSO rose from 41.3 to 44.8 days.", evidence=("t1",), refused=False, chart=None):
    return {"answer_text": answer, "refused": refused, "refusal_reason": "out of scope" if refused else None,
            "evidence_tool_use_ids": list(evidence),
            "chart_hint": chart or {"type": "line", "x": "month", "y": "dso_days", "series": None}}


def test_a_governed_answer_carries_its_sql_data_chart_and_label():
    response = assemble(final(), {"t1": call("t1")}, "trace-1")
    assert response == {
        "answer_text": "DSO rose from 41.3 to 44.8 days.",
        "sql": ["select month, dso_days from marts.x"],
        "data": DATA,
        "chart_spec": {"type": "line", "x": "month", "y": "dso_days", "series": None},
        "label": "governed_metric",
        "confidence_note": "2/2 figures traced to query results.",
        "trace_id": "trace-1",
    }


def test_any_ad_hoc_evidence_makes_the_answer_ad_hoc():
    calls = {"t1": call("t1"), "t2": call("t2", name="run_readonly_sql", sql="SELECT 2")}
    response = assemble(final(evidence=("t1", "t2")), calls, "trace-1")
    assert response["label"] == "ad_hoc_sql_verify" and response["sql"] == ["select month, dso_days from marts.x", "SELECT 2"]


def test_uncited_ad_hoc_calls_do_not_change_the_label():
    calls = {"t1": call("t1"), "t2": call("t2", name="run_readonly_sql")}
    assert assemble(final(evidence=("t1",)), calls, "trace-1")["label"] == "governed_metric"


def test_the_first_cited_call_with_rows_is_the_primary_data():
    other = {"columns": ["n"], "rows": [[7]]}
    calls = {"t0": call("t0", name="explain_metric", data=None), "t1": call("t1", data=other), "t2": call("t2")}
    assert assemble(final(answer="It is 7.", evidence=("t0", "t1", "t2")), calls, "x")["data"] == other


def test_a_model_refusal_shows_no_sql_or_data():
    response = assemble(final(answer="I can only answer questions about this company's data.", refused=True),
                        {"t1": call("t1")}, "trace-1")
    assert (response["label"], response["sql"], response["data"], response["chart_spec"]) == ("refused", [], None, None)


@pytest.mark.parametrize(
    "calls",
    [{}, {"t1": call("t1", error="Rejected by the SQL validator before execution: forbidden_statement:Drop")}],
    ids=["no-calls", "only-a-failed-call"],
)
def test_an_answer_without_successful_evidence_is_refused_and_its_figures_withheld(calls):
    response = assemble(final(answer="DSO is 12 days."), calls, "trace-1")
    assert (response["label"], response["answer_text"]) == ("refused", NO_EVIDENCE_ANSWER)


def test_evidence_ids_the_conversation_never_produced_are_ignored():
    response = assemble(final(evidence=("toolu_made_up",)), {"t1": call("t1")}, "trace-1")
    assert response["label"] == "refused"


@pytest.mark.parametrize(
    ("hint", "expected"),
    [({"type": "bar", "x": "month", "y": "dso_days", "series": None}, "bar"),
     ({"type": "line", "x": "month", "y": "missing", "series": None}, None),
     ({"type": "line", "x": "dso_days", "y": "month", "series": None}, None),  # y must be numeric
     ({"type": "line", "x": "month", "y": "dso_days", "series": "nope"}, None),
     ({"type": "table", "x": None, "y": None, "series": None}, "table"),
     ({"type": "none", "x": None, "y": None, "series": None}, None)],
)
def test_the_chart_hint_is_kept_only_if_it_fits_the_columns(hint, expected):
    spec = chart_spec(hint, DATA)
    assert (spec["type"] if spec else None) == expected


def test_no_data_means_no_chart():
    assert chart_spec({"type": "bar", "x": "a", "y": "b", "series": None}, None) is None


def texts(answer: str) -> list[str]:
    return [figure.text.strip() for figure in figures(answer)]


def test_figures_are_found_with_currency_scale_and_indian_grouping():
    assert texts("Sales were ₹4.8 crore (Rs. 1,23,456 last week), up 12.5% and 3.2x the baseline; DSO 45 days.") == [
        "₹4.8 crore", "Rs. 1,23,456", "12.5%", "3.2x", "45"]


def test_years_dates_ids_ordinals_and_single_digits_are_not_figures():
    assert texts("In 2026, Q3 FY25 on 2025-09-30, DIST-0042 ranked 3rd; the top 5 on Line 2 of 500L tanks.") == []


def test_figures_trace_within_rounding_and_the_rest_are_listed():
    note = confidence_note("DSO was 41 and then 44.8 days, 60% above target.", [call("t1")], None)
    assert note == "2/3 figures traced to query results; untraced: 60%."


def test_percentages_trace_to_ratios_and_scales_to_raw_values():
    data = {"columns": ["share", "value_inr"], "rows": [[0.1251, 48_123_456.0]]}
    note = confidence_note("A 12.5% share worth ₹4.8 crore.", [call("t1", data=data)], None)
    assert note == "2/2 figures traced to query results."


def test_an_untraced_figure_is_flagged():
    assert confidence_note("DSO hit 52.3 days.", [call("t1")], None) == (
        "0/1 figure traced to query results; untraced: 52.3.")


def test_numbers_in_the_sql_and_row_counts_count_as_evidence():
    evidence = [call("t1", sql="select * from marts.x where day >= current_date - 90")]
    assert confidence_note("Over the last 90 days, 2 rows matched.", evidence, None) == (
        "1/1 figure traced to query results.")


def test_a_capped_result_is_mentioned():
    capped = call("t1")
    capped.result["row_cap_hit"] = True
    assert confidence_note("No numbers here.", [capped], capped) == (
        "No figures stated, so there was nothing to trace. Results are capped at 500 rows.")
