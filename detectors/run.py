"""Run the pre-registered detectors (detectors.yaml) point-in-time and publish their output.

    .venv\\Scripts\\python.exe -m detectors.run

Writes marts.mart_anomaly_flags (dropped and recreated in one transaction) and detectors/results/latest.json.
Interpretations of rules the spec leaves open are listed in detectors/README.md.
"""

import json
import os
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import psycopg
import yaml
from psycopg.types.json import Jsonb

from detectors.stats import (
    bonferroni_alpha,
    bucket_unit_days,
    cumulative_unit_days,
    cusum_first_alarm,
    expected_and_observed,
    leave_one_out,
    poisson_sf,
)

HERE = Path(__file__).resolve().parent
SPEC = yaml.safe_load((HERE / "detectors.yaml").read_text(encoding="utf-8"))
DBT_VARS = yaml.safe_load((HERE.parent / "warehouse" / "dbt_project.yml").read_text(encoding="utf-8"))["vars"]
WINDOW_START = date.fromisoformat(DBT_VARS["window_start"])  # window month 1, day 1

# Values the spec states in prose rather than as fields.
FAILURE_MODES = ("base_crack", "leak", "fitting_failure", "discoloration", "other")  # raw.warranty_claims CHECK
BUCKET_DAYS = 30
MIN_LOT_UNITS = 200
MIN_INSTALLS = 50
CUSUM_FIRST_MONTH = 17

COLUMNS = ("detector", "entity_type", "entity_id", "failure_mode", "region", "snapshot_date", "first_flag_date",
           "effect_size", "p_value", "details")


def connect() -> psycopg.Connection:
    env = os.environ.get
    return psycopg.connect(
        host=env("POSTGRES_HOST", "127.0.0.1"), port=env("POSTGRES_PORT", "5432"),
        user=env("POSTGRES_USER", "channelpulse"), password=env("POSTGRES_PASSWORD", "channelpulse"),
        dbname=env("POSTGRES_DB", "channelpulse"), connect_timeout=10, autocommit=True,
    )


def fetch(conn, sql: str, params=None) -> list[tuple]:
    return conn.execute(sql, params).fetchall()


