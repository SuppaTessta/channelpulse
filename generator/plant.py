"""Plants: resin-lot calendars, make-to-stock batch planning and FIFO allocation from pooled plant stock."""

import math
from collections import deque

import numpy as np

from common import LOTS, PRODUCTION, day_rng
from master import CATEGORIES, TANK

REQUEST_DAYS = 28


def lot_calendars(m, cfg, gt, cal) -> tuple[list[str], list[np.ndarray]]:
    """Per line: lot index for every day. Lots are whole ISO weeks of U{3..8} weeks, named after their first Monday.

    Durgapur Line 2 is generated backward and forward from the ground-truth anchor lot, so that lot is exactly
    as written there; every other line has its own calendar with a random phase.
    """
    lo_w, hi_w = cfg["production"]["resin_lot_weeks"]
    lot = gt["anomalies"]["resin_lot"]
    first, last = cal.day(lot["first_use_date"]), cal.day(lot["last_use_date"])
    assert (cal.weekday[0] + first) % 7 == 0 and (last - first + 1) % 7 == 0 and lo_w <= (last - first + 1) // 7 <= hi_w
    names, index = [], []
    span_start, span_end = -70, cal.n + 70
    for li, (p, line_no, _) in enumerate(m.lines):
        rng = np.random.default_rng(np.random.SeedSequence([gt["seed"], LOTS, li]))
        spans = []
        if m.plant_id[p] == "DGP" and line_no == lot["line_no"]:
            spans.append((first, last))
            end = first - 1
            while end >= span_start:
                start = end - 7 * int(rng.integers(lo_w, hi_w + 1)) + 1
                spans.insert(0, (start, end))
                end = start - 1
            start = last + 1
        else:
            start = -int(cal.weekday[0]) - 7 * int(rng.integers(0, hi_w)) - 7
        while start <= span_end:
            end = start + 7 * int(rng.integers(lo_w, hi_w + 1)) - 1
            spans.append((start, end))
            start = end + 1
        day_lot = np.full(cal.n, -1)
        for start, end in spans:
            code = cal.date(start).strftime("%y%m%d")
            day_lot[max(start, 0): max(end + 1, 0)] = len(names)
            names.append(f"RL-{m.plant_id[p]}-L{line_no}-{code}")
        index.append(day_lot)
    assert f"RL-DGP-L{lot['line_no']}-{cal.date(first):%y%m%d}" == lot["resin_lot_id"]
    return names, index


class Plants:
    """Finished-goods pools per (plant, sku), pooled across lines, FIFO by production order."""

    def __init__(self, m, cfg, gt, cal):
        self.m, self.cal, self.seed = m, cal, gt["seed"]
        prod = cfg["production"]
        self.fg_days, self.qc_beta = prod["fg_target_days"], prod["qc_pass_beta"]
        self.min_batch = [prod["min_batch_units"].get(c, 1) for c in CATEGORIES]
        self.max_age = prod["max_invoice_age_days"]
        self.capacity = [prod["shift_capacity"].get(f"{m.plant_id[p]}-{no}", math.inf) for p, no, _ in m.lines]
        cv = cfg["hazards"]["batch_frailty_cv"]
        self.frailty_shape = 1 / cv**2
        self.lot_names, self.day_lot = lot_calendars(m, cfg, gt, cal)
        self.keys = sorted(m.line_of)
        self.key_index = {k: i for i, k in enumerate(self.keys)}
        self.pool = [deque() for _ in self.keys]
        self.fg = np.zeros(len(self.keys))
        self.requests = np.zeros((REQUEST_DAYS, len(self.keys)))
        self.today = np.zeros(len(self.keys))
        self.b_line, self.b_sku, self.b_shift, self.b_day, self.b_lot = [], [], [], [], []
        self.b_qty, self.b_qc, self.b_frailty, self.b_first, self.b_next = [], [], [], [], []
        self.next_serial = 0
        self.aged_units = 0

    def seed_pool(self, key: int, qty: float):
        """Pre-history stock with no batch behind it (consumed first; never serialised)."""
        qty = round(qty)
        if qty > 0:
            self.pool[key].append([-1, qty])
            self.fg[key] += qty

    def rate(self) -> np.ndarray:
        return self.requests.sum(axis=0) / REQUEST_DAYS

    def produce(self, t: int):
        rng = day_rng(self.seed, PRODUCTION, int(self.cal.ordinal[t]))
        qc = rng.beta(*self.qc_beta, size=(len(self.m.lines), 2))
        frailty = rng.gamma(self.frailty_shape, 1 / self.frailty_shape, size=(len(self.m.lines), 2))
        rate = self.rate()
        for li, (p, _, skus) in enumerate(self.m.lines):
            for shift in (0, 1):
                best, best_cover = None, math.inf
                for s in skus:
                    k = self.key_index[(p, int(s))]
                    if self.m.launch_day[s] > t or rate[k] <= 0 or self.fg[k] >= self.fg_days * rate[k]:
                        continue
                    if self.fg[k] / rate[k] < best_cover:
                        best, best_cover = int(s), self.fg[k] / rate[k]
                if best is None:
                    continue
                k = self.key_index[(p, best)]
                qty = min(math.ceil(self.fg_days * rate[k] - self.fg[k]), self.capacity[li])
                if qty < self.min_batch[self.m.sku_cat[best]]:
                    continue
                b = len(self.b_day)
                for col, value in ((self.b_line, li), (self.b_sku, best), (self.b_shift, shift), (self.b_day, t),
                                   (self.b_lot, int(self.day_lot[li][t])), (self.b_qty, qty), (self.b_qc, qc[li, shift]),
                                   (self.b_frailty, frailty[li, shift]), (self.b_next, 0)):
                    col.append(value)
                self.b_first.append(self.next_serial if self.m.sku_cat[best] == TANK else -1)
                if self.m.sku_cat[best] == TANK:
                    self.next_serial += qty
                self.pool[k].append([b, qty])
                self.fg[k] += qty

    def allocate(self, key: int, qty: float, t: int) -> list[tuple[int, int, int]]:
        """FIFO from the pool: [(batch, units, first serial or -1)]. Tank stock too old to ship in time is held back."""
        pool, out = self.pool[key], []
        self.today[key] += qty
        tank = self.m.sku_cat[self.keys[key][1]] == TANK
        while qty > 0 and pool:
            b, left = pool[0]
            if tank and b >= 0 and t - self.b_day[b] > self.max_age:
                pool.popleft()
                self.fg[key] -= left
                self.aged_units += left
                continue
            take = min(left, qty)
            first = -1
            if b >= 0 and tank:
                first = self.b_first[b] + self.b_next[b]
                self.b_next[b] += take
            if b >= 0 or not tank:
                out.append((b, take, first))
            if take == left:
                pool.popleft()
            else:
                pool[0][1] -= take
            qty -= take
            self.fg[key] -= take
        return out

    def end_day(self, t: int):
        self.requests[t % REQUEST_DAYS] = self.today
        self.today[:] = 0
