"""ChannelPulse synthetic data generator: a daily simulation of Gangasagar Polymers written into Postgres `raw`.

    python generator/generate.py [--as-of YYYY-MM-DD] [--schema NAME] [--disable id1,id2] [--scale F] [--dry-run]

Design overview
- Output is a pure function of (config.yaml, ground_truth.yaml, as_of, disabled set, scale). The wall clock is
  read only for generation_run.generated_at. Per-day RNG streams (SeedSequence([seed, stream, date])) draw
  fixed-length vectors over the distributor x sku grid; per-entity hashed uniforms (common.uniform) drive
  everything downstream of stock, serial fates, payments and visits. So a run to D+14 repeats every event
  of a run to D, and a hazard-only anomaly moves nothing but claims.
- Time: legacy production from ground_truth anchor.legacy_serial_start (D7) against expected demand; an
  unwritten 92-day burn-in of the full channel; then the window, window_start..as_of. Legacy tank stock
  ends the burn-in in distributor stock (legacy serials never ship in-window), which with the pipes and
  fittings still in the channel becomes raw.opening_channel_stock (D5).
- master.py: geography, catalog, entities; the churn account and decoy installer come from master-data
  rules only. plant.py: resin-lot calendars, make-to-stock batches (10-14 days of cover), FIFO pooled stock.
  channel.py: gamma-Poisson retailer purchase events capped by stock, weekly secondary uploads, periodic
  order-up-to replenishment, invoices. schemes.py: slab schemes and quarter_end_stuffing. fates.py:
  latent install, registration, installer, competing-risk failure hazards, collections, visits.
  tables.py: as-of visibility and the schema.sql columns. load.py: the single-transaction COPY load.
- Anomalies (all parameters read from ground_truth.yaml):
  resin_lot           fates.serial_fates: base_crack x multiplier in [0, 365) days from latent install
                      for serials whose batch used the anchor lot (plant.lot_calendars builds that lot).
  installer_decoy     fates.serial_fates: the decoy's hazard multiplier replaces its frailty; it takes a
                      fixed share of its district's installer installs from first_install_date.
  distributor_churn   channel.Channel: sell-out events thinned by the monthly multipliers; phase A orders
                      come from a shadow counterfactual of the account; fates.collections: late payments.
  quarter_end_stuffing schemes.SchemeProgramme: stuffers, k x trailing-90 window orders, and a drain of
                      the excess to zero at QE+72 (ground truth's theta rule at flat demand).
"""

import argparse
import datetime as dt
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import yaml

from channel import Channel
from common import Calendar
from fates import serial_fates
from master import build_master
from schemes import DRAIN_DAYS, SLAB_FACTOR, SLAB_ROUND, WINDOW_DAYS
from tables import build_tables

HERE = Path(__file__).parent
GROUND_TRUTH = HERE / "ground_truth.yaml"
ANOMALIES = ("resin_lot", "distributor_churn", "quarter_end_stuffing", "installer_decoy")


def read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def check_ground_truth(gt: dict):
    """Month offsets and the text rules the code implements must match the answer key; never re-derive."""
    y1, m1 = map(int, gt["anchor"]["month_1"].split("-"))

    def month(d: dt.date) -> int:
        return d.year * 12 + d.month - (y1 * 12 + m1) + 1

    a = gt["anomalies"]
    lot = a["resin_lot"]
    assert [month(lot["first_use_date"]), month(lot["last_use_date"])] == lot["month_offsets"]["production"]
    assert lot["last_mfg_date"] == lot["last_use_date"] - dt.timedelta(days=1)
    hz = lot["hazard"]
    assert hz["in_service_days_from"] == 0 and hz["after_window_multiplier"] == 1.0 and hz["other_modes_multiplier"] == 1.0
    churn = a["distributor_churn"]
    assert [month(churn["window"]["start"]), month(churn["window"]["end"])] == churn["month_offsets"]["window"]
    assert month(churn["window"]["end"]) + 1 == churn["month_offsets"]["hold_from"]
    stuff = a["quarter_end_stuffing"]
    assert [c["m"] for c in stuff["cycles"]] == stuff["month_offsets"]
    for c in stuff["cycles"]:
        assert month(c["start"]) == c["m"] and (c["end"] - c["start"]).days == WINDOW_DAYS - 1
        assert c["baseline"] == [c["start"] - dt.timedelta(days=90), c["start"] - dt.timedelta(days=1)]
    assert stuff["post_window"]["theta"] == f"1 - {WINDOW_DAYS}*(k - 1)/{DRAIN_DAYS}"
    rule = stuff["schemes"]["min_slab_units"]
    assert f"ceil to {SLAB_ROUND} of {SLAB_FACTOR} x median" in rule and f"x {WINDOW_DAYS})" in rule
    assert stuff["schemes"]["per_window"] == {"categories": ["tank", "pipe"], "tiers": [1, 2, 3]}
    decoy = a["installer_decoy"]
    assert month(decoy["first_install_date"]) == decoy["month_offsets"]["active_from"]
    assert decoy["hazard"]["horizon"] == "whole_service_life"


