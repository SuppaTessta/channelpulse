"""Pure-function tests for the detector statistics, on synthetic arrays (no database)."""

import math

import numpy as np
import pytest

from detectors.stats import (
    bonferroni_alpha,
    bucket_unit_days,
    cumulative_unit_days,
    cusum_first_alarm,
    expected_and_observed,
    leave_one_out,
    poisson_sf,
)


def pmf_tail(k: int, lam: float) -> float:
    """P(X >= k) by summing the pmf upward from k: no cancellation, so exact to rounding even for tiny tails."""
    term = math.exp(-lam + k * math.log(lam) - math.lgamma(k + 1))
    total, i = 0.0, k
    while term > total * 1e-18:
        total += term
        i += 1
        term *= lam / i
    return total


@pytest.mark.parametrize(("k", "lam"), [(5, 0.5), (6, 0.0029), (15, 2.8143), (20, 0.1), (40, 3.0), (200, 60.0)])
def test_poisson_tail_matches_pmf_sum_in_the_small_tail(k, lam):
    assert poisson_sf(k, lam) == pytest.approx(pmf_tail(k, lam), rel=1e-12)


def test_poisson_tail_is_accurate_near_1e_minus_12():
    p = poisson_sf(10, 0.3)
    assert 1e-13 < p < 1e-11
    assert p == pytest.approx(pmf_tail(10, 0.3), rel=1e-12)
    # P(X >= 2 | lam) = e^-lam (lam^2/2 + lam^3/6 + ...), about 5e-13 at lam = 1e-6
    assert poisson_sf(2, 1e-6) == pytest.approx(math.exp(-1e-6) * (0.5e-12 + 1e-18 / 6), rel=1e-12)


@pytest.mark.parametrize(("k", "lam"), [(10, 20.0), (10, 10.999), (10, 11.001), (3, 50.0), (100, 120.0)])
def test_poisson_tail_continued_fraction_branch(k, lam):
    cdf = sum(math.exp(-lam + i * math.log(lam) - math.lgamma(i + 1)) for i in range(k))
    assert poisson_sf(k, lam) == pytest.approx(1 - cdf, rel=1e-12)


def test_poisson_tail_known_values_and_edges():
    assert poisson_sf(1, 1.0) == pytest.approx(1 - math.exp(-1), rel=1e-14)
    assert poisson_sf(1, 1e-10) == pytest.approx(-math.expm1(-1e-10), rel=1e-12)
    assert poisson_sf(0, 3.0) == 1.0
    assert poisson_sf(5, 0.0) == 0.0


def test_cumulative_unit_days_is_sum_of_max_zero_t_minus_start():
    start = np.array([0, 3, 3, 7, 2])
    group = np.array([0, 0, 1, 1, 1])
    f = cumulative_unit_days(group, start, 2, 12)
    for g in range(2):
        for t in range(13):
            assert f[g, t] == sum(max(0, t - s) for s in start[group == g])


def test_bucket_unit_days_matches_a_per_unit_count():
    rng = np.random.default_rng(7)
    start = rng.integers(0, 200, 500)
    group = rng.integers(0, 3, 500)
    snapshot, width, n_buckets = 180, 30, 8
    got = bucket_unit_days(cumulative_unit_days(group, start, 3, 201), snapshot, n_buckets, width)
    want = np.zeros((3, n_buckets))
    for g, d in zip(group, start):
        for age in range(snapshot - d + 1):  # a unit started on day d is at ages 0..snapshot-d by then
            want[g, age // width] += 1
    np.testing.assert_array_equal(got, want)


def test_cumulative_unit_days_rejects_out_of_range_starts():
    with pytest.raises(ValueError):
        cumulative_unit_days(np.array([0]), np.array([-1]), 1, 10)


def test_expected_is_bucketed_and_drops_buckets_the_reference_never_reached():
    exposure = np.array([100.0, 50.0, 0.0])
    claims = np.array([2, 4, 0])
    ref_exposure = np.array([1000.0, 0.0, 10.0])
    ref_claims = np.array([10.0, 0.0, 1.0])
    expected, observed = expected_and_observed(exposure, claims, ref_exposure, ref_claims)
    assert expected == pytest.approx(100 * 10 / 1000)
    assert observed == 2  # bucket 1 has no reference rate, so its 4 claims are not compared


def test_expected_broadcasts_over_failure_modes():
    exposure = np.array([[[100.0, 100.0]]])  # (lot, 1, bucket)
    ref_exposure = np.array([[[1000.0, 500.0]]])
    ref_claims = np.array([[[10.0, 5.0], [0.0, 50.0]]])  # (lot, mode, bucket)
    expected, _ = expected_and_observed(exposure, np.zeros((1, 2, 2)), ref_exposure, ref_claims)
    np.testing.assert_allclose(expected, [[2.0, 10.0]])


def test_leave_one_out_removes_the_cell_from_its_stratum():
    values = np.array([[1.0, 10.0], [2.0, 20.0], [5.0, 50.0]])
    np.testing.assert_array_equal(leave_one_out(values, np.array([0, 0, 1]), 2), [[2, 20], [1, 10], [0, 0]])


def test_bonferroni_threshold():
    assert bonferroni_alpha(0.05, 680, 142) == pytest.approx(0.05 / 96_560)


def test_cusum_is_quiet_on_a_flat_series():
    assert cusum_first_alarm(np.full(36, 10.0), 17, k=1.0, h=4.0) is None


def test_cusum_alarms_at_once_on_a_jump():
    counts = np.array([10.0] * 16 + [30.0] * 5)
    assert cusum_first_alarm(counts, 17, k=1.0, h=4.0) == 17  # z = 20 / sqrt(10) - 1 = 5.3 > 4


def test_cusum_accumulates_a_moderate_shift_with_the_lagged_mean():
    # x = 16 from month 17: S climbs 0.90 a month; at month 21 mu first includes month 17, (11*10 + 16) / 12.
    counts = np.array([10.0] * 16 + [16.0] * 8)
    assert cusum_first_alarm(counts, 17, k=1.0, h=4.0) == 21


def test_cusum_ignores_months_before_monitoring_and_undefined_means():
    spike_early = np.array([10.0] * 10 + [100.0] + [10.0] * 10)
    assert cusum_first_alarm(spike_early, 17, k=1.0, h=4.0) is None
    assert cusum_first_alarm(np.zeros(30), 17, k=1.0, h=4.0) is None
