"""Raw tables: simulator state mapped onto generator/schema.sql columns, with as-of visibility applied.

Values are strings (None = NULL) in schema column order, so the load and the tests see the same bytes.
Documented time-varying attributes (they depend on as_of, not only on dates <= as_of): claim status,
distributor status, products.list_price_inr, installation registration fields and _loaded_at.
"""

import numpy as np

from fates import MODES, VIA, collections, field_visits
from master import CATEGORIES, TANK


def _s(values) -> np.ndarray:
    return np.asarray(values).astype(str).astype(object)


def _money(paise) -> np.ndarray:
    return np.char.mod("%.2f", np.asarray(paise, dtype=np.int64) / 100).astype(object)


def _nullable(values, mask) -> np.ndarray:
    out = _s(values)
    out[~np.asarray(mask, dtype=bool)] = None
    return out


def _pick(names, idx) -> np.ndarray:
    return np.asarray(names, dtype=object)[np.asarray(idx, dtype=np.int64)]


def build_tables(ch, s, cfg: dict, gt: dict, disabled: set) -> dict:
    m, cal, p, as_of = ch.m, ch.cal, ch.plants, ch.as_of
    iso = cal.iso
    t = {}
    tier = _s(m.dist_tier)
    t["geo_pincodes"] = {"pincode": _s(m.pincode), "district": _pick(m.district_name, m.pincode_district),
                         "state": _pick(m.district_state, m.pincode_district), "region": _pick(m.district_region, m.pincode_district)}
    t["plants"] = {col: _s([row[i] for row in m.plants]) for i, col in enumerate(("plant_id", "name", "city", "state", "plant_type"))}

    launched = np.flatnonzero(m.launch_day <= as_of)
    price_now = np.round(100 * m.base_price * ch.price_factor[as_of, m.sku_cat])
    t["products"] = {"sku": _pick(m.sku, launched), "name": _pick(m.sku_name, launched), "category": _pick(CATEGORIES, m.sku_cat[launched]),
                     "capacity_l": np.array([None if m.capacity[i] is None else str(m.capacity[i]) for i in launched], dtype=object),
                     "list_price_inr": _money(price_now[launched]), "warranty_months": _s(np.array(m.warranty_months)[launched]),
                     "launched_date": _s([m.launched_date[i].isoformat() for i in launched])}

    nb = len(p.b_day)
    b_line = np.array(p.b_line)
    batch_id = np.array([f"B{i + 1:07d}" for i in range(nb)], dtype=object)
    t["production_batches"] = {
        "batch_id": batch_id, "plant_id": _pick(m.plant_id, [m.lines[li][0] for li in b_line]), "sku": _pick(m.sku, p.b_sku),
        "line_no": _s([m.lines[li][1] for li in b_line]), "shift": _pick(["A", "B"], p.b_shift), "mfg_date": iso(p.b_day),
        "resin_lot_id": _pick(p.lot_names, p.b_lot), "qty_produced": _s(p.b_qty), "qc_pass_rate": np.char.mod("%.4f", np.array(p.b_qc)).astype(object)}
    serial_id = np.char.add("GS", np.char.zfill(np.arange(1, len(s.batch) + 1).astype(str), 8)).astype(object)
    t["serial_units"] = {"serial": serial_id, "batch_id": batch_id[s.batch], "sku": _pick(m.sku, s.sku), "mfg_date": iso(s.mfg)}

    t["sales_reps"] = {"rep_id": _s(m.rep_id), "name": _s(m.rep_name), "region": _s(m.rep_region), "hire_date": iso(m.rep_hire)}
    dd = np.flatnonzero(m.dist_onboard <= as_of)
    inactive = as_of >= m.attrition_start + ch.dem["attrition_days"]
    t["distributors"] = {
        "distributor_id": _pick(m.dist_id, dd), "name": _pick(m.dist_name, dd), "tier": tier[dd], "state": m.dist_state[dd].astype(object),
        "district": _pick(m.district_name, m.dist_district[dd]), "pincode": m.pincode[m.dist_pincode[dd]].astype(object),
        "onboarding_date": iso(m.dist_onboard[dd]), "credit_limit_inr": _money(100 * m.credit_limit[dd]),
        "sales_rep_id": _pick(m.rep_id, m.dist_rep[dd]), "status": np.where(inactive[dd], "inactive", "active").astype(object)}
    rr = np.flatnonzero(m.ret_onboard <= as_of)
    t["retailers"] = {"retailer_id": _pick(m.ret_id, rr), "distributor_id": _pick(m.dist_id, m.ret_dist[rr]), "name": _pick(m.ret_name, rr),
                      "pincode": m.pincode[m.ret_pincode[rr]].astype(object), "onboarding_date": iso(m.ret_onboard[rr])}

    oc = np.flatnonzero(ch.opening > 0) if ch.opening is not None else np.array([], dtype=int)
    t["opening_channel_stock"] = {"distributor_id": _pick(m.dist_id, ch.cell_d[oc]), "sku": _pick(m.sku, ch.cell_s[oc]),
                                  "qty": _s(ch.opening[oc].astype(np.int64)), "as_of_date": iso(np.full(len(oc), ch.ws))}
    rows = ch.schemes.rows
    t["schemes"] = {"scheme_id": _s([r["id"] for r in rows]), "name": _s([r["name"] for r in rows]), "start_date": iso([r["start"] for r in rows]),
                    "end_date": iso([r["end"] for r in rows]), "discount_pct": np.char.mod("%.4f", np.array([r["discount"] for r in rows], float)).astype(object),
                    "min_slab_units": _s([r["slab"] for r in rows]), "applies_to_category": _s([r["category"] for r in rows])}

    inv_d, inv_day, inv_scheme = (np.array(ch.inv[k], dtype=np.int64) for k in ("d", "day", "scheme"))
    terms = np.array([0, *[cfg["channel"]["payment_terms_days"][x] for x in (1, 2, 3)]])
    invoice_id = np.char.add("INV", np.char.zfill(np.arange(1, len(inv_d) + 1).astype(str), 7)).astype(object)
    scheme_ids = np.array([r["id"] for r in rows] + [None], dtype=object)
    t["primary_invoices"] = {"invoice_id": invoice_id, "distributor_id": _pick(m.dist_id, inv_d), "invoice_date": iso(inv_day),
                             "scheme_id": scheme_ids[inv_scheme], "total_amount_inr": _money(ch.inv["total"]), "due_date": iso(inv_day + terms[m.dist_tier[inv_d]])}
    line_batch = np.array(ch.line["batch"], dtype=np.int64)
    t["primary_invoice_lines"] = {"line_id": _s(np.arange(1, len(line_batch) + 1)), "invoice_id": invoice_id[np.array(ch.line["invoice"], dtype=np.int64)],
                                  "sku": _pick(m.sku, ch.line["sku"]), "qty": _s(ch.line["qty"]), "unit_price_inr": _money(ch.line["unit"]),
                                  "batch_id": np.where(line_batch >= 0, batch_id[np.maximum(line_batch, 0)], None)}

    sec = np.concatenate(ch.sec, axis=1) if ch.sec else np.zeros((9, 0), dtype=np.int64)
    sec = sec[:, sec[6] <= as_of]
    t["secondary_sales"] = {"record_id": _s(sec[0]), "distributor_id": _pick(m.dist_id, sec[1]),
                            "retailer_id": np.where(sec[2] >= 0, _pick(m.ret_id, np.maximum(sec[2], 0)), None),
                            "sku": _pick(m.sku, sec[3]), "sale_date": iso(sec[4]), "qty": _s(sec[5]), "reported_date": iso(sec[6]),
                            "source": _pick(m.source_names, sec[7])}

    shipped = np.flatnonzero(s.written & (s.ship <= as_of))
    bulk = np.array(ch.ship_bulk, dtype=np.int64).reshape(-1, 3)
    bulk = bulk[bulk[:, 0] <= as_of]
    ids = np.r_[s.shipment_id[shipped], bulk[:, 2]]
    order = np.argsort(ids, kind="stable")
    t["shipments"] = {"shipment_id": _s(ids[order]), "serial": np.r_[serial_id[shipped], np.full(len(bulk), None)][order],
                      "distributor_id": _pick(m.dist_id, np.r_[s.ship_d[shipped], bulk[:, 1]][order]), "ship_date": iso(np.r_[s.ship[shipped], bulk[:, 0]][order])}

    t["installers"] = {"installer_id": _s(m.inst_id), "name": _s(m.inst_name), "district": _pick(m.district_name, m.inst_district),
                       "certified": np.where(m.inst_certified, "t", "f").astype(object)}
    visible = s.registered[shipped] & (s.reg_day[shipped] <= as_of)
    via = s.via[shipped]
    t["installations"] = {"serial": serial_id[shipped], "pincode": np.where(visible, m.pincode[np.maximum(s.pincode[shipped], 0)], None),
                          "install_date": np.where(visible, iso(np.maximum(s.install[shipped], 0)), None),
                          "registered_via": np.where(visible, _pick(VIA, via), None),
                          "installer_id": np.where(visible & (via == 0), _pick(m.inst_id, np.maximum(s.installer[shipped], 0)), None),
                          "_loaded_at": iso(np.where(visible, s.reg_day[shipped], s.ship[shipped]))}

    claims = np.flatnonzero(s.claimed)
    claims = claims[np.lexsort((claims, s.claim[claims]))]
    cl = s.claim[claims]
    mode = s.mode[claims]
    status = np.where(cl > as_of - cfg["claims"]["pending_within_days"], "pending",
                      np.where(s.u_status[claims] < cfg["claims"]["approved_share"], "approved", "rejected"))
    lo, hi = cfg["claims"]["repair_cost_inr"]
    repair = 100 * (lo + 10 * (s.u_cost[claims] * ((hi - lo) // 10 + 1)).astype(np.int64))
    replace = np.round(100 * m.base_price[s.sku[claims]] * ch.price_factor[cl, TANK]).astype(np.int64)
    notes = [cfg["claims"]["notes"][MODES[k]] for k in mode]
    has_row = s.written[claims] & (s.ship[claims] <= as_of)
    seen = has_row & s.registered[claims] & (s.via[claims] == 0) & (s.reg_day[claims] <= cl)
    t["warranty_claims"] = {
        "claim_id": np.char.add("WC", np.char.zfill(np.arange(1, len(claims) + 1).astype(str), 7)).astype(object),
        "serial": serial_id[claims], "claim_date": iso(cl), "failure_mode": _pick(MODES, mode),
        "cost_inr": _money(np.where(mode == 0, replace, repair)), "status": status.astype(object),
        "technician_notes": np.array([n[int(u * len(n))] for n, u in zip(notes, s.u_note[claims])], dtype=object),
        "installer_id": np.where(seen, _pick(m.inst_id, np.maximum(s.installer[claims], 0)), None)}

    col = collections(ch, cfg, gt, disabled)
    t["collections"] = {"collection_id": _s(np.arange(1, len(col["day"]) + 1)), "invoice_id": invoice_id[col["invoice"]],
                        "payment_date": iso(col["day"]), "amount_inr": _money(col["paise"])}
    fv = field_visits(ch, cfg)
    t["field_visits"] = {"visit_id": _s(np.arange(1, len(fv["day"]) + 1)), "rep_id": _pick(m.rep_id, m.dist_rep[fv["d"]]),
                         "distributor_id": _pick(m.dist_id, fv["d"]), "visit_date": iso(fv["day"]),
                         "geofence_verified": np.where(fv["geofence"], "t", "f").astype(object), "notes": fv["note"]}
    return t