def check_calibration(cfg: dict, gt: dict):
    """config.yaml must agree with every ground_truth.calibration lever the simulator uses."""
    cal, hz, f, ch = gt["calibration"], cfg["hazards"], cfg["fates"], cfg["channel"]
    line2, lags = cal["durgapur_line2"], cal["lags"]
    others = [v for k, v in hz["after_year1_factor"].items() if k != "base_crack"]
    pairs = {
        "per_month_days": (cal["per_month_days"], hz["per_month_days"]),
        "plant_calendar": ("Mon-Sat, 2 shifts" in cal["plant_calendar"], cfg["calendar"]["plant_weekdays"] == list(range(6)) and len(cfg["calendar"]["shifts"]) == 2),
        "serialized_categories": (cal["serialized_categories"], cfg["catalog"]["serialized_categories"]),
        "durgapur_line2.annual_units": (line2["annual_units"], cfg["production"]["dgp_line2_annual_units"]),
        "durgapur_line2.footprint_states": (sorted(line2["footprint_states"]), sorted(cfg["production"]["dgp_state_priority"])),
        "durgapur_line2.footprint_excluded_districts": (sorted(line2["footprint_excluded_districts"]), sorted(cfg["geography"]["north_bengal_districts"])),
        "hazards.tank_year1_all_modes_per_month": (cal["hazards"]["tank_year1_all_modes_per_month"], round(sum(hz["year1_per_month"].values()), 10)),
        "hazards.base_crack_year1_per_month": (cal["hazards"]["base_crack_year1_per_month"], hz["year1_per_month"]["base_crack"]),
        "hazards.base_crack_after_year1_factor": (cal["hazards"]["base_crack_after_year1_factor"], hz["after_year1_factor"]["base_crack"]),
        "hazards.other_modes_after_year1_factor_max": (True, max(others) <= cal["hazards"]["other_modes_after_year1_factor_max"]),
        "hazards.claim_after_failure_days": (cal["hazards"]["claim_after_failure_days"], hz["claim_after_failure_days"]),
        "lags.mfg_to_ship_days_max": (lags["mfg_to_ship_days_max"], f["mfg_to_ship_days_max"]),
        "lags.ship_to_latent_install": ([lags["ship_to_latent_install"][k] for k in ("median_days", "sigma", "truncate_days")],
                                        [f["ship_to_install"][k] for k in ("median_days", "sigma", "cap_days")]),
        "lags.registration_probability": (lags["registration_probability"], f["registration_probability"]),
        "lags.registration_visible_after_install_days": (lags["registration_visible_after_install_days"], f["registration_visible_after_install_days"]),
        "channel.target_cover_days": (cal["channel"]["target_cover_days"], ch["target_cover_days"]),
        "channel.tier2_payment_terms_days": (cal["channel"]["tier2_payment_terms_days"], ch["payment_terms_days"][2]),
        "channel.secondary_reporting_lag": (cal["channel"]["secondary_reporting_lag"], ch["reporting"]["lag"]),
    }
    bad = [key for key, (want, got) in pairs.items() if want != got]
    if bad:
        raise SystemExit(f"config.yaml disagrees with ground_truth.calibration: {', '.join(bad)}")


