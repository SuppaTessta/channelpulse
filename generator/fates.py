"""Serial fates (latent install, installer, registration, failure, claim), collections and field visits.

Every draw here is a hashed uniform keyed by the entity (serial, invoice, distributor-visit), so fates are
as-of invariant and a hazard change for one unit moves nothing but that unit's claim.
"""

import math
from statistics import NormalDist
from types import SimpleNamespace

import numpy as np

from common import H_FATE, H_PAY, H_PROFILE, H_VISIT, normal, uniform, weighted_pick

MODES = ["base_crack", "leak", "fitting_failure", "discoloration", "other"]
VIA = ["installer_app", "qr_scan", "call_centre", "dealer_portal"]


def expand(chunks, cols: int):
    """Chunks of (first serial, units, *values) -> (serial, [value per serial...], offset within chunk)."""
    a = np.array(chunks, dtype=np.int64).reshape(-1, cols)
    first, n = a[:, 0], a[:, 1]
    offset = np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)
    return np.repeat(first, n) + offset, [np.repeat(a[:, j], n) for j in range(2, cols)], offset


def serial_fates(ch, cfg: dict, gt: dict, disabled: set) -> SimpleNamespace:
    m, p, cal, seed = ch.m, ch.plants, ch.cal, ch.seed
    f, hz = cfg["fates"], cfg["hazards"]
    tank_batches = np.flatnonzero(np.array(p.b_first) >= 0)
    n = p.next_serial
    s = SimpleNamespace(batch=np.repeat(tank_batches, np.array(p.b_qty)[tank_batches]))
    s.sku, s.mfg = np.array(p.b_sku)[s.batch], np.array(p.b_day)[s.batch]
    s.ship, s.ship_d, s.line, s.shipment_id = (np.full(n, -1) for _ in range(4))
    s.written, prehistory = np.zeros(n, dtype=bool), np.zeros(n, dtype=bool)
    if ch.internal_ship:
        idx, (day, d), _ = expand(ch.internal_ship, 4)
        s.ship[idx], s.ship_d[idx] = day, d
    if ch.ship_chunks:
        idx, (day, d, line, first_id), offset = expand(ch.ship_chunks, 6)
        s.ship[idx], s.ship_d[idx], s.line[idx], s.shipment_id[idx], s.written[idx] = day, d, line, first_id + offset, True
    if ch.prehistory:
        idx, (day,), _ = expand(ch.prehistory, 3)
        s.ship[idx], prehistory[idx] = day, True
    s.sale, s.sale_d, s.sale_r = np.full(n, -1), np.full(n, -1), np.full(n, -1)
    if ch.sales:
        idx, (day, d, r), _ = expand(ch.sales, 5)
        s.sale[idx], s.sale_d[idx], s.sale_r[idx] = day, d, r

    u = uniform(seed, H_FATE, np.arange(n), np.arange(14)[:, None])
    channel = (s.ship >= 0) & ~prehistory
    cap, mfg_cap = f["ship_to_install"]["cap_days"], f["mfg_to_ship_days_max"] + f["ship_to_install"]["cap_days"]
    delay = np.round(f["retailer_to_install"]["median_days"] * np.exp(f["retailer_to_install"]["sigma"] * normal(u[0], u[1])))
    cap_day = np.minimum(s.ship + cap, s.mfg + mfg_cap)
    natural = s.sale + delay
    # A unit not installed by the cap is installed at the cap, placed with the distributor holding it. Its fate
    # then never depends on a later sale, so a run to a later as_of cannot change anything already visible.
    direct = channel & (s.sale >= 0) & (natural <= cap_day)
    install = np.where(direct, np.maximum(natural, s.ship + 1), cap_day)
    pre = s.ship + np.clip(np.round(f["ship_to_install"]["median_days"] * np.exp(f["ship_to_install"]["sigma"] * normal(u[0], u[1]))), 1, cap)
    s.install = np.where(channel, install, np.where(prehistory, pre, -1)).astype(np.int64)
    s.direct = direct

    holder = np.where(direct, s.sale_d, s.ship_d)
    district = np.where(direct & (s.sale_r >= 0), m.ret_district[np.maximum(s.sale_r, 0)], m.dist_district[np.maximum(holder, 0)])
    s.district = np.where(channel, district, -1)
    sold = channel                                        # every channel unit has a latent install
    s.installer, s.pincode = np.full(n, -1), np.full(n, -1)
    has_installer = sold & (u[2] >= f["self_install_share"])
    decoy = gt["anomalies"]["installer_decoy"]
    decoy_from = cal.day(decoy["first_install_date"])
    share = decoy["volume"]["installer_registered_share_of_district"]
    for k in np.unique(s.district[sold]):
        idx = np.flatnonzero(sold & (s.district == k))
        pins = m.district_pincodes[k]
        s.pincode[idx] = pins[(u[7][idx] * len(pins)).astype(int)]
        idx = idx[has_installer[idx]]
        pool, weights = m.district_installers[k], m.inst_weight[m.district_installers[k]]
        if m.decoy in pool:     # the decoy starts installing on its first_install_date with a fixed district share
            before = np.where(pool == m.decoy, 0.0, weights)
            after = np.where(pool == m.decoy, share / (1 - share) * before.sum(), before)
            late = s.install[idx] >= decoy_from
            s.installer[idx[~late]] = pool[weighted_pick(u[3][idx[~late]], before)]
            s.installer[idx[late]] = pool[weighted_pick(u[3][idx[late]], after)]
        else:
            s.installer[idx] = pool[weighted_pick(u[3][idx], weights)]

    lo, hi = f["registration_visible_after_install_days"]
    s.registered = sold & (u[4] < f["registration_probability"])
    s.reg_day = s.install + lo + (u[5] * (hi - lo + 1)).astype(int)
    via_installer = np.array([f["registered_via"]["installer"].get(v, 0) for v in VIA])
    via_self = np.array([f["registered_via"]["self"].get(v, 0) for v in VIA])
    s.via = np.where(s.installer >= 0, weighted_pick(u[6], via_installer), weighted_pick(u[6], via_self))

    # Hazards from the latent install: year-1 rates, after-year-1 factors, batch and installer frailty.
    y1 = np.array([hz["year1_per_month"][mode] for mode in MODES]) / hz["per_month_days"]
    y2 = y1 * np.array([hz["after_year1_factor"][mode] for mode in MODES])
    frailty = np.array(p.b_frailty)[s.batch] * np.where(s.installer >= 0, m.inst_frailty[np.maximum(s.installer, 0)], 1.0)
    if "installer_decoy" not in disabled:
        frailty[s.installer == m.decoy] = decoy["hazard"]["all_modes_multiplier"]
    rate1, rate2 = frailty[:, None] * y1, frailty[:, None] * y2
    lot = gt["anomalies"]["resin_lot"]
    if "resin_lot" not in disabled:
        in_lot = np.array(p.b_lot)[s.batch] == p.lot_names.index(lot["resin_lot_id"])
        rate1[in_lot, MODES.index(lot["hazard"]["failure_mode"])] *= lot["hazard"]["multiplier"]
    year = lot["hazard"]["in_service_days_to"]
    a, b = rate1.sum(axis=1), rate2.sum(axis=1)
    e = -np.log1p(-u[8])
    t_fail = np.where(e < a * year, e / a, year + (e - a * year) / b)
    rates = np.where((t_fail < year)[:, None], rate1, rate2)
    cum = np.cumsum(rates, axis=1)
    s.mode = (cum < (u[9] * cum[:, -1])[:, None]).sum(axis=1)
    c_lo, c_hi = hz["claim_after_failure_days"]
    s.claim = s.install + np.floor(t_fail).astype(np.int64) + c_lo + (u[10] * (c_hi - c_lo + 1)).astype(int)
    warranty = cfg["catalog"]["warranty_months"]["tank"] * hz["per_month_days"]
    s.claimed = (s.install >= 0) & (t_fail < warranty) & (s.claim >= ch.ws) & (s.claim <= ch.as_of)
    s.u_status, s.u_cost, s.u_note = u[11], u[12], u[13]
    return s


