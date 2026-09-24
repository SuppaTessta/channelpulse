"""Shared helpers: the day calendar, keyed RNG streams and counter-based uniforms."""

import datetime as dt

import numpy as np

# RNG stream ids. Per-day streams key SeedSequence([seed, stream, date ordinal]); hashed uniforms key
# splitmix64 over (seed, stream, *entity keys). Never renumber: every value in the data depends on them.
MASTER, DEMAND, PRODUCTION, STUFF_PICK, LOTS = 1, 2, 3, 4, 5
H_REPORT, H_WEEK, H_SHIP, H_STUFF, H_FATE, H_PAY, H_VISIT, H_PROFILE = 20, 21, 22, 23, 30, 40, 50, 51

_GOLD = np.uint64(0x9E3779B97F4A7C15)
_M1 = np.uint64(0xBF58476D1CE4E5B9)
_M2 = np.uint64(0x94D049BB133111EB)


def day_rng(seed: int, stream: int, ordinal: int) -> np.random.Generator:
    return np.random.default_rng(np.random.SeedSequence([seed, stream, ordinal]))


def _mix(z: np.ndarray) -> np.ndarray:
    z = (z ^ (z >> np.uint64(30))) * _M1
    z = (z ^ (z >> np.uint64(27))) * _M2
    return z ^ (z >> np.uint64(31))


def uniform(seed: int, stream: int, *keys) -> np.ndarray:
    """Uniforms in [0, 1) that depend only on (seed, stream, *keys); keys are int arrays that broadcast."""
    parts = np.broadcast_arrays(*[np.atleast_1d(np.asarray(k, dtype=np.int64)) for k in keys])
    h = np.full(parts[0].shape, (seed * 0x9E3779B97F4A7C15 + stream) % 2**64, dtype=np.uint64)
    for part in parts:
        h = _mix(h ^ (np.ascontiguousarray(part).view(np.uint64) * _GOLD + _GOLD))
    return (h >> np.uint64(11)).astype(np.float64) * 2.0**-53


def normal(u1: np.ndarray, u2: np.ndarray) -> np.ndarray:
    """Box-Muller standard normals from two uniform arrays."""
    return np.sqrt(-2.0 * np.log1p(-u1)) * np.cos(2.0 * np.pi * u2)


def weighted_pick(u: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Index into weights for each uniform in u."""
    cum = np.cumsum(weights)
    return np.minimum(np.searchsorted(cum, u * cum[-1], side="right"), len(weights) - 1)


def largest_remainder(total: int, weights: np.ndarray) -> np.ndarray:
    """Integer split of total proportional to weights."""
    raw = total * weights / weights.sum()
    out = np.floor(raw).astype(np.int64)
    out[np.argsort(-(raw - out), kind="stable")[: total - out.sum()]] += 1
    return out


class Calendar:
    """Day indices 0..n-1 from start (the first legacy production day) through end."""

    def __init__(self, start: dt.date, end: dt.date):
        self.start = start
        self.n = (end - start).days + 1
        days = np.arange(np.datetime64(start, "D"), np.datetime64(end, "D") + np.timedelta64(1, "D"))
        epoch_days = days.astype(np.int64)
        self.weekday = (epoch_days + 3) % 7                      # Mon = 0 (1970-01-01 was a Thursday)
        self.month = days.astype("datetime64[M]").astype(np.int64) % 12 + 1
        self.year = days.astype("datetime64[Y]").astype(np.int64) + 1970
        self.week = (epoch_days + 3) // 7                         # absolute Monday-based week number
        self.ordinal = start.toordinal() + np.arange(self.n)

    def day(self, date: dt.date) -> int:
        return (date - self.start).days

    def date(self, day: int) -> dt.date:
        return self.start + dt.timedelta(days=int(day))

    def iso(self, days) -> np.ndarray:
        return np.datetime_as_string(np.datetime64(self.start, "D") + np.asarray(days, dtype=np.int64))
