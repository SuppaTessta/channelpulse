"""Detector v1 against v2 on one seed (decisions D46): stuffing precision and recall, and the churn account's flag.

    python -m detectors.evaluate [--churn-id D0084] [--out detectors/results/evaluation_<seed>.json]

Reads the database the POSTGRES_* variables point at. It needs the marts built by dbt, and the stuffing-off
counterfactual schema `raw_cf_quarter_end_stuffing` that the acceptance suite generates. Ground truth is the
acceptance suite's own rule, never a detector's: a stuffer cell is a (distributor, tank or pipe, scheme window)
whose window units are at least 1.8x the same cell in the stuffing-off run (generator/acceptance.py).
"""

import argparse
import datetime as dt
import json
import sys
from collections import defaultdict
from pathlib import Path

import psycopg
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from app.db import db_conninfo

GROUND_TRUTH = ROOT / "generator" / "ground_truth.yaml"
STUFFER_MULTIPLE = 1.8  # generator/acceptance.py stuffing_cells: raw >= 1.8x the stuffing-off run
CHURN_DEADLINE = dt.date(2026, 1, 31)  # acceptance C7 and the v2 goal: flagged before the end of January 2026
OVERHANG_DAYS = 60  # the stock overhang after a quarter-end (ground truth: elevated_through = QE+60)
STUFFING_RULES = {"v1": "is_stuffing_flag", "v2_provisional": "is_stuffing_flag_v2",
                  "v2_confirmed": "is_stuffing_confirmed_v2"}
HEALTH_RULES = {"v1": "is_at_risk", "v2": "is_at_risk_v2"}

WINDOW_UNITS = """
select i.distributor_id, p.category, sum(l.qty)
from {schema}.primary_invoices i
join {schema}.primary_invoice_lines l using (invoice_id)
join {schema}.products p using (sku)
where i.invoice_date between %s and %s and p.category in ('tank', 'pipe')
group by 1, 2"""


def precision_recall(flagged: set, truth: set) -> dict:
    hits = len(flagged & truth)
    return {"flags": len(flagged), "true_positives": hits,
            "precision": round(hits / len(flagged), 4) if flagged else None,
            "recall": round(hits / len(truth), 4) if truth else None}


def first_at_risk(weeks: list[tuple[dt.date, bool]]) -> dt.date | None:
    return next((day for day, at_risk in weeks if at_risk), None)


def crossing_share(at_risk_days: dict[str, list[dt.date]], periods: dict[str, set]) -> float | None:
    """Share of distributors at risk on some day inside one of their own periods."""
    if not periods:
        return None
    crossed = sum(any(a <= day <= b for day in at_risk_days.get(d, []) for a, b in ps) for d, ps in periods.items())
    return round(crossed / len(periods), 4)


def stuffer_truth(conn, cycles: list[dict]) -> set:
    truth = set()
    for c in cycles:
        raw, off = ({(d, cat): u for d, cat, u in conn.execute(WINDOW_UNITS.format(schema=schema), (c["start"], c["end"]))}
                    for schema in ("raw", "raw_cf_quarter_end_stuffing"))
        truth |= {(d, cat, c["start"]) for (d, cat), units in raw.items()
                  if units > 0 and units >= STUFFER_MULTIPLE * off.get((d, cat), 0)}
    return truth


def evaluate(conn, cycles: list[dict], churn_id: str) -> dict:
    truth = stuffer_truth(conn, cycles)
    starts = [c["start"] for c in cycles]
    cells = conn.execute(f"""
        select distributor_id, category, window_start_date, {', '.join(STUFFING_RULES.values())}, is_follow_through_complete
        from marts.mart_scheme_quarterly where window_start_date = any(%s)""", (starts,)).fetchall()
    stuffing = {}
    for i, (rule, _) in enumerate(STUFFING_RULES.items()):
        scope = [c for c in cells if rule != "v2_confirmed" or c[-1]]  # confirmation needs QE+60 in the data
        flagged = {c[:3] for c in scope if c[3 + i]}
        stuffing[rule] = precision_recall(flagged, truth & {c[:3] for c in scope})
    stuffing["truth_cells"] = len(truth)

    rows = conn.execute(f"""
        select distributor_id, snapshot_date, {', '.join(HEALTH_RULES.values())}
        from marts.mart_distributor_health_weekly order by distributor_id, snapshot_date""").fetchall()
    ends = {c["start"]: c["end"] for c in cycles}
    overhang = defaultdict(set)
    for d, _, start in truth:
        overhang[d].add((ends[start] + dt.timedelta(1), ends[start] + dt.timedelta(OVERHANG_DAYS)))
    health = {}
    for i, rule in enumerate(HEALTH_RULES):
        at_risk = defaultdict(list)
        for d, day, *flags in rows:
            if flags[i]:
                at_risk[d].append(day)
        first = first_at_risk([(day, flags[i]) for d, day, *flags in rows if d == churn_id])
        health[rule] = {
            "churn_first_at_risk": first.isoformat() if first else None,
            "churn_before_deadline": first is not None and first <= CHURN_DEADLINE,
            "other_distributors_ever_at_risk": len([d for d in at_risk if d != churn_id]),
            "stuffers_at_risk_during_overhang": crossing_share(at_risk, overhang),
        }
    return {"stuffing": stuffing, "distributor_health": health, "churn_id": churn_id}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--churn-id", help="the planted churn account (default: ground_truth.yaml's, for its seed)")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    gt = yaml.safe_load(GROUND_TRUTH.read_text(encoding="utf-8"))
    with psycopg.connect(db_conninfo(), autocommit=True) as conn:
        (seed,) = conn.execute("select seed from raw.generation_run").fetchone()
        churn_id = args.churn_id or (gt["anomalies"]["distributor_churn"]["distributor_id"] if seed == gt["seed"] else None)
        if churn_id is None:
            parser.error(f"seed {seed} isn't ground truth's {gt['seed']}: pass --churn-id from the generator's report")
        result = {"seed": seed, **evaluate(conn, gt["anomalies"]["quarter_end_stuffing"]["cycles"], churn_id)}
    text = json.dumps(result, indent=2, default=str)
    print(text)
    out = args.out or ROOT / "detectors" / "results" / f"evaluation_{seed}.json"
    out.write_text(text + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