def collections(ch, cfg: dict, gt: dict, disabled: set) -> dict:
    m, seed, col = ch.m, ch.seed, cfg["channel"]["collections"]
    d, day, split = (np.array(ch.inv[k]) for k in ("d", "day", "split"))
    total = np.array(ch.inv["total"], dtype=np.int64)
    terms = np.array([0, *[cfg["channel"]["payment_terms_days"][t] for t in (1, 2, 3)]])
    due = day + terms[m.dist_tier[d]]
    nd = len(m.dist_id)
    pu = uniform(seed, H_PROFILE, np.arange(nd), np.arange(3)[:, None])
    chronic = pu[0] < col["chronic_share"]
    profile = np.where(chronic, col["chronic_median_days"] + col["chronic_profile_sd"] * normal(pu[1], pu[2]),
                       col["late_median_days"] + col["late_profile_sd"] * normal(pu[1], pu[2]))
    u = uniform(seed, H_PAY, d, day, split, np.arange(6)[:, None])
    late = np.round(profile[d] + col["invoice_sd_days"] * normal(u[0], u[1]))
    churn = gt["anomalies"]["distributor_churn"]["collections"]
    slow = np.zeros(len(d), dtype=bool)
    if "distributor_churn" not in disabled:
        q1, q3 = churn["days_late"]["iqr"]
        sigma = (math.log(q3) - math.log(q1)) / (2 * 0.6745)
        slow = (d == m.churn) & (due >= ch.cal.day(churn["applies_to_due_date_from"]))
        # Golden-ratio quantiles: the account's few late invoices reproduce the stated median and IQR, and each
        # invoice's draw depends only on its rank among them, so it is as-of invariant.
        q = (0.5 + 0.6180339887 * np.arange(slow.sum())) % 1
        z = np.array([NormalDist().inv_cdf(x) for x in q])
        late[slow] = np.round(churn["days_late"]["median"] * np.exp(sigma * z))
    pay = np.maximum(due + late, day + 1).astype(np.int64)
    two = (u[2] < col["instalment_share"]) & ~slow          # a distressed account clears each invoice in one late payment
    g_lo, g_hi = col["instalment_gap_days"]
    first_day = np.maximum(pay - g_lo - (u[3] * (g_hi - g_lo + 1)).astype(int), day + 1)
    f_lo, f_hi = col["first_instalment_share"]
    first_amount = np.round(total * (f_lo + (f_hi - f_lo) * u[4])).astype(np.int64)
    inv = np.arange(len(d))
    rows_inv = np.r_[inv[two], inv]
    rows_day = np.r_[first_day[two], pay]
    rows_amt = np.r_[first_amount[two], np.where(two, total - first_amount, total)]
    rows_part = np.r_[np.zeros(two.sum(), int), np.ones(len(d), int)]
    keep = rows_day <= ch.as_of
    order = np.lexsort((rows_part[keep], rows_inv[keep], rows_day[keep]))
    return {"invoice": rows_inv[keep][order], "day": rows_day[keep][order], "paise": rows_amt[keep][order]}


