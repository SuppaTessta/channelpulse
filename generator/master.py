"""Master data: geography, catalog, plants, channel entities and the two anomaly entity picks.

Everything here is drawn from one MASTER stream in a fixed order, so it depends only on the seed and
config (never on as_of, scale or the disabled set).
"""

import math
from types import SimpleNamespace

import numpy as np

from common import MASTER, largest_remainder

CATEGORIES = ["tank", "pipe", "fitting", "sanitaryware"]
TANK, PIPE, FITTING, SANITARY = range(4)


def build_master(cfg: dict, gt: dict, cal) -> SimpleNamespace:
    rng = np.random.default_rng(np.random.SeedSequence([gt["seed"], MASTER]))
    m = SimpleNamespace()
    _geography(m, cfg, rng)
    _catalog(m, cfg, cal)
    _distributors(m, cfg, gt, cal, rng)
    _retailers(m, cfg, gt, cal, rng)
    _base_demand(m, cfg, cal, rng)
    _routing(m, cfg, gt)
    _reps(m, cfg, cal, rng)
    _installers(m, cfg, gt, rng)
    return m


def _geography(m, cfg, rng):
    geo = cfg["geography"]
    north_bengal = set(geo["north_bengal_districts"])
    names, states, regions, weights, pincodes, pin_district = [], [], [], [], [], []
    used = set()
    for state, districts in geo["districts"].items():
        for name, (prefixes, weight) in districts.items():
            prefixes = prefixes if isinstance(prefixes, list) else [prefixes]
            n = round(geo["pincodes"]["base"] + geo["pincodes"]["per_weight"] * weight)
            if len(prefixes[0]) == 4:
                n = min(n, geo["pincodes"]["max_per_4digit_prefix"] * len(prefixes))
            got = 0
            while got < n:
                prefix = prefixes[got % len(prefixes)]
                suffix = "".join(str(x) for x in rng.integers(0, 10, 6 - len(prefix)))
                code = prefix + suffix
                if code in used or int(suffix) == 0:
                    continue
                used.add(code)
                pincodes.append(code)
                pin_district.append(len(names))
                got += 1
            names.append(name)
            states.append(state)
            regions.append(geo["north_bengal_region"] if name in north_bengal else geo["regions"][state])
            weights.append(weight)
    m.district_name, m.district_state, m.district_region = names, states, regions
    m.district_weight = np.array(weights, dtype=float)
    m.pincode, m.pincode_district = np.array(pincodes), np.array(pin_district)
    m.district_pincodes = [np.flatnonzero(m.pincode_district == k) for k in range(len(names))]


def _catalog(m, cfg, cal):
    cat = cfg["catalog"]
    rows = cat["skus"]
    m.sku = [r[0] for r in rows]
    m.sku_name = [r[1] for r in rows]
    m.sku_cat = np.array([CATEGORIES.index(r[2]) for r in rows])
    m.capacity = [r[3] for r in rows]
    m.base_price = np.array([float(r[4]) for r in rows])
    m.launch_day = np.array([cal.day(r[5]) for r in rows])
    m.launched_date = [r[5] for r in rows]
    m.mix_weight = np.array([r[6] for r in rows], dtype=float)
    m.season = [r[7] for r in rows]
    lots = [cat["lot_overrides"].get(r[0], cat["lots"][r[2]]) for r in rows]
    m.pack = np.array([lot["pack"] for lot in lots])
    m.lot_packs = np.array([lot["packs"] for lot in lots], dtype=float)
    m.warranty_months = [cat["warranty_months"][r[2]] for r in rows]
    m.plants = cfg["production"]["plants"]
    m.plant_id = [p[0] for p in m.plants]
    m.lines = [(m.plant_id.index(p), no, np.array([m.sku.index(s) for s in skus])) for p, no, skus in cfg["production"]["lines"]]
    m.line_of = {(p, int(s)): i for i, (p, _, skus) in enumerate(m.lines) for s in skus}


