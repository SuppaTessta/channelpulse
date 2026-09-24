"""Quarter-end slab schemes: scheme rows, per-invoice tagging, and the quarter_end_stuffing behaviour.

Mechanism (ground_truth.yaml anomalies.quarter_end_stuffing): at each window start the programme fixes
min_slab_units from the literal trailing-90 primary, picks round(U(15%, 20%) x active) stuffers from the
eligible accounts weighted by their Beta(2, 8) propensity, and replaces each stuffer's scheme-category ordering
in the window by k x its trailing-90 daily average over the 15 days, in 1-2 invoices. After quarter end the
stuffer orders theta = 1 - 15(k - 1)/72 of its trailing-30 sell-out until stock is back at target.
"""

import math

import numpy as np

from common import H_STUFF, STUFF_PICK, day_rng, largest_remainder, uniform
from master import CATEGORIES, PIPE, TANK

SCHEME_CATS = (TANK, PIPE)
SLAB_FACTOR, SLAB_ROUND, WINDOW_DAYS, DRAIN_DAYS = 1.6, 10, 15, 72


class SchemeProgramme:
    def __init__(self, ch, stuffing_on: bool):
        self.ch, self.on = ch, stuffing_on
        self.gt = ch.gt["anomalies"]["quarter_end_stuffing"]
        self.cycles = {ch.cal.day(c["start"]): c for c in self.gt["cycles"]}
        self.rows, self.stuffers = [], []
        self.active = None
        self.block = np.zeros(ch.nc, dtype=bool)
        self.theta = np.zeros(ch.nc)
        self.orders, self.drain_from = {}, {}

    def begin_day(self, t: int):
        if self.active is not None and t > self.active["end"]:
            self.active = None
            self.block[:] = False
        for cells, theta in self.drain_from.pop(t, []):
            self.theta[cells] = theta
        if t in self.cycles:
            self._start(t, self.cycles[t])

    def _start(self, t: int, cyc: dict):
        ch, m = self.ch, self.ch.m
        end = ch.cal.day(cyc["end"])
        prim90 = ch.prim_ring.sum(axis=0).reshape(ch.nd, ch.ns)      # literal [start - 90, start - 1]
        daily = {c: prim90[:, m.sku_cat == c].sum(axis=1) / 90 for c in SCHEME_CATS}
        active = (m.dist_onboard <= t) & (t < m.attrition_start + ch.dem["attrition_days"])
        base = active & (ch.first_invoice <= t - 90) & (m.propensity > 0)
        discount = self.gt["schemes"]["discount_pct"]["fiscal_year_end" if cyc.get("fy_end") else "default"]
        slab = {}
        for c in SCHEME_CATS:
            for tier in (1, 2, 3):
                pool = base & (m.dist_tier == tier) & (daily[c] > 0)
                median = np.median(daily[c][pool] * WINDOW_DAYS) if pool.any() else 0   # empty only at tiny --scale
                slab[c, tier] = max(SLAB_ROUND, math.ceil(SLAB_FACTOR * median / SLAB_ROUND) * SLAB_ROUND)
                slab[c, tier, "row"] = len(self.rows)
                self.rows.append({
                    "id": f"SCH-{cyc['fq']}-{CATEGORIES[c][:3].upper()}-T{tier}",
                    "name": self.gt["schemes"]["name_pattern"].format(fq=cyc["fq"], Category=CATEGORIES[c].capitalize(), tier=tier),
                    "start": t, "end": end, "discount": discount, "slab": slab[c, tier], "category": CATEGORIES[c]})
        self.active = {"end": end, "slab": slab}
        if not self.on:
            return

        tier_slab = {c: np.array([0, *[slab[c, tier] for tier in (1, 2, 3)]])[m.dist_tier] for c in SCHEME_CATS}
        k_low, k_high = self.gt["multiplier"]["k"]["low"], self.gt["multiplier"]["k"]["high"]
        eligible_cat = {c: base & (daily[c] > 0) & (k_low * daily[c] * WINDOW_DAYS >= tier_slab[c]) for c in SCHEME_CATS}
        eligible = np.flatnonzero(eligible_cat[TANK] | eligible_cat[PIPE])
        share = self.gt["participation"]["share_of_active"]
        quarter = int(cyc["fq"][2:4]) * 10 + int(cyc["fq"][-1])
        rng = day_rng(ch.seed, STUFF_PICK, quarter)
        n = min(round(rng.uniform(share["low"], share["high"]) * active.sum()), len(eligible))
        weights = m.propensity[eligible]
        picked = np.sort(rng.choice(eligible, n, replace=False, p=weights / weights.sum()))
        window = [x for x in range(t, end + 1) if (ch.cal.weekday[0] + x) % 7 < 6]   # may run past as_of
        record = []
        for d in picked:
            k = k_low + (k_high - k_low) * uniform(ch.seed, H_STUFF, quarter, d, 0)[0]
            theta = 1 - WINDOW_DAYS * (k - 1) / DRAIN_DAYS
            cats = [c for c in SCHEME_CATS if eligible_cat[c][d]]
            for i, c in enumerate(SCHEME_CATS):
                if c not in cats:
                    continue
                cols = np.flatnonzero(m.sku_cat == c)
                total = k * daily[c][d] * WINDOW_DAYS
                pack = m.pack[cols]
                units = np.round(largest_remainder(round(total), prim90[d, cols]) / pack) * pack
                u = uniform(ch.seed, H_STUFF, quarter, d, 1 + 3 * i + np.arange(3))
                first = int(u[1] * len(window))
                plan = [(window[first], units)]
                if total >= 2 * tier_slab[c][d] and u[0] < 0.5:
                    half = np.round(units / 2 / pack) * pack
                    second = (first + 1 + int(u[2] * (len(window) - 1))) % len(window)
                    plan = [(window[first], half), (window[second], units - half)]
                for day, q in plan:
                    self.orders.setdefault(day, []).append((int(d), cols[q > 0], q[q > 0]))
                cells = d * ch.ns + cols
                self.block[cells] = True
                self.drain_from.setdefault(end + 1, []).append((cells, theta))
            record.append((int(d), k, [CATEGORIES[c] for c in cats]))
        self.stuffers.append({"fq": cyc["fq"], "n_active": int(active.sum()), "n_eligible": len(eligible), "stuffers": record})

    def adjust_orders(self, t: int, cells: np.ndarray, qty: np.ndarray, target: np.ndarray):
        """Stuffers skip normal scheme-category orders in the window, then drain at theta x trailing-30 sell-out."""
        ch = self.ch
        if self.active is not None:
            qty[cells[self.block[cells]]] = 0
        pos = np.flatnonzero((self.theta[cells] > 0) & ~self.block[cells])   # a new window replaces an old drain
        if not pos.size:
            return
        c = cells[pos]
        over = ch.stock[c] > target[pos]
        self.theta[c[~over]] = 0
        c, tgt = c[over], target[pos][over]
        want = self.theta[c] * ch.sold_ring[:, c].sum(axis=0) / 30 * (t - ch.last_order[c])
        pack = ch.pack_cell[c]
        qty[c] = np.where((want >= ch.ch["reorder_fraction"] * tgt) & (want > 0), np.ceil(want / pack) * pack, 0)

    def scheduled(self, t: int):
        return self.orders.pop(t, [])

    def split_invoice(self, d: int, t: int, lines: list):
        """One scheme per invoice: category lines at or above the tier's slab go on their own tagged invoice."""
        m, groups, rest = self.ch.m, [], lines
        if self.active is not None and m.propensity[d] > 0:     # an account with no scheme propensity never claims one
            for c in SCHEME_CATS:
                mine = [line for line in rest if m.sku_cat[line[0]] == c]
                slab = self.active["slab"]
                if mine and sum(line[2] for line in mine) >= slab[c, m.dist_tier[d]]:
                    groups.append((slab[c, m.dist_tier[d], "row"], 1 + SCHEME_CATS.index(c), mine))
                    rest = [line for line in rest if m.sku_cat[line[0]] != c]
        if rest:
            groups.append((-1, 0, rest))
        return groups

    def discount(self, row: int) -> float:
        return 0.0 if row < 0 else self.rows[row]["discount"]
