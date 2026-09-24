"""Generator invariants on a reduced-scale, in-memory simulation (no database).

As-of invariance exempts the documented time-varying attributes, which describe the state at as_of rather
than an event: warranty_claims.status (pending while recent), distributors.status (inactive once a natural
attrition completes), products.list_price_inr (the price in force at as_of), and the installations
registration fields (install_date, pincode, registered_via, installer_id) with _loaded_at, which fill in once
the registration date is visible.
"""

import datetime as dt
from collections import Counter
from functools import cache

import numpy as np
import pytest

import generate
from load import tsv

SCALE = 0.05
AS_OF = dt.date(2025, 9, 30)      # resin-lot claims, the decoy and every stuffing cycle so far are in range
CFG = generate.read_yaml(generate.HERE / "config.yaml")
GT = generate.read_yaml(generate.GROUND_TRUTH)


@cache
def run(as_of=AS_OF, disabled=frozenset()):
    return generate.build(CFG, GT, as_of, disabled, SCALE)


def rows(table: dict, mask=None) -> str:
    return tsv(table if mask is None else {k: np.asarray(v, dtype=object)[mask] for k, v in table.items()})


def dates(values) -> np.ndarray:
    return np.array([v if v is not None else "9999-12-31" for v in values], dtype="datetime64[D]").astype(np.int64)


def test_same_seed_gives_identical_tables():
    first, _ = run()
    again, _ = generate.build(CFG, GT, AS_OF, frozenset(), SCALE)
    assert first.keys() == again.keys()
    for name in first:
        assert rows(first[name]) == rows(again[name]), name


def test_nothing_is_dated_after_as_of():
    tables, _ = run()
    terms = {("primary_invoices", "due_date"), ("schemes", "end_date")}   # obligations and a window still running
    for name, cols in tables.items():
        for col, values in cols.items():
            if (col.endswith("_date") or col == "_loaded_at") and (name, col) not in terms:
                assert max((v for v in values if v is not None), default="") <= AS_OF.isoformat(), (name, col)


def test_events_visible_by_as_of_do_not_change_when_simulating_further():
    early, _ = run()
    late, _ = run(AS_OF + dt.timedelta(days=14))
    by = AS_OF.isoformat()
    visible_on = {"production_batches": "mfg_date", "serial_units": "mfg_date", "primary_invoices": "invoice_date",
                  "secondary_sales": "reported_date", "shipments": "ship_date", "collections": "payment_date",
                  "field_visits": "visit_date", "schemes": "start_date", "retailers": "onboarding_date"}
    for name, col in visible_on.items():
        assert rows(early[name]) == rows(late[name], np.asarray(late[name][col]).astype(str) <= by), name
    for name in ("geo_pincodes", "plants", "sales_reps", "installers", "opening_channel_stock"):
        assert rows(early[name]) == rows(late[name]), name

    invoices = np.isin(late["primary_invoice_lines"]["invoice_id"], early["primary_invoices"]["invoice_id"])
    assert rows(early["primary_invoice_lines"]) == rows(late["primary_invoice_lines"], invoices)
    for name, exempt, col in (("distributors", "status", "onboarding_date"), ("products", "list_price_inr", "launched_date"),
                              ("warranty_claims", "status", "claim_date")):
        keep = {k: v for k, v in late[name].items() if k != exempt}
        assert rows({k: v for k, v in early[name].items() if k != exempt}) == rows(keep, np.asarray(late[name][col]).astype(str) <= by), name

    shipped = late["shipments"]["serial"][(np.asarray(late["shipments"]["ship_date"]).astype(str) <= by)]
    assert set(early["installations"]["serial"]) == {x for x in shipped if x is not None}
    registered = np.array([x is not None for x in early["installations"]["install_date"]])
    assert rows(early["installations"], registered) == rows(late["installations"], np.isin(late["installations"]["serial"], early["installations"]["serial"][registered]))


def test_channel_stock_never_goes_negative():
    tables, _ = run()
    sec, lines, inv, opening = (tables[k] for k in ("secondary_sales", "primary_invoice_lines", "primary_invoices", "opening_channel_stock"))
    # The loader re-sends ~0.5% of weekly uploads; keep the earliest-reported copy of each record.
    key = np.array(["|".join(map(str, r)) for r in zip(sec["distributor_id"], sec["retailer_id"], sec["sku"], sec["sale_date"], sec["qty"])])
    order = np.lexsort((sec["record_id"].astype(int), dates(sec["reported_date"])))
    first = order[np.unique(key[order], return_index=True)[1]]
    invoice = dict(zip(inv["invoice_id"], zip(inv["distributor_id"], inv["invoice_date"])))
    cell = np.r_[[f"{invoice[i][0]}|{s}" for i, s in zip(lines["invoice_id"], lines["sku"])],
                 [f"{d}|{s}" for d, s in zip(sec["distributor_id"][first], sec["sku"][first])]]
    day = np.r_[dates([invoice[i][1] for i in lines["invoice_id"]]), dates(sec["sale_date"][first])]
    delta = np.r_[lines["qty"].astype(int), -sec["qty"][first].astype(int)]
    names, cell = np.unique(cell, return_inverse=True)
    stock0 = dict(zip([f"{d}|{s}" for d, s in zip(opening["distributor_id"], opening["sku"])], opening["qty"].astype(int)))
    order = np.lexsort((delta < 0, day, cell))                       # receipts before sales within a day
    cell, delta = cell[order], delta[order]
    running = np.cumsum(delta)
    starts = np.r_[0, np.flatnonzero(np.diff(cell)) + 1]
    running -= np.repeat(running[starts] - delta[starts], np.diff(np.r_[starts, len(cell)]))
    base = np.array([stock0.get(n, 0) for n in names])[cell]
    assert (running + base >= 0).all()


def test_every_tank_batch_has_one_serial_per_unit():
    tables, _ = run()
    tanks = {s for s, c in zip(tables["products"]["sku"], tables["products"]["category"]) if c == "tank"}
    serials = Counter(tables["serial_units"]["batch_id"])
    batches = tables["production_batches"]
    for batch, sku, qty in zip(batches["batch_id"], batches["sku"], batches["qty_produced"]):
        assert serials[batch] == (int(qty) if sku in tanks else 0), batch


def test_shipped_serials_belong_to_their_invoice_line_batch():
    _, r = run()
    shipped = np.flatnonzero(r.s.written & (r.s.ship <= r.ch.as_of))
    line = r.s.line[shipped] - 1
    assert (np.array(r.ch.line["batch"])[line] == r.s.batch[shipped]).all()
    assert (np.array(r.ch.inv["d"])[np.array(r.ch.line["invoice"])[line]] == r.s.ship_d[shipped]).all()


@pytest.mark.parametrize("anomaly", ["resin_lot", "installer_decoy"])
def test_claim_only_anomalies_change_nothing_but_claims(anomaly):
    full, _ = run()
    off, _ = run(disabled=frozenset({anomaly}))
    for name in full:
        if name != "warranty_claims":
            assert rows(full[name]) == rows(off[name]), name
    assert rows(full["warranty_claims"]) != rows(off["warranty_claims"])