def field_visits(ch, cfg: dict) -> dict:
    m, seed, v = ch.m, ch.seed, cfg["channel"]["visits"]
    days, dists = [], []
    for d in range(len(m.dist_id)):
        start = max(int(m.dist_onboard[d]), ch.ws)
        stop = min(ch.as_of, int(m.attrition_start[d]) + ch.dem["attrition_days"])
        cadence, jitter = v["cadence_days"][m.dist_tier[d]], v["jitter_days"]
        if stop < start:
            continue
        k = np.arange((stop - start) // (cadence - jitter) + 2)
        u = uniform(seed, H_VISIT, d, k)
        gaps = cadence - jitter + (u * (2 * jitter + 1)).astype(int)
        when = start + int(uniform(seed, H_VISIT, d, -1)[0] * cadence) + np.cumsum(gaps) - gaps[0]
        when += (ch.cal.weekday[0] + when) % 7 == 6            # Sunday visits move to Monday
        when = when[when <= stop]
        days.append(when)
        dists.append(np.full(len(when), d))
    day, d = np.concatenate(days), np.concatenate(dists)
    order = np.lexsort((d, day))
    day, d = day[order], d[order]
    u = uniform(seed, H_VISIT, d, day, np.arange(1, 4)[:, None])
    notes = np.array(v["notes"], dtype=object)[(u[2] * len(v["notes"])).astype(int)]
    return {"day": day, "d": d, "geofence": u[0] < v["geofence_share"], "note": np.where(u[1] < v["notes_share"], notes, None)}
