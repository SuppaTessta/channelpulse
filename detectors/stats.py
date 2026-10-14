"""Pure statistics for the pre-registered detectors (detectors.yaml). No database access, so it is unit-testable."""

import math

import numpy as np


def poisson_sf(k: int, lam: float) -> float:
    """One-sided Poisson tail P(X >= k | lam), summing the pmf on whichever side of lam has no cancellation.

    k > lam sums upward from k, so the tiny tails a Bonferroni test cares about keep full relative accuracy. Otherwise
    the tail is at least about 1/2 and 1 - P(X < k) loses nothing.
    """
    if k <= 0:
        return 1.0
    if lam <= 0:
        return 0.0
    term = math.exp(-lam + k * math.log(lam) - math.lgamma(k + 1))  # P(X = k)
    if k > lam:
        total, i = 0.0, k
        while term > total * 1e-18:
            total += term
            i += 1
            term *= lam / i
        return total
    lower = 0.0
    for i in range(k, 0, -1):
        term *= i / lam  # P(X = i - 1)
        lower += term
    return 1 - lower


def bonferroni_alpha(alpha_family: float, n_entities: int, n_snapshots: int) -> float:
    return alpha_family / (n_entities * n_snapshots)


def cumulative_unit_days(group: np.ndarray, start: np.ndarray, n_groups: int, horizon: int) -> np.ndarray:
    """F[g, t] = sum over units u in group g of max(0, t - start_u), for integer days t = 0..horizon.

    Built with two cumulative sums: F(t) - F(t - 1) is the number of units started before day t. Unit-days lived at
    ages [a, b) by the end of day S are then F(S + 1 - a) - F(S + 1 - b), with no per-unit work per snapshot.
    """
    if start.size and not 0 <= start.min() <= start.max() <= horizon:
        raise ValueError("start days must lie in 0..horizon")  # a negative index would silently wrap around
    width = horizon + 1
    started = np.bincount(group * width + start, minlength=n_groups * width).reshape(n_groups, width)
    started = np.cumsum(started, axis=1, dtype=float)  # units with start <= t
    f = np.zeros_like(started)
    f[:, 1:] = np.cumsum(started[:, :-1], axis=1)
    return f


def bucket_unit_days(f: np.ndarray, snapshot: int, n_buckets: int, width: int) -> np.ndarray:
    """E[g, j] = unit-days at ages [j*width, (j+1)*width) seen by the end of day `snapshot`.

    A unit started on day d has ages 0..snapshot-d by then, i.e. snapshot-d+1 unit-days, hence the + 1.
    """
    t = np.clip(snapshot + 1 - width * np.arange(n_buckets + 1), 0, f.shape[1] - 1)
    ft = f[:, t]
    return ft[:, :-1] - ft[:, 1:]


def expected_and_observed(exposure, claims, ref_exposure, ref_claims):
    """Indirect standardisation over age buckets (the last axis); arrays broadcast.

    expected = sum_j exposure_j * ref_claims_j / ref_exposure_j and observed = sum_j claims_j, both over the buckets
    where the reference has exposure. A bucket the reference never reached has no rate, so it drops from both sides.
    """
    ok = ref_exposure > 0
    rate = np.where(ok, ref_claims / np.where(ok, ref_exposure, 1), 0.0)
    return (exposure * rate).sum(-1), np.where(ok, claims, 0).sum(-1)


def leave_one_out(values: np.ndarray, group: np.ndarray, n_groups: int) -> np.ndarray:
    """Each row's group total with the row itself removed (rows are cells, `group` is each cell's stratum)."""
    totals = np.zeros((n_groups,) + values.shape[1:])
    np.add.at(totals, group, values)
    return totals[group] - values


def cusum_first_alarm(counts, first_month: int, k: float, h: float, lag: int = 3, span: int = 12):
    """First 1-based month t >= first_month with S_t > h, or None.

    counts[i] is month i + 1. mu_t is the mean of months t-lag-span .. t-lag-1 (t-15 .. t-4 by default),
    z_t = (x_t - mu_t) / sqrt(mu_t) and S_t = max(0, S_(t-1) + z_t - k), starting from S = 0.
    A month with mu_t = 0 has no defined z_t and leaves S unchanged.
    """
    s = 0.0
    for t in range(first_month, len(counts) + 1):
        mu = float(np.mean(counts[t - lag - span - 1 : t - lag - 1]))
        if mu <= 0:
            continue
        s = max(0.0, s + (counts[t - 1] - mu) / math.sqrt(mu) - k)
        if s > h:
            return t
    return None