def _unique_names(rng, n, make, taken):
    out = []
    while len(out) < n:
        name = make()
        if name not in taken:
            taken.add(name)
            out.append(name)
    return out


def _pick(rng, items):
    return items[rng.integers(len(items))]


def _distributors(m, cfg, gt, cal, rng):
    ent, geo, names = cfg["entities"]["distributors"], cfg["geography"], cfg["names"]
    states = list(geo["distributor_share"])
    per_state = largest_remainder(ent["count"], np.array([geo["distributor_share"][s] for s in states]))
    district = []
    for state, n in zip(states, per_state):
        ks = [k for k, s in enumerate(m.district_state) if s == state]
        for k, c in zip(ks, largest_remainder(int(n), m.district_weight[ks])):
            district += [k] * int(c)
    district = np.array(district)
    n = len(district)
    order = np.argsort(-(0.5 * np.log(m.district_weight[district]) + rng.normal(size=n)), kind="stable")
    tier = np.full(n, 3)
    t1, t2 = ent["tiers"][1], ent["tiers"][2]
    tier[order[:t1]], tier[order[t1:t1 + t2]] = 1, 2
    pin = np.array([rng.choice(m.district_pincodes[k]) for k in district])
    window_start = cal.day(gt["anchor"]["window_start"])
    burn_start = window_start - cfg["calendar"]["burn_in_days"]
    onboard = rng.integers(cal.day(ent["onboarded_from"]), burn_start, n)

    # The churn pick rule needs >= min_qualifying accounts; guarantee them on the first accounts of the district.
    sel = gt["anomalies"]["distributor_churn"]["selection"]
    k_sel = m.district_name.index(sel["district"])
    guaranteed = np.flatnonzero(district == k_sel)[: sel["min_qualifying_accounts"]]
    assert len(guaranteed) == sel["min_qualifying_accounts"], "too few distributors in the churn district"
    siliguri = [p for p in m.district_pincodes[k_sel] if m.pincode[p].startswith(sel["pincode_prefix"])]
    for d in guaranteed:
        tier[d], pin[d] = sel["tier"], rng.choice(siliguri)
        onboard[d] = rng.integers(cal.day(ent["onboarded_from"]), cal.day(sel["onboarded_before"]))
    others = np.setdiff1d(np.arange(n), guaranteed)
    late = rng.choice(others[tier[others] == 3], round(ent["in_window_share"] * n), replace=False)   # new accounts start small
    onboard[late] = rng.integers(*[cal.day(x) for x in ent["in_window_onboarding"]], len(late))

    m.dist_district, m.dist_tier, m.dist_pincode, m.dist_onboard = district, tier, pin, onboard
    m.dist_state = np.array([m.district_state[k] for k in district])
    m.dist_region = np.array([m.district_region[k] for k in district])
    m.dist_id = [f"D{i + 1:04d}" for i in range(n)]
    tier_scale = cfg["demand"]["tier_scale"]
    m.base_demand = np.array([tier_scale[t] for t in tier]) * np.exp(cfg["demand"]["size_sigma"] * rng.normal(size=n))
    review = cfg["channel"]["review_days"]
    m.review_period = np.array([_pick(rng, review[t]) for t in tier])
    m.review_weekday, m.review_parity = rng.integers(0, 6, n), rng.integers(0, 2, n)
    m.upload_weekday = rng.integers(0, 6, n)
    sources = cfg["channel"]["reporting"]["sources"]
    m.source_names = ["dms_api", "excel_upload", "sales_app", "backfill"]
    m.dist_source = np.array([m.source_names.index(rng.choice(list(sources[t]), p=list(sources[t].values()))) for t in tier])
    limits = cfg["channel"]["credit_limit_inr"]
    m.credit_limit = np.array([round(rng.uniform(*limits[t]), -5) for t in tier])
    m.propensity = rng.beta(2, 8, n)

    starts = cfg["entities"]["natural_attrition_starts"]
    pool = [d for d in others if tier[d] > 1 and onboard[d] < window_start and m.dist_region[d] != geo["north_bengal_region"]]
    m.attrition_start = np.full(n, 10**6)
    m.attrition_start[rng.choice(pool, len(starts), replace=False)] = [cal.day(s) for s in starts]

    pre, sur, first, suffix = names["trade_prefix"], names["surname"], names["first"], names["distributor_suffix"]
    forms = [lambda: f"{_pick(rng, pre)} {_pick(rng, suffix)}", lambda: f"{_pick(rng, sur)} {_pick(rng, suffix)}",
             lambda: f"New {_pick(rng, sur)} {_pick(rng, suffix)}", lambda: f"{_pick(rng, first)} {_pick(rng, sur)} {_pick(rng, suffix)}"]
    m.dist_name = _unique_names(rng, n, lambda: forms[rng.integers(len(forms))](), set())

    qualifying = [d for d in range(n) if tier[d] == sel["tier"] and m.dist_state[d] == sel["state"] and district[d] == k_sel
                  and m.pincode[pin[d]].startswith(sel["pincode_prefix"]) and onboard[d] < cal.day(sel["onboarded_before"])]
    assert len(qualifying) >= sel["min_qualifying_accounts"], "churn pick rule has too few qualifying accounts"
    ranked = sorted(qualifying, key=lambda d: (m.base_demand[d], m.dist_id[d]))
    m.churn = ranked[(len(ranked) - 1) // 2]
    m.propensity[m.churn] = gt["anomalies"]["distributor_churn"]["stuffing_propensity"]


def _retailers(m, cfg, gt, cal, rng):
    ent, names = cfg["entities"]["retailers"], cfg["names"]
    nd = len(m.dist_id)
    counts = np.maximum(5, rng.poisson([ent["per_distributor"][t] for t in m.dist_tier]))
    owner = np.repeat(np.arange(nd), counts)
    n = len(owner)
    district = m.dist_district[owner].copy()
    for r in np.flatnonzero(rng.random(n) >= ent["home_district_share"]):
        home = district[r]
        near = [k for k, reg in enumerate(m.district_region) if reg == m.district_region[home] and k != home]
        if near:
            district[r] = near[int(np.searchsorted(np.cumsum(m.district_weight[near]), rng.random() * m.district_weight[near].sum()))]
    m.ret_pincode = np.array([rng.choice(m.district_pincodes[k]) for k in district])
    m.ret_dist, m.ret_district = owner, district

    ws, cap = cal.day(gt["anchor"]["window_start"]),cal.day(cfg["entities"]["distributors"]["in_window_onboarding"][1])
    dist_onb = m.dist_onboard[owner]
    lo = np.maximum(dist_onb, cal.day(ent["onboarded_from"]))
    onboard = rng.integers(np.minimum(lo, ws - 1), ws, n)
    late = rng.random(n) < ent["in_window_share"]
    late_lo = np.maximum(dist_onb, ws + 14)
    onboard[late] = rng.integers(late_lo[late], np.maximum(late_lo[late] + 1, cap), late.sum())
    new_dist = dist_onb >= ws
    rank = np.arange(n) - np.searchsorted(owner, owner)
    onboard[new_dist] = np.where(rank[new_dist] < 3, dist_onb[new_dist],
                                 rng.integers(dist_onb[new_dist], np.minimum(dist_onb[new_dist] + 365, cap), new_dist.sum()))
    m.ret_onboard = onboard
    m.ret_weight = np.exp(cfg["demand"]["retailer_weight_sigma"] * rng.normal(size=n))
    m.ret_id = [f"R{i + 1:05d}" for i in range(n)]

    pre, sur, first, suffix = names["trade_prefix"], names["surname"], names["first"], names["retailer_suffix"]
    letters = "ABCDGHJKMNPRSTU"
    forms = [lambda: f"{_pick(rng, pre)} {_pick(rng, suffix)}", lambda: f"{_pick(rng, sur)} {_pick(rng, suffix)}",
             lambda: f"{_pick(rng, letters)}. {_pick(rng, letters)}. {_pick(rng, sur)} {_pick(rng, suffix)}",
             lambda: f"{_pick(rng, first)} {_pick(rng, sur)} {_pick(rng, suffix)}"]
    ret_names = _unique_names(rng, n, lambda: forms[rng.integers(len(forms))](), set(m.dist_name))
    variants = [lambda s: s, lambda s: s.replace(" & ", " and "), lambda s: s[:-1] if s.endswith("s") else s + "s",
                lambda s: s.upper(), lambda s: s.replace(".", "")]
    for r in rng.choice(n, round(ent["duplicate_name_share"] * n / 2), replace=False):
        ret_names[r] = variants[rng.integers(len(variants))](ret_names[rng.integers(n)])
    copies = np.random.default_rng(np.random.SeedSequence([gt["seed"], MASTER, 1]))   # own stream: later master draws stay put
    for r, source in zip(copies.choice(n, round(ent["exact_copy_share"] * n), replace=False), copies.integers(0, n, n)):
        ret_names[r] = ret_names[source]
    m.ret_name = ret_names


def _base_demand(m, cfg, cal, rng):
    dem = cfg["demand"]
    nd, ns = len(m.dist_id), len(m.sku)
    carried = np.zeros((nd, ns), dtype=bool)
    for c, name in enumerate(CATEGORIES):
        share = np.array([dem["carried_share"][name][t] for t in m.dist_tier])
        cols = np.flatnonzero(m.sku_cat == c)
        noisy = m.mix_weight[cols] * np.exp(0.5 * rng.normal(size=(nd, len(cols))))
        rank = np.argsort(np.argsort(-noisy, axis=1), axis=1)
        carried[:, cols] = rank < np.ceil(share * len(cols))[:, None]
    factor = np.ones((nd, ns))
    for profile, by_state in dem["state_factor"].items():
        cols = [s for s in range(ns) if m.season[s] == profile]
        for state, f in by_state.items():
            factor[np.ix_(m.dist_state == state, cols)] *= f
    units = m.base_demand[:, None] * factor * m.mix_weight[None, :] * carried
    active = m.dist_onboard <= cal.day(cfg["calendar"]["reference_date"])
    for c, name in enumerate(CATEGORIES):
        cols = m.sku_cat == c
        units[:, cols] *= dem["units_per_year"][name] / 365.25 / units[active][:, cols].sum()
    m.carried, m.units_ref = carried, units             # units/day per distributor x sku at the reference date


def _routing(m, cfg, gt):
    prod, line2 = cfg["production"], gt["calibration"]["durgapur_line2"]
    hwh, dgp, ghy = (m.plant_id.index(p) for p in ("HWH", "DGP", "GHY"))
    nd, ns = len(m.dist_id), len(m.sku)
    names = np.array([m.district_name[k] for k in m.dist_district])
    footprint = np.isin(m.dist_state, line2["footprint_states"]) & ~np.isin(names, line2["footprint_excluded_districts"])
    l2_skus = [s for s in range(ns) if (dgp, s) in m.line_of and m.sku_cat[s] == TANK]
    candidates = [d for d in range(nd) if footprint[d] and names[d] not in prod["howrah_hinterland"]]
    candidates.sort(key=lambda d: (prod["dgp_state_priority"].index(m.dist_state[d]), -m.district_weight[m.dist_district[d]], d))
    m.dgp_served = np.zeros(nd, dtype=bool)
    served_units = 0.0
    for d in candidates:
        if served_units >= prod["dgp_line2_annual_units"]:
            break
        m.dgp_served[d] = True
        served_units += m.units_ref[d, l2_skus].sum() * 365.25
    route = np.full((nd, ns, 2), -1)
    for d in range(nd):
        region = m.dist_region[d]
        for s in range(ns):
            c = m.sku_cat[s]
            if c == PIPE:
                route[d, s, 0] = dgp
            elif c == FITTING:
                route[d, s, 0] = ghy
            elif c == TANK:
                ghy_makes = (ghy, s) in m.line_of
                if region in ("Assam", "North East"):
                    route[d, s] = (ghy, hwh) if ghy_makes else (hwh, -1)
                elif region == cfg["geography"]["north_bengal_region"]:
                    route[d, s] = ((ghy, hwh) if names[d] in prod["ghy_first_districts"] else (hwh, ghy)) if ghy_makes else (hwh, -1)
                else:
                    route[d, s] = (dgp, hwh) if m.dgp_served[d] and s in l2_skus else (hwh, -1)
    assert footprint[m.dgp_served].all(), "Durgapur Line 2 must stay within its footprint"
    m.route = route


def _person(rng, names):
    return f"{_pick(rng, names['first'])} {_pick(rng, names['surname'])}"


def _reps(m, cfg, cal, rng):
    ent = cfg["entities"]["sales_reps"]
    regions = list(dict.fromkeys(m.dist_region))
    per_region = np.array([(m.dist_region == r).sum() for r in regions])
    reps = np.maximum(2, largest_remainder(ent["count"], per_region))
    m.rep_region, m.dist_rep = [], np.zeros(len(m.dist_id), dtype=int)
    for region, k in zip(regions, reps):
        members = sorted(np.flatnonzero(m.dist_region == region), key=lambda d: (m.dist_district[d], d))
        for block in np.array_split(np.array(members), k):
            m.dist_rep[block] = len(m.rep_region)
            m.rep_region.append(region)
    n = len(m.rep_region)
    m.rep_id = [f"SR{i + 1:03d}" for i in range(n)]
    m.rep_name = [_person(rng, cfg["names"]) for _ in range(n)]
    m.rep_hire = rng.integers(*[cal.day(x) for x in ent["hired"]], n)


def _installers(m, cfg, gt, rng):
    ent, decoy = cfg["entities"]["installers"], gt["anomalies"]["installer_decoy"]
    unattributed = cfg["demand"]["unattributed_share"]
    tank_units = m.units_ref[:, m.sku_cat == TANK].sum(axis=1)
    weight_sum = np.bincount(m.ret_dist, m.ret_weight)
    expected = np.zeros(len(m.district_name))
    np.add.at(expected, m.ret_district, (1 - unattributed) * tank_units[m.ret_dist] * m.ret_weight / weight_sum[m.ret_dist])
    np.add.at(expected, m.dist_district, unattributed * tank_units)
    counts = np.maximum(largest_remainder(ent["count"], expected), expected > 0)
    k_decoy = m.district_name.index(decoy["district"])
    counts[k_decoy] = max(counts[k_decoy], decoy["district_min_other_active_installers"] + 1)
    m.inst_district = np.repeat(np.arange(len(counts)), counts)
    n = len(m.inst_district)
    m.inst_id = [f"INS{i + 1:04d}" for i in range(n)]
    m.inst_name = [_person(rng, cfg["names"]) for _ in range(n)]
    m.inst_certified = rng.random(n) < ent["certified_share"]
    sigma = math.sqrt(math.log(1 + cfg["hazards"]["installer_frailty_cv"] ** 2))
    m.inst_frailty = np.exp(-sigma**2 / 2 + sigma * rng.normal(size=n))
    m.inst_weight = np.exp(ent["weight_sigma"] * rng.normal(size=n))
    m.decoy = int(np.flatnonzero(m.inst_district == k_decoy)[-1])   # the district's newest installer
    m.district_installers = [np.flatnonzero(m.inst_district == k) for k in range(len(counts))]