def sundays(first: date, as_of: date) -> list[date]:
    return [first + timedelta(weeks=i) for i in range((as_of - first).days // 7 + 1)]


def year_before(d: date) -> date:
    return d.replace(year=d.year - 1, day=28 if (d.month, d.day) == (2, 29) else d.day)


def days(dates, origin: date) -> np.ndarray:
    return np.array([(d - origin).days for d in dates], dtype=np.int64)


def run_tests(observed, expected, eligible, alpha, min_claims):
    """Per-snapshot one-sided Poisson tests. Returns p (nan where not computed) and the flag matrix.

    A test needs an eligible entity and a positive expected count; p is only computed once observed >= min_claims,
    since smaller counts cannot flag, and observed never falls afterwards (claims and reference exposure accumulate).
    """
    p = np.full(observed.shape, np.nan)
    for i, j in zip(*np.nonzero(eligible & (expected > 0) & (observed >= min_claims))):
        p[i, j] = poisson_sf(int(observed[i, j]), float(expected[i, j]))
    return p, p <= alpha  # nan compares False


def flag_rows(detector, entity_type, keys, snaps, stats, flagged, details):
    """One row per flagged entity per snapshot from its first flag onward, carrying that snapshot's statistics."""
    observed, expected, p = stats
    rows, firsts = [], {}
    for e in np.nonzero(flagged.any(axis=0))[0]:
        s0 = int(np.argmax(flagged[:, e]))
        entity_id, failure_mode = keys[e]
        firsts[e] = s0
        for s in range(s0, len(snaps)):
            ratio = observed[s, e] / expected[s, e] if expected[s, e] > 0 else None
            rows.append((detector, entity_type, entity_id, failure_mode, None, snaps[s], snaps[s0], ratio,
                         None if np.isnan(p[s, e]) else float(p[s, e]),
                         {"claims": int(observed[s, e]), "expected": round(float(expected[s, e]), 4),
                          "flagged_this_snapshot": bool(flagged[s, e]), **details(s, e)}))
    return rows, firsts


def lot_scan(conn, snaps, snap_days, origin, as_of_day):
    """Resin lot x failure mode vs same plant+line lots first used in the prior 12 months, on days since ship."""
    lots = fetch(conn, """
        select resin_lot_id, min(plant_id), min(line_no), min(mfg_date), count(distinct (plant_id, line_no))
        from marts.dim_batch group by resin_lot_id order by resin_lot_id""")
    if any(r[4] > 1 for r in lots):
        raise SystemExit("a resin lot spans several plant/lines; the lot_scan peer rule is then undefined")
    lot_ids = [r[0] for r in lots]
    lot_idx = {lot: i for i, lot in enumerate(lot_ids)}
    n_lots, n_modes = len(lots), len(FAILURE_MODES)
    peers = np.array([[lots[q][1:3] == lots[p][1:3] and year_before(lots[p][3]) <= lots[q][3] < lots[p][3]
                       for q in range(n_lots)] for p in range(n_lots)], dtype=float)

    units = fetch(conn, "select resin_lot_id, ship_date from intermediate.int_serials where is_shipped")
    unit_lot = np.array([lot_idx[r[0]] for r in units])
    f = cumulative_unit_days(unit_lot, days([r[1] for r in units], origin), n_lots, as_of_day + 1)

    # Legacy units (D7) have no ship date and so no exposure clock; their claims are outside this scan.
    claims = fetch(conn, """
        select resin_lot_id, failure_mode, ship_date, claim_date from marts.fct_warranty_claims
        where ship_date is not null""")
    claim_lot = np.array([lot_idx[r[0]] for r in claims])
    claim_mode = np.array([FAILURE_MODES.index(r[1]) for r in claims])
    claim_day = days([r[3] for r in claims], origin)
    claim_bucket = (claim_day - days([r[2] for r in claims], origin)) // BUCKET_DAYS

    n_buckets = as_of_day // BUCKET_DAYS + 1
    shape = (len(snaps), n_lots, n_modes)
    observed, expected, peer_claims = np.zeros(shape), np.zeros(shape), np.zeros(shape)
    units_by, peer_days = np.zeros((len(snaps), n_lots)), np.zeros((len(snaps), n_lots))
    for s, day in enumerate(snap_days):
        exposure = bucket_unit_days(f, day, n_buckets, BUCKET_DAYS)  # (lot, bucket)
        units_by[s] = f[:, day + 1] - f[:, day]  # units shipped by the snapshot
        seen = (claim_day <= day) & (claim_bucket >= 0)
        counts = np.zeros((n_lots, n_modes, n_buckets))
        np.add.at(counts, (claim_lot[seen], claim_mode[seen], claim_bucket[seen]), 1)
        # Pool peers: their unit-days and claims per bucket, so the peer rate is claims per unit-day at that age.
        ref_exposure = peers @ exposure
        ref_claims = np.einsum("pq,qmj->pmj", peers, counts)
        expected[s], observed[s] = expected_and_observed(
            exposure[:, None, :], counts, ref_exposure[:, None, :], ref_claims)
        peer_days[s], peer_claims[s] = ref_exposure.sum(-1), ref_claims.sum(-1)

    eligible = np.repeat(units_by >= MIN_LOT_UNITS, n_modes, axis=1)  # columns are lot-major, like `keys`
    # Bonferroni counts the spec's entities at as_of (a lot can pass 200 units after the last snapshot).
    n_entities = int(((f[:, as_of_day + 1] - f[:, as_of_day]) >= MIN_LOT_UNITS).sum()) * n_modes
    alpha = bonferroni_alpha(SPEC["lot_scan"]["alpha_family"], n_entities, len(snaps))
    observed, expected, peer_claims = (a.reshape(len(snaps), -1) for a in (observed, expected, peer_claims))
    p, flagged = run_tests(observed, expected, eligible, alpha, SPEC["lot_scan"]["min_claims"])

    keys = [(lot, mode) for lot in lot_ids for mode in FAILURE_MODES]
    n_peers = peers.sum(axis=1)

    def details(s, e):
        lot = e // n_modes
        return {"units": int(units_by[s, lot]), "plant_id": lots[lot][1], "line_no": lots[lot][2],
                "peer_lots": int(n_peers[lot]), "peer_unit_days": int(peer_days[s, lot]),
                "peer_claims": int(peer_claims[s, e])}

    rows, firsts = flag_rows("lot_scan", "resin_lot", keys, snaps, (observed, expected, p), flagged, details)
    return rows, firsts, keys, {"entities": n_entities, "snapshots": len(snaps), "alpha": alpha}


def installer_scan(conn, snaps, snap_days, origin, as_of_day):
    """Installer vs leave-one-out same district+category installs, all failure modes, on days since install."""
    units = fetch(conn, """
        select s.serial, s.installer_id, s.install_district, p.category, s.install_date, i._loaded_at,
               s.plant_id, s.resin_lot_id
        from intermediate.int_serials as s
        inner join raw.installations as i on i.serial = s.serial
        inner join marts.dim_product as p on p.sku = s.sku
        where s.installer_id is not null and s.install_date is not null""")
    installer_ids = sorted({r[1] for r in units})
    inst_idx = {x: i for i, x in enumerate(installer_ids)}
    cells = sorted({(r[1], r[2], r[3]) for r in units})  # installer x district x category
    cell_idx = {c: i for i, c in enumerate(cells)}
    strata = sorted({c[1:] for c in cells})
    cell_stratum = np.array([strata.index(c[1:]) for c in cells])
    cell_installer = np.array([inst_idx[c[0]] for c in cells])

    unit_cell = np.array([cell_idx[(r[1], r[2], r[3])] for r in units])
    unit_installer = cell_installer[unit_cell]
    install_day = days([r[4] for r in units], origin)
    loaded_day = days([r[5] for r in units], origin)
    plant = np.array([r[6] for r in units])
    lot = np.array([r[7] for r in units])

    unit_of = {r[0]: i for i, r in enumerate(units)}
    claims = fetch(conn, "select serial, claim_date from marts.fct_warranty_claims where installer_id is not null")
    claims = [(unit_of[serial], claim_date) for serial, claim_date in claims if serial in unit_of]
    claim_unit = np.array([c[0] for c in claims])
    claim_day = days([c[1] for c in claims], origin)
    claim_bucket = (claim_day - install_day[claim_unit]) // BUCKET_DAYS

    n_cells, n_inst, n_buckets = len(cells), len(installer_ids), as_of_day // BUCKET_DAYS + 1
    observed, expected, installs = (np.zeros((len(snaps), n_inst)) for _ in range(3))
    for s, day in enumerate(snap_days):
        # Point-in-time: an attributed install exists at S only once its registration has loaded (D16).
        vis = loaded_day <= day
        f = cumulative_unit_days(unit_cell[vis], install_day[vis], n_cells, as_of_day + 1)
        exposure = bucket_unit_days(f, day, n_buckets, BUCKET_DAYS)
        seen = (claim_day <= day) & vis[claim_unit] & (claim_bucket >= 0)
        counts = np.zeros((n_cells, n_buckets))
        np.add.at(counts, (unit_cell[claim_unit[seen]], claim_bucket[seen]), 1)
        cell_expected, cell_observed = expected_and_observed(
            exposure, counts, leave_one_out(exposure, cell_stratum, len(strata)),
            leave_one_out(counts, cell_stratum, len(strata)))
        expected[s] = np.bincount(cell_installer, cell_expected, n_inst)
        observed[s] = np.bincount(cell_installer, cell_observed, n_inst)
        installs[s] = np.bincount(unit_installer[vis], minlength=n_inst)

    n_entities = int((np.bincount(unit_installer[loaded_day <= as_of_day], minlength=n_inst) >= MIN_INSTALLS).sum())
    alpha = bonferroni_alpha(SPEC["installer_scan"]["alpha_family"], n_entities, len(snaps))
    p, flagged = run_tests(observed, expected, installs >= MIN_INSTALLS, alpha, SPEC["installer_scan"]["min_claims"])

    districts = {i: sorted({c[1] for c in cells if c[0] == x}) for i, x in enumerate(installer_ids)}

    def details(s, e):
        mine = (unit_installer == e) & (loaded_day <= snap_days[s])
        return {"installs": int(installs[s, e]), "plants_spanned": len(set(plant[mine])),
                "resin_lots_spanned": len(set(lot[mine])), "districts": districts[e]}

    keys = [(x, None) for x in installer_ids]
    rows, firsts = flag_rows("installer_scan", "installer", keys, snaps, (observed, expected, p), flagged, details)
    return rows, firsts, keys, {"entities": n_entities, "snapshots": len(snaps), "alpha": alpha}


def month_add(d: date, months: int) -> date:
    m = d.year * 12 + d.month - 1 + months
    return date(m // 12, m % 12 + 1, 1)


def cusum_alarms(conn, as_of):
    """Case-study comparator: standardised CUSUM on raw monthly claim counts per plant x failure mode."""
    spec = SPEC["case_study_comparator"]
    last_month = month_add(as_of + timedelta(days=1), -1)  # the last month whose final day is <= as_of
    n_months = (last_month.year - WINDOW_START.year) * 12 + last_month.month - WINDOW_START.month + 1
    counts = {}
    for plant_id, mode, month, n in fetch(conn, """
            select plant_id, failure_mode, claim_month, count(*) from marts.fct_warranty_claims
            where claim_month between %s and %s group by 1, 2, 3""", (WINDOW_START, last_month)):
        i = (month.year - WINDOW_START.year) * 12 + month.month - WINDOW_START.month
        counts.setdefault((plant_id, mode), np.zeros(n_months))[i] = n
    plants = sorted({key[0] for key in counts})
    out = []
    for plant_id in plants:
        for mode in FAILURE_MODES:
            alarm = cusum_first_alarm(counts.get((plant_id, mode), np.zeros(n_months)), CUSUM_FIRST_MONTH,
                                      spec["k"], spec["h"])
            alarm_month = month_add(WINDOW_START, alarm - 1) if alarm else None
            out.append({"plant_id": plant_id, "failure_mode": mode, "first_alarm_window_month": alarm,
                        "first_alarm_month": alarm_month.isoformat()[:7] if alarm_month else None,
                        "alarm_month_last_day": (month_add(alarm_month, 1) - timedelta(days=1)).isoformat()
                        if alarm_month else None})
    return out, {"first_monitored_month": month_add(WINDOW_START, CUSUM_FIRST_MONTH - 1).isoformat()[:7],
                 "last_monitored_month": last_month.isoformat()[:7]}


def write_table(conn, rows, as_of):
    with conn.transaction():
        conn.execute("drop table if exists marts.mart_anomaly_flags")
        conn.execute("""
            create table marts.mart_anomaly_flags (
                detector        text not null,
                entity_type     text not null,
                entity_id       text not null,
                failure_mode    text,
                region          text,
                snapshot_date   date not null,
                first_flag_date date not null,
                effect_size     numeric,
                p_value         double precision,
                details         jsonb not null
            )""")
        with conn.cursor().copy(f"copy marts.mart_anomaly_flags ({', '.join(COLUMNS)}) from stdin") as copy:
            for row in rows:
                copy.write_row((*row[:-1], Jsonb(row[-1])))
        # Stuffing (detector v2, D46-D48): each flagged window is its own flag event. The provisional row is dated
        # when the window is visible. A confirmed row follows at QE+60, when the post-quarter evidence it rests on is,
        # so an as-of read never sees later data. concentration_ratio stays out: it uses later quarters.
        conn.execute("""
            insert into marts.mart_anomaly_flags
            select 'stuffing', 'distributor', distributor_id, null, region, f.snapshot_date,
                   least(window_end_date, %(as_of)s), rate_ratio, null,
                   jsonb_build_object('fiscal_quarter', fiscal_quarter_label, 'category', category,
                                      'window_start_date', window_start_date, 'window_end_date', window_end_date,
                                      'is_window_complete', is_window_complete, 'window_units', window_units,
                                      'baseline_units', baseline_units, 'scheme_invoices', scheme_invoices,
                                      'status', f.status, 'rule_version', 2)
                   || case when f.status = 'confirmed' then jsonb_build_object(
                          'post_rate_ratio', post_rate_ratio, 'dos_excess_60d', dos_excess_60d) else '{}' end
            from marts.mart_scheme_quarterly
            cross join lateral (values (least(window_end_date, %(as_of)s), 'provisional'),
                                       (window_end_date + 60, 'confirmed')) as f (snapshot_date, status)
            where is_stuffing_flag and (f.status = 'provisional' or is_stuffing_confirmed)""", {"as_of": as_of})
        # Health: consecutive at-risk weeks form a run (gaps and islands); first_flag_date is the run's first week.
        conn.execute("""
            insert into marts.mart_anomaly_flags
            select 'distributor_health', 'distributor', distributor_id, null, region, snapshot_date,
                   min(snapshot_date) over (partition by distributor_id, run), health_score, null,
                   jsonb_build_object('week_start', week_start,
                       'score_secondary_trend', score_secondary_trend,
                       'score_primary_secondary_gap', score_primary_secondary_gap,
                       'score_days_of_stock_dev', score_days_of_stock_dev,
                       'score_dso_trend', score_dso_trend, 'score_visit_recency', score_visit_recency,
                       'secondary_trend_ratio', secondary_trend_ratio,
                       'primary_secondary_ratio', primary_secondary_ratio,
                       'days_of_stock_vs_median', days_of_stock_vs_median, 'dso_vs_median', dso_vs_median,
                       'days_since_verified_visit', days_since_verified_visit, 'rule_version', 2)
            from (
                select *,
                    snapshot_date - 7 * (row_number() over (partition by distributor_id order by snapshot_date))::int
                        as run
                from marts.mart_distributor_health_weekly where is_at_risk
            ) as h""")
        conn.execute("alter table marts.mart_anomaly_flags enable row level security")
        conn.execute("""
            create policy region_claim on marts.mart_anomaly_flags for select using (
                region is null or coalesce(nullif(current_setting('app.region', true), ''), 'ALL') in ('ALL', region)
            )""")
        if fetch(conn, "select 1 from pg_roles where rolname = 'channelpulse_agent'"):
            conn.execute("grant select on marts.mart_anomaly_flags to channelpulse_agent")


def _round(value):
    return None if value is None else round(value, 3)


def scan_summary(rows, firsts, keys, snaps):
    by_key = {(r[2], r[3], r[5]): r for r in rows}
    out = []
    for e, s0 in sorted(firsts.items(), key=lambda kv: (kv[1], kv[0])):
        first = by_key[(*keys[e], snaps[s0])]
        last = by_key[(*keys[e], snaps[-1])]
        out.append({"entity_id": keys[e][0], "failure_mode": keys[e][1], "first_flag_date": snaps[s0].isoformat(),
                    "rate_ratio": _round(first[7]), "p_value": first[8], **first[9],
                    "latest": {"rate_ratio": _round(last[7]), "p_value": last[8], "claims": last[9]["claims"],
                               "expected": last[9]["expected"]}})
    return out


def distributor_summary(conn, detector):
    """Per distributor: first flag and its flag events (a stuffing window x category, or a run of at-risk weeks)."""
    return [{"entity_id": r[0], "region": r[1], "first_flag_date": r[2].isoformat(), "min_effect_size": float(r[3]),
             "max_effect_size": float(r[4]), "events": r[5]}
            for r in fetch(conn, """
                with events as (
                    select entity_id, region, first_flag_date, details ->> 'fiscal_quarter' as fiscal_quarter,
                           details ->> 'category' as category, max(snapshot_date) as last_snapshot_date,
                           count(*) as snapshots, min(effect_size) as min_effect, max(effect_size) as max_effect,
                           bool_or(details ->> 'status' = 'confirmed') as confirmed
                    from marts.mart_anomaly_flags where detector = %s
                    group by 1, 2, 3, 4, 5
                )
                select entity_id, region, min(first_flag_date), min(min_effect), max(max_effect),
                       jsonb_agg(jsonb_strip_nulls(jsonb_build_object(
                           'first_flag_date', first_flag_date, 'last_snapshot_date', last_snapshot_date,
                           'snapshots', snapshots, 'fiscal_quarter', fiscal_quarter, 'category', category,
                           'min_effect_size', min_effect, 'max_effect_size', max_effect, 'confirmed', confirmed))
                           order by first_flag_date, category)
                from events group by 1, 2 order by 3, 1""", (detector,))]


def lead_times(lot_flags, alarms, as_of):
    """Lead time of each lot_scan flag over the CUSUM on its own plant x failure mode (case_study_comparator)."""
    alarm_of = {(a["plant_id"], a["failure_mode"]): a for a in alarms}
    out = []
    for flag in lot_flags:
        flag_date = date.fromisoformat(flag["first_flag_date"])
        alarm = alarm_of.get((flag["plant_id"], flag["failure_mode"]), {})
        item = {"resin_lot_id": flag["entity_id"], "failure_mode": flag["failure_mode"], "plant_id": flag["plant_id"],
                "flag_date": flag["first_flag_date"], "cusum_first_alarm_month": alarm.get("first_alarm_month")}
        if alarm.get("alarm_month_last_day"):
            weeks = (date.fromisoformat(alarm["alarm_month_last_day"]) - flag_date).days / 7
            item |= {"lead_weeks": round(weeks, 1), "lead_time": f"{weeks:.1f} weeks"}
        else:
            weeks = (as_of - flag_date).days / 7
            item |= {"lead_weeks": None, "lead_time": f"> {weeks:.1f} weeks; the raw count never showed it"}
        out.append(item)
    return out


def main():
    started = time.perf_counter()
    with connect() as conn:
        as_of = fetch(conn, "select as_of_date from raw.generation_run order by generated_at desc limit 1")[0][0]
        snaps = sundays(SPEC["point_in_time"]["first_snapshot"], as_of)
        origin = WINDOW_START
        snap_days = [(s - origin).days for s in snaps]
        as_of_day = (as_of - origin).days

        lot_rows, lot_firsts, lot_keys, lot_meta = lot_scan(conn, snaps, snap_days, origin, as_of_day)
        inst_rows, inst_firsts, inst_keys, inst_meta = installer_scan(conn, snaps, snap_days, origin, as_of_day)
        write_table(conn, lot_rows + inst_rows, as_of)
        alarms, cusum_meta = cusum_alarms(conn, as_of)

        lot_flags = scan_summary(lot_rows, lot_firsts, lot_keys, snaps)
        summary = {
            "as_of": as_of.isoformat(),
            "snapshots": {"first": snaps[0].isoformat(), "last": snaps[-1].isoformat(), "count": len(snaps)},
            "detectors": {
                "lot_scan": {**lot_meta, "flags": lot_flags},
                "installer_scan": {**inst_meta, "flags": scan_summary(inst_rows, inst_firsts, inst_keys, snaps)},
                "stuffing": {"flags": distributor_summary(conn, "stuffing")},
                "distributor_health": {"flags": distributor_summary(conn, "distributor_health")},
            },
            "lead_times": lead_times(lot_flags, alarms, as_of),
            "cusum": {**cusum_meta, "series": alarms},
            "runtime_seconds": round(time.perf_counter() - started, 1),
        }
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "latest.json").write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8", newline="\n")
    d = summary["detectors"]
    print(f"as_of {as_of}; flagged lot_scan={len(d['lot_scan']['flags'])} installer_scan="
          f"{len(d['installer_scan']['flags'])} stuffing={len(d['stuffing']['flags'])} "
          f"distributor_health={len(d['distributor_health']['flags'])}; {summary['runtime_seconds']}s")


if __name__ == "__main__":
    main()
