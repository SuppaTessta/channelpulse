"""Daily channel simulation: latent sell-out, secondary reporting, distributor ordering and invoicing.

Python loops over days; numpy works over the dense distributor x sku cell grid. Per-day RNG streams draw
fixed-length vectors over every cell in index order. Anything downstream of stock (reporting, ship lags,
stuffing draws) uses hashed uniforms keyed by entity, so a change in one account never reshuffles another's.
"""

from collections import deque

import numpy as np

from common import (
    DEMAND,
    H_REPORT,
    H_SHIP,
    H_WEEK,
    day_rng,
    largest_remainder,
    uniform,
    weighted_pick,
)
from master import CATEGORIES, SANITARY, TANK
from plant import Plants
from schemes import SchemeProgramme


class Channel:
    def __init__(self, m, cfg, gt, cal, as_of: int, disabled: set, scale: float):
        self.m, self.cfg, self.gt, self.cal = m, cfg, gt, cal
        self.seed, self.as_of = gt["seed"], as_of
        self.plants = Plants(m, cfg, gt, cal)
        nd, ns = len(m.dist_id), len(m.sku)
        self.nd, self.ns, self.nc = nd, ns, nd * ns
        self.ws = cal.day(gt["anchor"]["window_start"])
        self.burn = self.ws - cfg["calendar"]["burn_in_days"]
        self.ref = cal.day(cfg["calendar"]["reference_date"])
        dem, ch = cfg["demand"], cfg["channel"]
        self.dem, self.ch = dem, ch
        self.rate_ref = (m.units_ref * scale).ravel()
        self.cell_s, self.cell_d = np.tile(np.arange(ns), nd), np.repeat(np.arange(nd), ns)
        self.pack_cell = m.pack[self.cell_s].astype(float)
        tier_lot = np.array([0, *[dem["lot_tier_factor"][t] for t in (1, 2, 3)]])[m.dist_tier]
        self.lot_packs = np.maximum(1.0, m.lot_packs[self.cell_s] * tier_lot[self.cell_d])   # bigger accounts, bigger retailers
        self.lot_mean = m.pack[self.cell_s] * self.lot_packs
        self.safety_lots = np.array([ch["safety_lots"][c] for c in CATEGORIES])[m.sku_cat[self.cell_s]]
        self.cell_key = np.array([self.plants.key_index.get((int(m.route[d, s, 0]), int(s)), -1)
                                  for d, s in zip(self.cell_d, self.cell_s)])
        prof = {k: np.array(v, float) / np.mean(v) for k, v in dem["seasonality"].items()}
        prof["blend"] = (prof["tank"] + prof["agri"]) / 2
        self.season = np.ones((13, ns))
        for s, name in enumerate(m.season):
            self.season[1:, s] = prof[name]
        weekday = np.array(dem["weekday_factor"], float)
        self.weekday_factor = weekday / weekday.mean()
        self.state_names = sorted(set(m.dist_state))
        self.dist_state_idx = np.array([self.state_names.index(s) for s in m.dist_state])
        self.festival = self._festivals()
        self.price_factor = np.ones((cal.n, len(CATEGORIES)))
        for date, cats, change in cfg["prices"]["revisions"]:
            for c in cats:
                self.price_factor[cal.day(date):, CATEGORIES.index(c)] *= 1 + change
        self.margin = np.array([0, *[cfg["prices"]["tier_margin"][t] for t in (1, 2, 3)]])

        self.churn = m.churn
        churn = gt["anomalies"]["distributor_churn"]
        self.churn_on = "distributor_churn" not in disabled
        self.churn_mult = np.ones(cal.n)
        self.churn_mult[cal.day(churn["window"]["start"]):] = churn["secondary_multiplier"]["hold_after_window"]
        for month, mult in churn["secondary_multiplier"]["by_month"].items():
            y, mo = map(int, month.split("-"))
            self.churn_mult[(cal.year == y) & (cal.month == mo)] = mult
        self.phase_a = (cal.day(churn["primary"]["phase_a"]["start"]), cal.day(churn["primary"]["phase_a"]["end"]))
        self.shadow = None
        self.schemes = SchemeProgramme(self, "quarter_end_stuffing" not in disabled)

        self.ret_of = [np.flatnonzero(m.ret_dist == d) for d in range(nd)]
        self.stock = np.zeros(self.nc)
        self.fifo = {}                                   # tank cell -> deque of [first serial, units, ship day]
        self.dem_ring, self.sold_ring, self.prim_ring = np.zeros((28, self.nc)), np.zeros((30, self.nc)), np.zeros((90, self.nc))
        self.last_order = np.full(self.nc, -(10**6))
        self.first_invoice = np.full(nd, 10**6)
        self.legacy_log = [[] for _ in self.plants.keys]  # per plant-sku: [first serial, units, day] consumed pre-history
        self.prehistory, self.internal_ship, self.sales = [], [], []   # serial chunks
        self.inv = {k: [] for k in ("d", "day", "scheme", "split", "total")}
        self.line = {k: [] for k in ("invoice", "sku", "qty", "unit", "batch")}
        self.ship_chunks, self.ship_bulk = [], []        # written shipments with their first shipment_id
        self.next_shipment = 1
        self.sec = []                                    # per-day arrays of secondary records
        self.next_record = 1
        self.opening = None
        self.stats = {"demand": np.zeros(4), "lost": np.zeros(4), "cell_days": 0, "stockout_days": 0}

    def _festivals(self) -> np.ndarray:
        f, cal = self.cfg["festivals"], self.cal
        out = np.ones((cal.n, len(self.state_names)))
        dp = f["durga_puja"]
        cols = [self.state_names.index(s) for s in dp["states"] if s in self.state_names]
        for date in dp["dashami"]:
            k = cal.day(date)
            out[max(k - dp["dip_days"] + 1, 0):max(k + 1, 0), cols] *= dp["dip"]
            out[max(k + 1, 0):max(k + 1 + dp["bump_days"], 0), cols] *= dp["bump"]
        dw = f["diwali"]
        for date in dw["dates"]:
            k = cal.day(date)
            out[max(k - dw["half_width_days"], 0):max(k + dw["half_width_days"] + 1, 0)] *= dw["bump"]
        return out

    def dist_factor(self, t: int) -> np.ndarray:
        m, ramp = self.m, self.dem["onboarding_ramp"]
        age = t - m.dist_onboard
        f = np.where(age < 0, 0.0, 1.0)
        new = (m.dist_onboard >= self.ws) & (age >= 0)
        f[new] = np.minimum(1.0, ramp["start"] + (1 - ramp["start"]) * age[new] / ramp["days"])
        return f * np.clip(1 - (t - m.attrition_start) / self.dem["attrition_days"], 0, 1)

    def expected_units(self, t: int) -> np.ndarray:
        launch = self.dem["launch_ramp"]
        age = t - self.m.launch_day
        sku = np.where(age < 0, 0.0, np.minimum(1.0, launch["start"] + (1 - launch["start"]) * age / launch["days"]))
        cat, w = self.m.sku_cat, self.m.mix_weight            # a launch takes share within its category
        sku *= (np.bincount(cat, w) / np.bincount(cat, w * sku))[cat]
        sku *= self.season[self.cal.month[t]] * (1 + self.dem["yoy_growth"]) ** ((t - self.ref) / 365.25)
        return self.rate_ref * (self.dist_factor(t)[:, None] * sku[None, :]).ravel()

    def run(self):
        for t in range(self.burn):
            self._legacy_day(t)
        self._start_burn_in()
        for t in range(self.burn, self.as_of + 1):
            self._day(t)
        return self

    # --- pre-window -------------------------------------------------------------------------------------

    def _key_expected(self, t: int) -> np.ndarray:
        ok = self.cell_key >= 0
        return np.bincount(self.cell_key[ok], self.expected_units(t)[ok], minlength=len(self.plants.keys))

    def _legacy_day(self, t: int):
        """Legacy production against expected demand; consumed tanks are the pre-window installed base (D7)."""
        if t == 0:
            self.plants.requests[:] = self._key_expected(0)
            for k, units in enumerate(self._key_expected(0) * self.cfg["production"]["fg_target_days"] * 0.85):
                self.plants.seed_pool(k, units)
            self._carry = np.zeros(len(self.plants.keys))
        if self.cal.weekday[t] < 6:
            self.plants.produce(t)
            need = self._key_expected(t) * 7 / 6 + self._carry
            self._carry = need - np.floor(need)
            for k in np.flatnonzero(need >= 1):
                for b, n, first in self.plants.allocate(k, int(need[k]), t):
                    if first >= 0:
                        self.legacy_log[k].append([first, n, t])
        self.plants.end_day(t)

    def _start_burn_in(self):
        """Distributor stock at burn-in start is the most recently consumed legacy output, newest first."""
        t, m = self.burn, self.m
        exp = self.expected_units(t)
        active = np.repeat(m.dist_onboard <= t, self.ns)
        cover = self.ch["target_cover_days"] + np.repeat(m.review_period, self.ns) / 2
        self.stock = np.where(active, np.round(cover * exp), 0)
        for k, (p, s) in enumerate(self.plants.keys):
            if m.sku_cat[s] != TANK:
                continue
            log = self.legacy_log[k]
            for c in np.flatnonzero((self.cell_key == k) & (self.stock > 0)):
                need, chunks = int(self.stock[c]), deque()
                while need > 0 and log:
                    first, n, day = log[-1]
                    take = min(n, need)
                    chunks.appendleft([first + n - take, take, day])
                    self.internal_ship.append((first + n - take, take, day, self.cell_d[c]))
                    if take == n:
                        log.pop()
                    else:
                        log[-1][1] -= take
                    need -= take
                self.stock[c] -= need
                self.fifo[c] = chunks
        self.prehistory = [chunk for log in self.legacy_log for chunk in log]
        self.dem_ring[:], self.sold_ring[:], self.prim_ring[:] = exp, exp, exp
        self.first_invoice = np.where(m.dist_onboard <= t, m.dist_onboard, 10**6)
        self.plants.aged_units = 0

    def _open_window(self, t: int):
        """Legacy tank serials may not ship in-window (D7), so plant tank stock ends the burn-in in the channel."""
        exp = self.expected_units(t).reshape(self.nd, self.ns)
        today = self.plants.today.copy()
        for k, (p, s) in enumerate(self.plants.keys):
            if self.m.sku_cat[s] != TANK or self.plants.fg[k] < 1:
                continue
            recipients = np.flatnonzero((self.m.route[:, s, 0] == p) & (exp[:, s] > 0))
            for d, n in zip(recipients, largest_remainder(int(self.plants.fg[k]), exp[recipients, s])):
                if n:
                    self._receive(d * self.ns + s, self.plants.allocate(k, int(n), t - 1), t - 1, internal=True)
        self.plants.today[:] = today
        self.opening = self.stock.copy()

    # --- the day loop -----------------------------------------------------------------------------------

    def _day(self, t: int):
        if t == self.ws:
            self._open_window(t)
        self.schemes.begin_day(t)                         # reads prim_ring = [t - 90, t - 1] before today's slot is reused
        self.prim_ring[t % 90] = 0
        if self.churn_on and t == self.phase_a[0]:
            cells = self.churn * self.ns + np.arange(self.ns)
            self.shadow = {"cells": cells, "stock": self.stock[cells].copy(), "ring": self.dem_ring[:, cells].copy()}
        if self.cal.weekday[t] < 6:
            self.plants.produce(t)
            self._orders(t)
        self._sell(t)
        if self.shadow is not None and t == self.phase_a[1]:
            self.shadow = None
        self.plants.end_day(t)

    def policy(self, cells, stock, demand_sum, t: int):
        """Periodic review: order up to (cover + R) days of the trailing-28 true sell-out rate, once the gap
        reaches reorder_fraction of target, rounded up to whole packs. Retailer purchases are lumpy, so bulk
        goods add a purchase lot of safety stock and a stocked tank SKU holds at least one lot."""
        d = self.cell_d[cells]
        review = self.m.review_period[d]
        rate = demand_sum / np.clip(t - np.maximum(self.m.dist_onboard[d], self.burn - 28), 1, 28)
        target = (self.ch["target_cover_days"] + review) * rate
        lot, safety = self.lot_mean[cells] * (rate > 0), self.safety_lots[cells]
        target = np.where(safety > 0, target + safety * lot, np.maximum(target, lot))
        gap, pack = target - stock, self.pack_cell[cells]
        order = (gap >= self.ch["reorder_fraction"] * target) & (gap > 0)
        return np.where(order, np.ceil(gap / pack) * pack, 0.0), target

    def _orders(self, t: int):
        m, ns = self.m, self.ns
        reviewing = np.flatnonzero((m.dist_onboard <= t) & (m.review_weekday == self.cal.weekday[t])
                                   & ((m.review_period == 7) | (self.cal.week[t] % 2 == m.review_parity)))
        qty = np.zeros(self.nc)
        if reviewing.size:
            cells = (reviewing[:, None] * ns + np.arange(ns)).ravel()
            qty[cells], target = self.policy(cells, self.stock[cells], self.dem_ring[:, cells].sum(axis=0), t)
            self.schemes.adjust_orders(t, cells, qty, target)
            if self.shadow is not None and self.churn in reviewing:
                sh = self.shadow
                qty[sh["cells"]] = self.policy(sh["cells"], sh["stock"], sh["ring"].sum(axis=0), t)[0]
        for d, skus, units in self.schemes.scheduled(t):
            qty[d * ns + skus] += units
        cells = np.flatnonzero(qty > 0)
        for d in np.unique(self.cell_d[cells]):
            mine = cells[self.cell_d[cells] == d]
            self._invoice(int(d), self.cell_s[mine], qty[mine], t)

    def _receive(self, c: int, parts, ship_day: int, internal: bool):
        units = sum(n for _, n, _ in parts)
        self.stock[c] += units
        if self.m.sku_cat[self.cell_s[c]] == TANK:
            chunks = self.fifo.setdefault(c, deque())
            for _, n, first in parts:
                chunks.append([first, n, ship_day])
                if internal:
                    self.internal_ship.append((first, n, ship_day, self.cell_d[c]))
        return units

    def _invoice(self, d: int, skus, qtys, t: int):
        m, in_window = self.m, t >= self.ws
        ship_day = t + int(uniform(self.seed, H_SHIP, d, t)[0] * 3)
        lines = []                                        # (sku, batch, units, first serial)
        for s, q in zip(skus, qtys):
            c = d * self.ns + s
            if m.sku_cat[s] == SANITARY:
                parts = [(-1, int(q), -1)]
            else:
                parts, need = [], int(q)
                for p in m.route[d, s]:
                    if p < 0 or need <= 0:
                        break
                    got = self.plants.allocate(self.plants.key_index[(int(p), int(s))], need, t)
                    parts += got
                    need -= sum(n for _, n, _ in got)
            filled = self._receive(c, parts, ship_day, internal=not in_window)
            if filled:
                self.prim_ring[t % 90, c] += filled
                self.last_order[c] = t
                if self.shadow is not None and d == self.churn:
                    self.shadow["stock"][s] += filled
            lines += [(int(s), b, n, first) for b, n, first in parts]
        if not lines:
            return
        self.first_invoice[d] = min(self.first_invoice[d], t)
        if not in_window:
            return
        for scheme, split, group in self.schemes.split_invoice(d, t, lines):
            self._write_invoice(d, t, scheme, split, group, ship_day)

    def _write_invoice(self, d, t, scheme, split, lines, ship_day):
        m, inv = self.m, len(self.inv["d"])
        discount = self.schemes.discount(scheme)
        total, bulk = 0, False
        for s, b, n, first in lines:
            unit = round(100 * m.base_price[s] * self.price_factor[t, m.sku_cat[s]] * (1 - self.margin[m.dist_tier[d]]) * (1 - discount))
            total += unit * n
            line_id = len(self.line["invoice"]) + 1
            for key, value in (("invoice", inv), ("sku", s), ("qty", n), ("unit", unit), ("batch", b)):
                self.line[key].append(value)
            if first >= 0:
                self.ship_chunks.append((first, n, ship_day, d, line_id, self.next_shipment))
                self.next_shipment += n
            else:
                bulk = True
        if bulk:
            self.ship_bulk.append((ship_day, d, self.next_shipment))
            self.next_shipment += 1
        for key, value in (("d", d), ("day", t), ("scheme", scheme), ("split", split), ("total", total)):
            self.inv[key].append(value)

    def _sell(self, t: int):
        m, ns, cal = self.m, self.ns, self.cal
        rng = day_rng(self.seed, DEMAND, int(cal.ordinal[t]))
        festival = np.repeat(self.festival[t, self.dist_state_idx], ns)
        lam = self.expected_units(t) * self.weekday_factor[cal.weekday[t]] * festival / self.lot_mean
        shape = self.dem["event_dispersion"]
        events = rng.poisson(rng.gamma(shape, lam / shape))
        cells = np.repeat(np.arange(self.nc), events)
        s = self.cell_s[cells]
        units = m.pack[s] * (1 + rng.poisson(self.lot_packs[cells] - 1))
        u_attr, u_ret, u_thin = rng.random(len(cells)), rng.random(len(cells)), rng.random(len(cells))

        # "True sell-out" for ordering is the latent rate, not its lumpy draws: a trailing mean of realised
        # purchases jumps by a whole lot after each one and ratchets slow cells into months of stock.
        rate = lam * self.lot_mean
        if self.shadow is not None:                       # the churn account's counterfactual, before the multiplier
            sh = self.shadow
            cf = np.bincount(cells, units, minlength=self.nc)[sh["cells"]]
            sh["stock"] -= np.minimum(cf, sh["stock"])
            sh["ring"][t % 28] = rate[sh["cells"]]
        keep = np.ones(len(cells), dtype=bool)
        if self.churn_on:                                 # each purchase shrinks by the month's multiplier, in whole packs
            mine = np.flatnonzero(self.cell_d[cells] == self.churn)
            pack = m.pack[s[mine]]
            units[mine] = np.floor(units[mine] // pack * self.churn_mult[t] + u_thin[mine]).astype(np.int64) * pack
            keep[mine] = units[mine] > 0
            rate[self.churn * ns:(self.churn + 1) * ns] *= self.churn_mult[t]
        cells, units, u_attr, u_ret = cells[keep], units[keep], u_attr[keep], u_ret[keep]

        demand = np.bincount(cells, units, minlength=self.nc)
        before = np.cumsum(units) - units
        if len(cells):
            starts = np.r_[0, np.flatnonzero(np.diff(cells)) + 1]
            before -= np.repeat(before[starts], np.diff(np.r_[starts, len(cells)]))
        filled = np.clip(self.stock[cells] - before, 0, units)
        sold = np.bincount(cells, filled, minlength=self.nc)
        self.stock -= sold
        self.dem_ring[t % 28], self.sold_ring[t % 30] = rate, sold
        if t >= self.ws:
            cat = m.sku_cat[self.cell_s]
            self.stats["demand"] += np.bincount(cat, demand, minlength=4)
            self.stats["lost"] += np.bincount(cat, demand - sold, minlength=4)
            live = lam > 0
            self.stats["cell_days"] += int(live.sum())
            self.stats["stockout_days"] += int((live & (self.stock <= 0)).sum())

        ok = filled > 0
        cells, filled, u_attr, u_ret = cells[ok], filled[ok].astype(np.int64), u_attr[ok], u_ret[ok]
        retailer = np.full(len(cells), -1)
        d_ev = self.cell_d[cells]
        attributed = u_attr >= self.dem["unattributed_share"]
        for d in np.unique(d_ev[attributed]):
            idx = np.flatnonzero((d_ev == d) & attributed)
            pool = self.ret_of[d]
            weights = m.ret_weight[pool] * (m.ret_onboard[pool] <= t)
            if weights.sum() > 0:
                retailer[idx] = pool[weighted_pick(u_ret[idx], weights)]
        key, inverse = np.unique(cells * (len(m.ret_id) + 1) + retailer + 1, return_inverse=True)
        qty = np.bincount(inverse, filled).astype(np.int64)
        rec_cell, rec_ret = key // (len(m.ret_id) + 1), key % (len(m.ret_id) + 1) - 1
        rec_d, rec_s = self.cell_d[rec_cell], self.cell_s[rec_cell]
        for c, r, q in zip(rec_cell[m.sku_cat[rec_s] == TANK], rec_ret[m.sku_cat[rec_s] == TANK], qty[m.sku_cat[rec_s] == TANK]):
            chunks = self.fifo[c]
            while q > 0:
                first, n, _ = chunks[0]
                take = min(n, q)
                self.sales.append((first, take, t, self.cell_d[c], r))
                if take == n:
                    chunks.popleft()
                else:
                    chunks[0][0] += take
                    chunks[0][1] -= take
                q -= take
        if t >= self.ws and len(key):
            self._report(t, rec_d, rec_ret, rec_s, qty)

    def _report(self, t, d, r, s, qty):
        """Weekly uploads on the distributor's weekday; late weeks, skipped-then-backfilled weeks, losses, re-sends."""
        rep, cap = self.ch["reporting"], self.ch["reporting"]["lag"]["cap_days"]
        due = t + (self.m.upload_weekday[d] - self.cal.weekday[t]) % 7
        u = uniform(self.seed, H_REPORT, d, r, s, t, np.arange(2)[:, None])
        late = weighted_pick(u[1], np.array(rep["late_week_probs"]))
        skipped = uniform(self.seed, H_WEEK, d, due, 0) < rep["skipped_week_share"]
        lo, hi = rep["backfill_weeks"]
        weeks = np.where(skipped, lo + (uniform(self.seed, H_WEEK, d, due, 1) * (hi - lo + 1)).astype(int), late)
        reported = due + 7 * np.minimum(weeks, (cap - (due - t)) // 7)
        source = np.where(skipped, self.m.source_names.index("backfill"), self.m.dist_source[d])
        kept = u[0] >= rep["lag"]["permanent_loss_share"]
        resent = kept & (uniform(self.seed, H_WEEK, d, reported, 2) < rep["duplicate_upload_share"])
        lo, hi = rep["duplicate_delay_days"]
        resent_on = np.minimum(reported + lo + (uniform(self.seed, H_WEEK, d, reported, 3) * (hi - lo + 1)).astype(int), t + cap)
        ids = self.next_record + np.arange(len(d))
        self.next_record += len(d) + int(resent.sum())
        dup_ids = ids[-1] + 1 + np.arange(int(resent.sum()))
        excel = self.m.source_names.index("excel_upload")
        self.sec.append(np.stack([
            np.r_[ids[kept], dup_ids], np.r_[d[kept], d[resent]], np.r_[r[kept], r[resent]], np.r_[s[kept], s[resent]],
            np.full(int(kept.sum() + resent.sum()), t), np.r_[qty[kept], qty[resent]],
            np.r_[reported[kept], resent_on[resent]], np.r_[source[kept], np.full(int(resent.sum()), excel)],
            np.r_[np.zeros(int(kept.sum()), int), np.ones(int(resent.sum()), int)]]))