def build(cfg: dict, gt: dict, as_of: dt.date, disabled=frozenset(), scale: float = 1.0):
    """Simulate and return (tables, run internals). No database access."""
    disabled = set(disabled) | {a for a in ANOMALIES if not gt["anomalies"][a]["enabled"]}
    cal = Calendar(gt["anchor"]["legacy_serial_start"], as_of)
    m = build_master(cfg, gt, cal)
    ch = Channel(m, cfg, gt, cal, cal.day(as_of), disabled, scale).run()
    s = serial_fates(ch, cfg, gt, disabled)
    return build_tables(ch, s, cfg, gt, disabled), SimpleNamespace(cal=cal, m=m, ch=ch, s=s, disabled=disabled)


def resolve_ids(gt: dict, run, may_write: bool) -> dict:
    """The two ids ground truth leaves null until master data exists: write back once, assert ever after."""
    picks = {("distributor_churn", "distributor_id"): run.m.dist_id[run.m.churn],
             ("installer_decoy", "installer_id"): run.m.inst_id[run.m.decoy]}
    text = GROUND_TRUTH.read_text(encoding="utf-8")
    for (anomaly, key), value in picks.items():
        current = gt["anomalies"][anomaly][key]
        if current is not None:
            if current != value:
                raise SystemExit(f"ground_truth {anomaly}.{key} = {current}, but the pick rule gives {value}")
            continue
        if not may_write:
            continue
        matches = list(re.finditer(rf"^(\s*{key}: )null( +)(#.*)$", text, re.MULTILINE))
        assert len(matches) == 1, f"expected exactly one '{key}: null' in ground_truth.yaml"
        mo = matches[0]                                   # keep the comment in its column
        line = mo.group(1) + value + " " * max(1, len(mo.group(2)) - len(value) + 4) + mo.group(3)
        text = text[:mo.start()] + line + text[mo.end():]
        GROUND_TRUTH.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote back ground_truth {anomaly}.{key} = {value}")
    return {key: value for (_, key), value in picks.items()}


