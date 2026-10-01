"""The v1 against v2 evaluator's arithmetic (decisions D46). No database."""

import datetime as dt

from detectors import evaluate

D = dt.date


def test_precision_and_recall_count_hits_against_the_truth_cells():
    out = evaluate.precision_recall({"a", "b", "c", "d"}, {"a", "b", "x"})
    assert out == {"flags": 4, "true_positives": 2, "precision": 0.5, "recall": 0.6667}
    assert evaluate.precision_recall(set(), {"a"})["precision"] is None


def test_the_first_at_risk_week_is_the_first_true_one():
    assert evaluate.first_at_risk([(D(2026, 1, 4), False), (D(2026, 1, 11), True), (D(2026, 1, 18), True)]) == D(2026, 1, 11)
    assert evaluate.first_at_risk([(D(2026, 1, 4), False)]) is None


def test_crossing_counts_a_stuffer_at_risk_inside_its_own_overhang_only():
    periods = {"S1": {(D(2025, 4, 1), D(2025, 5, 30))}, "S2": {(D(2025, 4, 1), D(2025, 5, 30))}}
    at_risk = {"S1": [D(2025, 5, 3)], "S2": [D(2025, 7, 1)], "X": [D(2025, 5, 3)]}
    assert evaluate.crossing_share(at_risk, periods) == 0.5
    assert evaluate.crossing_share(at_risk, {}) is None