def report(tables: dict, run, gt: dict, cfg: dict, seconds: float, size: int | None, ids: dict):
    ch, s, m, cal = run.ch, run.s, run.m, run.cal
    as_of = ch.as_of
    counts = {name: len(next(iter(cols.values()))) for name, cols in tables.items()}
    counts["generation_run"] = 1
    out = ["row counts:"] + [f"  {name:<24}{n:>10,}" for name, n in counts.items()]
    out.append(f"  {'total':<24}{sum(counts.values()):>10,}")
    out.append(f"runtime {seconds:.0f} s" + (f"; raw size {size / 2**20:.0f} MB" if size is not None else " (dry run)"))
    fy = cal.year + (cal.month >= 4)
    line_day = np.array(ch.inv["day"])[np.array(ch.line["invoice"], dtype=int)]
    paise = np.array(ch.line["qty"], dtype=np.int64) * np.array(ch.line["unit"], dtype=np.int64)
    shipped = s.written & (s.ship <= as_of)
    per_fy = {}
    for y in range(int(fy[ch.ws]), int(fy[as_of]) + 1):
        full = (fy[ch.ws:as_of + 1] == y).sum() >= 365
        per_fy[f"FY{y % 100}{'' if full else ' (partial)'}"] = (
            paise[fy[line_day] == y].sum() / 1e9, int((fy[s.ship[shipped]] == y).sum()), int((fy[s.claim[s.claimed]] == y).sum()))
    out.append("per fiscal year: revenue Rs crore / tanks shipped / claims")
    out += [f"  {k:<16}{rev:>8.1f}{tanks:>10,}{claims:>8,}" for k, (rev, tanks, claims) in per_fy.items()]
    cohort = shipped & (s.ship <= as_of - 120)
    registered = cohort & s.registered & (s.reg_day <= as_of) & (s.install - s.ship <= 90)
    out.append(f"warranty_registration_rate (90 d, shipped <= as_of - 120): {registered.sum() / cohort.sum():.1%}")
    sec = np.concatenate(ch.sec, axis=1)
    sec = sec[:, sec[6] <= as_of]
    lag = (sec[6] - sec[4])[sec[8] == 0]
    out.append("secondary reporting lag p50/p80/p95/p97: " + "/".join(f"{x:.0f}" for x in np.percentile(lag, [50, 80, 95, 97]))
               + f" d; re-sent duplicates {int(sec[8].sum()):,}; backfill rows {int((sec[7] == m.source_names.index('backfill')).sum()):,}")
    st = ch.stats
    out.append(f"stock-out share (carried cell-days at zero stock) {st['stockout_days'] / st['cell_days']:.1%}; lost demand {st['lost'].sum() / st['demand'].sum():.1%}")
    gap = (s.install - s.ship)[shipped & (s.install >= 0)]
    out.append(f"realised ship -> latent install: median {np.median(gap):.0f} d, p90 {np.percentile(gap, 90):.0f} d")
    lot_index = ch.plants.lot_names.index(gt["anomalies"]["resin_lot"]["resin_lot_id"])
    in_lot = np.array(ch.plants.b_lot)[s.batch] == lot_index
    dgp_l2 = np.array([m.plant_id[m.lines[li][0]] == "DGP" and m.lines[li][1] == 2 for li in ch.plants.b_line])[s.batch]
    months = (cal.year * 12 + cal.month)[s.claim[s.claimed & dgp_l2 & ~in_lot & (s.mode == 0)]]
    full_months = np.unique((cal.year * 12 + cal.month)[ch.ws:as_of + 1])[:-1]
    baseline = np.isin(months, full_months).sum() / len(full_months)
    mfg_fy = fy[s.mfg[dgp_l2]]
    out.append(f"power floors: Durgapur L2 base_crack baseline {baseline:.0f}/month; resin-lot units {int(in_lot.sum()):,}; "
               f"L2 units FY25 {int((mfg_fy == 2025).sum()):,}, FY26 {int((mfg_fy == 2026).sum()):,}")
    stuffing = ch.schemes.stuffers
    if stuffing:
        out.append("stuffers per cycle (share of active, mean k): " + ", ".join(
            f"{c['fq']} {len(c['stuffers']) / c['n_active']:.1%} {np.mean([x[1] for x in c['stuffers']]):.2f}" for c in stuffing))
    decoy_from = cal.day(gt["anomalies"]["installer_decoy"]["first_install_date"])
    km = m.district_name.index(gt["anomalies"]["installer_decoy"]["district"])
    app = shipped & s.registered & (s.reg_day <= as_of) & (s.via == 0) & (s.district == km) & (s.install >= decoy_from)
    n_months = (as_of - decoy_from) / cfg["hazards"]["per_month_days"]
    out.append(f"decoy: {(app & (s.installer == m.decoy)).sum() / n_months:.0f} installer-registered installs/month, "
               f"{(app & (s.installer == m.decoy)).sum() / app.sum():.1%} of the district; held-back aged tank units {int(ch.plants.aged_units):,}")
    out.append(f"resolved ids: churn distributor_id {ids['distributor_id']}, decoy installer_id {ids['installer_id']}")
    print("\n".join(out))
    return {"baseline": baseline, "lot_units": int(in_lot.sum()), "rows": sum(counts.values())}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--as-of", type=dt.date.fromisoformat)
    parser.add_argument("--schema", default="raw")
    parser.add_argument("--disable", default="", help="comma-separated anomaly ids: " + ", ".join(ANOMALIES))
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--dry-run", action="store_true", help="simulate and report without touching the database")
    args = parser.parse_args(argv)
    cfg, gt = read_yaml(HERE / "config.yaml"), read_yaml(GROUND_TRUTH)
    check_ground_truth(gt)
    check_calibration(cfg, gt)
    disabled = {x.strip() for x in args.disable.split(",") if x.strip()}
    if unknown := disabled - set(ANOMALIES):
        parser.error(f"unknown anomaly ids: {', '.join(sorted(unknown))}")
    as_of = args.as_of or gt["anchor"]["as_of"]
    started = time.perf_counter()
    tables, run = build(cfg, gt, as_of, disabled, args.scale)
    full_run = args.scale == 1.0 and not run.disabled
    ids = resolve_ids(gt, run, may_write=full_run and not args.dry_run)
    size = None
    if not args.dry_run:
        from load import load

        size = load(tables, args.schema, as_of, gt["anchor"]["anchor_date"], gt["seed"])
    result = report(tables, run, gt, cfg, time.perf_counter() - started, size, ids)
    floors = gt["calibration"]["power_floor"]
    if full_run and (result["baseline"] < floors["durgapur_base_crack_baseline_per_month_min"] or result["lot_units"] < floors["resin_lot_units_min"]):
        sys.exit("power floor breached")


if __name__ == "__main__":
    main()
